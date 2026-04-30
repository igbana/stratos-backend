from sqlalchemy import create_engine, Column, String, Float, Integer, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import os

# DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./stratos.db")
# engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False}
#                        if "sqlite" in DATABASE_URL else {})

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL environment variable is not set")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)

SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="player")
    avatar_url = Column(String)
    bio = Column(Text)
    age_group = Column(String)
    position = Column(String)
    country = Column(String)
    club = Column(String)
    organization = Column(String)
    scout_role = Column(String)
    earned = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    videos = relationship("Video", back_populates="user")
    followers_rel = relationship("Follow", foreign_keys="Follow.following_id", back_populates="following")
    following_rel = relationship("Follow", foreign_keys="Follow.follower_id", back_populates="follower")

    def to_dict(self):
        return {
            "id": self.id, "full_name": self.full_name, "email": self.email,
            "role": self.role, "avatar_url": self.avatar_url, "bio": self.bio,
            "age_group": self.age_group, "position": self.position,
            "country": self.country, "club": self.club,
            "organization": self.organization, "scout_role": self.scout_role,
            "earned": self.earned,
            "followers": len(self.followers_rel),
            "following": len(self.following_rel),
        }

class Video(Base):
    __tablename__ = "videos"
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"))
    caption = Column(Text)
    video_url = Column(String)
    thumbnail_url = Column(String)
    duration = Column(Integer, default=0)
    views = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    user = relationship("User", back_populates="videos")
    likes = relationship("Like", back_populates="video")
    saves = relationship("Save", back_populates="video")

    def to_dict(self, current_user_id=None):
        return {
            "id": self.id, "user_id": self.user_id,
            "username": self.user.full_name if self.user else "",
            "user_avatar_url": self.user.avatar_url if self.user else None,
            "caption": self.caption, "video_url": self.video_url,
            "thumbnail_url": self.thumbnail_url, "duration": self.duration,
            "views": self.views, "likes": len(self.likes),
            "saves": len(self.saves),
            "is_liked": any(l.user_id == current_user_id for l in self.likes),
            "is_saved": any(s.user_id == current_user_id for s in self.saves),
            "created_at": self.created_at.isoformat(),
        }

class Follow(Base):
    __tablename__ = "follows"
    id = Column(String, primary_key=True)
    follower_id = Column(String, ForeignKey("users.id"))
    following_id = Column(String, ForeignKey("users.id"))
    follower = relationship("User", foreign_keys=[follower_id], back_populates="following_rel")
    following = relationship("User", foreign_keys=[following_id], back_populates="followers_rel")

class Like(Base):
    __tablename__ = "likes"
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"))
    video_id = Column(String, ForeignKey("videos.id"))
    video = relationship("Video", back_populates="likes")

class Save(Base):
    __tablename__ = "saves"
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"))
    video_id = Column(String, ForeignKey("videos.id"))
    video = relationship("Video", back_populates="saves")

class Payment(Base):
    __tablename__ = "payments"
    id = Column(String, primary_key=True)
    payer_id = Column(String, ForeignKey("users.id"))
    recipient_id = Column(String, ForeignKey("users.id"))
    amount = Column(Float)
    status = Column(String, default="completed")
    created_at = Column(DateTime, default=datetime.utcnow)

# Initialize DB
Base.metadata.create_all(bind=engine)