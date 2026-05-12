from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, EmailStr
from passlib.context import CryptContext
from jose import jwt, JWTError
from datetime import datetime, timedelta
from models.database import get_db, User
from sqlalchemy.orm import Session
import os
import re
import uuid

router = APIRouter()
pwd_ctx = CryptContext(schemes=["bcrypt"])
oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
SECRET = os.getenv("JWT_SECRET", "stratos-super-secret-change-in-prod")
ALGO = "HS256"
PRIVY_APP_ID = os.getenv("PRIVY_APP_ID")
PRIVY_VERIFICATION_KEY = os.getenv("PRIVY_VERIFICATION_KEY", "").replace("\\n", "\n")
PRIVY_ISSUER = "privy.io"
PRIVY_ALGO = "ES256"

class RegisterIn(BaseModel):
    full_name: str
    email: EmailStr
    password: str

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class PrivyAuthIn(BaseModel):
    access_token: str
    create_user: bool = False
    full_name: str | None = None
    email: EmailStr | None = None
    avatar_url: str | None = None
    role: str | None = None

class ProfileIn(BaseModel):
    full_name: str | None = None
    email: EmailStr | None = None
    avatar_url: str | None = None
    role: str | None = None
    bio: str | None = None
    age_group: str | None = None
    position: str | None = None
    country: str | None = None
    club: str | None = None
    organization: str | None = None
    scout_role: str | None = None

def _require_privy_config():
    if not PRIVY_APP_ID or not PRIVY_VERIFICATION_KEY:
        raise HTTPException(500, "Privy auth is not configured")

def make_token(user_id: str) -> str:
    return jwt.encode(
        {"sub": user_id, "exp": datetime.utcnow() + timedelta(days=30)},
        SECRET, algorithm=ALGO)

def verify_app_token(token: str) -> dict:
    return jwt.decode(token, SECRET, algorithms=[ALGO])

def verify_privy_token(token: str) -> dict:
    _require_privy_config()
    try:
        return jwt.decode(
            token,
            PRIVY_VERIFICATION_KEY,
            algorithms=[PRIVY_ALGO],
            audience=PRIVY_APP_ID,
            issuer=PRIVY_ISSUER,
        )
    except JWTError:
        raise HTTPException(401, "Invalid Privy token")

def _fallback_email(privy_user_id: str) -> str:
    local_part = re.sub(r"[^a-zA-Z0-9._+-]", "-", privy_user_id).strip("-")
    return f"{local_part or 'user'}@privy.local"

def _claim_value(claims: dict, *keys: str) -> str | None:
    for key in keys:
        value = claims.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None

def _privy_profile(claims: dict, body: PrivyAuthIn | None = None) -> dict:
    return {
        "email": (
            str(body.email)
            if body and body.email
            else _claim_value(claims, "email")
        ),
        "full_name": (
            body.full_name
            if body and body.full_name
            else _claim_value(claims, "name", "full_name")
        ),
        "avatar_url": (
            body.avatar_url
            if body and body.avatar_url
            else _claim_value(claims, "picture", "avatar_url")
        ),
        "role": body.role if body and body.role else None,
    }

def _upsert_privy_user(claims: dict, db: Session, body: PrivyAuthIn | None = None) -> User:
    privy_user_id = claims.get("sub")
    if not privy_user_id:
        raise HTTPException(401, "Privy token is missing a user id")

    user = db.query(User).filter(User.id == privy_user_id).first()
    profile = _privy_profile(claims, body)

    if not user:
        email = profile["email"] or _fallback_email(privy_user_id)
        existing_email_user = db.query(User).filter(User.email == email).first()
        if existing_email_user:
            return existing_email_user

        if not body or not body.create_user:
            raise HTTPException(404, "User not found")

        user = User(
            id=privy_user_id,
            full_name=(profile["full_name"] or "Privy User"),
            email=email,
            hashed_password="",
            role=(profile["role"] or "player"),
            avatar_url=profile["avatar_url"],
        )
        db.add(user)
    elif body:
        for field in ("full_name", "email", "avatar_url", "role"):
            value = profile[field]
            if value is not None:
                setattr(user, field, value)

    db.commit()
    db.refresh(user)
    return user

def get_user(token: str = Depends(oauth2), db: Session = Depends(get_db)) -> User:
    try:
        payload = verify_app_token(token)
        user = db.query(User).filter(User.id == payload["sub"]).first()
        if not user:
            raise HTTPException(401, "User not found")
        return user
    except JWTError:
        if not PRIVY_APP_ID or not PRIVY_VERIFICATION_KEY:
            raise HTTPException(401, "Invalid token")
        claims = verify_privy_token(token)
        return _upsert_privy_user(claims, db)

@router.get("/config")
def auth_config():
    return {
        "provider": "privy",
        "app_id": PRIVY_APP_ID,
        "login_methods": ["google", "apple"],
        "token_type": "Bearer",
    }

@router.post("/register", status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(400, "Email already registered")
    try:
        user = User(
            id=str(uuid.uuid4()),
            full_name=body.full_name,
            email=body.email,
            hashed_password=pwd_ctx.hash(body.password)[:72],
        )
        db.add(user); db.commit(); db.refresh(user)
        return {"access_token": make_token(user.id), "user": user.to_dict()}
    except Exception as e:
        raise HTTPException(500, f"Registration failed: {e}")

@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not user.hashed_password or not pwd_ctx.verify(body.password, user.hashed_password[:72]):
        raise HTTPException(401, "Invalid credentials")
    return {"access_token": make_token(user.id), "user": user.to_dict()}

@router.post("/privy")
def privy_login(body: PrivyAuthIn, db: Session = Depends(get_db)):
    claims = verify_privy_token(body.access_token)
    user = _upsert_privy_user(claims, db, body)
    return {"access_token": make_token(user.id), "user": user.to_dict()}

@router.patch("/profile")
def update_profile(body: ProfileIn, user: User = Depends(get_user),
                   db: Session = Depends(get_db)):
    for field, val in body.dict(exclude_none=True).items():
        setattr(user, field, val)
    db.commit(); db.refresh(user)
    return {"user": user.to_dict()}

@router.get("/me")
def me(user: User = Depends(get_user)):
    return {"user": user.to_dict()}
