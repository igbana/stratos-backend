from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from models.database import get_db, Video, User
from routes.auth import get_user
from utils.ranking import rank_feed_videos

router = APIRouter()

@router.get("")
def get_feed(page: int = Query(1), db: Session = Depends(get_db),
             user: User = Depends(get_user)):
    videos = rank_feed_videos(db, user, page)
    return {"videos": [v.to_dict(user.id) for v in videos], "page": page}
