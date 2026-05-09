from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from models.database import get_db, Video, User
from routes.auth import get_user

router = APIRouter()

@router.get("/me/videos")
def my_videos(db: Session = Depends(get_db), user: User = Depends(get_user)):
    videos = (
        db.query(Video)
        .filter(Video.user_id == user.id)
        .order_by(Video.created_at.desc())
        .all()
    )
    return {"videos": [v.to_dict(user.id) for v in videos]}

@router.get("/{user_id}/videos")
def user_videos(user_id: str, db: Session = Depends(get_db), user: User = Depends(get_user)):
    videos = (
        db.query(Video)
        .filter(Video.user_id == user_id)
        .order_by(Video.created_at.desc())
        .all()
    )
    return {"videos": [v.to_dict(user.id) for v in videos]}
