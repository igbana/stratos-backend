from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, EmailStr
from passlib.context import CryptContext
from jose import jwt, JWTError
from datetime import datetime, timedelta
from models.database import get_db, User
from sqlalchemy.orm import Session
import os, uuid

router = APIRouter()
pwd_ctx = CryptContext(schemes=["bcrypt"])
oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
SECRET = os.getenv("JWT_SECRET", "stratos-super-secret-change-in-prod")
ALGO = "HS256"

class RegisterIn(BaseModel):
    full_name: str; email: EmailStr; password: str

class LoginIn(BaseModel):
    email: EmailStr; password: str

class ProfileIn(BaseModel):
    bio: str | None = None; age_group: str | None = None
    position: str | None = None; country: str | None = None
    club: str | None = None; organization: str | None = None
    scout_role: str | None = None

def make_token(user_id: str) -> str:
    return jwt.encode(
        {"sub": user_id, "exp": datetime.utcnow() + timedelta(days=30)},
        SECRET, algorithm=ALGO)

def get_user(token: str = Depends(oauth2), db: Session = Depends(get_db)) -> User:
    try:
        payload = jwt.decode(token, SECRET, algorithms=[ALGO])
        user = db.query(User).filter(User.id == payload["sub"]).first()
        if not user: raise HTTPException(401, "User not found")
        return user
    except JWTError:
        raise HTTPException(401, "Invalid token")

@router.post("/register", status_code=201)
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(400, "Email already registered")
    try:
        user = User(id=str(uuid.uuid4()), full_name=body.full_name, email=body.email, hashed_password=pwd_ctx.hash(body.password)[:72])
        db.add(user); db.commit(); db.refresh(user)
        return {"access_token": make_token(user.id), "user": user.to_dict()}
    except Exception as e:
        raise HTTPException(500, f"Registration failed: {e}")

@router.post("/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not pwd_ctx.verify(body.password, user.hashed_password[:72]):
        raise HTTPException(401, "Invalid credentials")
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