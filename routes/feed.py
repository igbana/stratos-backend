from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from models.database import get_db, Video, User
from routes.auth import get_user

router = APIRouter()

@router.get("")
def get_feed(page: int = Query(1), db: Session = Depends(get_db),
             user: User = Depends(get_user)):
    offset = (page - 1) * 10
    videos = db.query(Video).order_by(Video.created_at.desc())\
        .offset(offset).limit(10).all()
    return {"videos": [v.to_dict(user.id) for v in videos], "page": page}