from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, EmailStr
from jose import jwt, JWTError
from models.database import get_db, User
from sqlalchemy.orm import Session
import os
import re

router = APIRouter()
oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
PRIVY_APP_ID = os.getenv("PRIVY_APP_ID")
PRIVY_VERIFICATION_KEY = os.getenv("PRIVY_VERIFICATION_KEY", "").replace("\\n", "\n")
PRIVY_ISSUER = "privy.io"
PRIVY_ALGO = "ES256"

class PrivyAuthIn(BaseModel):
    access_token: str
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

def _upsert_privy_user(claims: dict, db: Session, body: PrivyAuthIn | None = None) -> User:
    privy_user_id = claims.get("sub")
    if not privy_user_id:
        raise HTTPException(401, "Privy token is missing a user id")

    user = db.query(User).filter(User.id == privy_user_id).first()
    if not user:
        user = User(
            id=privy_user_id,
            full_name=(body.full_name if body and body.full_name else "Privy User"),
            email=(body.email if body and body.email else _fallback_email(privy_user_id)),
            hashed_password="",
            role=(body.role if body and body.role else "player"),
            avatar_url=(body.avatar_url if body else None),
        )
        db.add(user)
    elif body:
        for field in ("full_name", "email", "avatar_url", "role"):
            value = getattr(body, field)
            if value is not None:
                setattr(user, field, value)

    db.commit()
    db.refresh(user)
    return user

def get_user(token: str = Depends(oauth2), db: Session = Depends(get_db)) -> User:
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

@router.post("/login")
def login(body: PrivyAuthIn, db: Session = Depends(get_db)):
    claims = verify_privy_token(body.access_token)
    user = _upsert_privy_user(claims, db, body)
    return {"access_token": body.access_token, "user": user.to_dict()}

@router.post("/register", status_code=201)
def register(body: PrivyAuthIn, db: Session = Depends(get_db)):
    return login(body, db)

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
