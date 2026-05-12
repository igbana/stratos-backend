from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, EmailStr
from passlib.context import CryptContext
from jose import jwt, JWTError
from jose.exceptions import JWKError
from datetime import datetime, timedelta
from models.database import get_db, Follow, Like, Payment, Save, User, Video, VideoEvent
from sqlalchemy.orm import Session
import os
import re

router = APIRouter()
pwd_ctx = CryptContext(schemes=["bcrypt"])
oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
SECRET = os.getenv("JWT_SECRET", "stratos-super-secret-change-in-prod")
ALGO = "HS256"
PRIVY_APP_ID = os.getenv("PRIVY_APP_ID")
PRIVY_VERIFICATION_KEY = os.getenv("PRIVY_VERIFICATION_KEY", "")
PRIVY_ISSUER = "privy.io"
PRIVY_ALGO = "ES256"

class PrivyAuthIn(BaseModel):
    access_token: str
    create_user: bool = False
    password: str | None = None
    full_name: str | None = None
    email: EmailStr | None = None
    avatar_url: str | None = None
    country: str | None = None
    age_group: str | None = None
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

def _normalize_pem_key(value: str) -> str:
    key = value.strip().strip('"').strip("'")
    while "\\n" in key or "\\r" in key:
        key = key.replace("\\r", "\r").replace("\\n", "\n")
    key = key.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not key:
        return key

    begin = "-----BEGIN PUBLIC KEY-----"
    end = "-----END PUBLIC KEY-----"
    if begin in key and end in key:
        body = key.replace(begin, "").replace(end, "")
        body = "".join(body.split())
        chunks = [body[i:i + 64] for i in range(0, len(body), 64)]
        return "\n".join([begin, *chunks, end])

    body = "".join(key.split())
    if re.fullmatch(r"[A-Za-z0-9+/=]+", body or "") and len(body) > 100:
        chunks = [body[i:i + 64] for i in range(0, len(body), 64)]
        return "\n".join([begin, *chunks, end])

    return key

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
            _normalize_pem_key(PRIVY_VERIFICATION_KEY),
            algorithms=[PRIVY_ALGO],
            audience=PRIVY_APP_ID,
            issuer=PRIVY_ISSUER,
        )
    except JWKError:
        raise HTTPException(
            500,
            "Privy verification key is malformed. Use the Privy app verification key PEM, not the client ID or app secret.",
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
        "country": (
            body.country
            if body and body.country
            else _claim_value(claims, "country", "locale")
        ),
        "age_group": (
            body.age_group
            if body and body.age_group
            else _claim_value(claims, "age_group")
        ),
        "role": body.role if body and body.role else None,
    }

def _check_password(user: User, password: str | None):
    if password is None:
        return
    if not user.hashed_password:
        raise HTTPException(401, "Password is not set for this account")
    if not pwd_ctx.verify(password, user.hashed_password[:72]):
        raise HTTPException(401, "Invalid password")

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
            if body and body.password and not existing_email_user.hashed_password and body.create_user:
                existing_email_user.hashed_password = pwd_ctx.hash(body.password)[:72]
                db.commit()
                db.refresh(existing_email_user)
            elif body:
                _check_password(existing_email_user, body.password)
            return existing_email_user

        if not body or not body.create_user:
            raise HTTPException(404, "User not found")

        user = User(
            id=privy_user_id,
            full_name=(profile["full_name"] or "Privy User"),
            email=email,
            hashed_password=pwd_ctx.hash(body.password)[:72] if body.password else "",
            role=(profile["role"] or "player"),
            avatar_url=profile["avatar_url"],
            country=profile["country"],
            age_group=profile["age_group"],
        )
        db.add(user)
    elif body:
        if body.password and not user.hashed_password and body.create_user:
            user.hashed_password = pwd_ctx.hash(body.password)[:72]
        else:
            _check_password(user, body.password)
        for field in ("full_name", "email", "avatar_url", "country", "age_group", "role"):
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
        "login_methods": ["email", "google", "apple"],
        "token_type": "Bearer",
    }

@router.post("/register", status_code=201)
def register():
    raise HTTPException(410, "Email signup is handled by Privy")

@router.post("/login")
def login():
    raise HTTPException(410, "Email login is handled by Privy")

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

@router.delete("/me")
def delete_me(user: User = Depends(get_user), db: Session = Depends(get_db)):
    video_ids = [
        video_id
        for (video_id,) in db.query(Video.id).filter(Video.user_id == user.id).all()
    ]

    db.query(VideoEvent).filter(VideoEvent.user_id == user.id).delete(
        synchronize_session=False
    )
    db.query(Like).filter(Like.user_id == user.id).delete(synchronize_session=False)
    db.query(Save).filter(Save.user_id == user.id).delete(synchronize_session=False)
    db.query(Follow).filter(
        (Follow.follower_id == user.id) | (Follow.following_id == user.id)
    ).delete(synchronize_session=False)
    db.query(Payment).filter(
        (Payment.payer_id == user.id) | (Payment.recipient_id == user.id)
    ).delete(synchronize_session=False)

    if video_ids:
        db.query(VideoEvent).filter(VideoEvent.video_id.in_(video_ids)).delete(
            synchronize_session=False
        )
        db.query(Like).filter(Like.video_id.in_(video_ids)).delete(
            synchronize_session=False
        )
        db.query(Save).filter(Save.video_id.in_(video_ids)).delete(
            synchronize_session=False
        )
        db.query(Video).filter(Video.id.in_(video_ids)).delete(
            synchronize_session=False
        )

    db.delete(user)
    db.commit()
    return {"deleted": True}
