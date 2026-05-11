from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from models.database import get_db, User, Follow, Video
from routes.auth import get_user
from utils.ranking import record_video_event
import uuid

router = APIRouter()

@router.get("/top")
def top_players(db: Session = Depends(get_db), user: User = Depends(get_user)):
    players = db.query(User).filter(User.role == "player").limit(10).all()
    return {"players": [_player_dict(p, user.id, db) for p in players]}

@router.get("/recommended")
def recommended(db: Session = Depends(get_db), user: User = Depends(get_user)):
    players = db.query(User).filter(
        User.role == "player", User.id != user.id).limit(20).all()
    return {"players": [_player_dict(p, user.id, db) for p in players]}

@router.get("")
def search(q: str = Query(""), db: Session = Depends(get_db),
           user: User = Depends(get_user)):
    players = db.query(User).filter(
        User.role == "player",
        (User.full_name.ilike(f"%{q}%")) | (User.position.ilike(f"%{q}%"))
    ).limit(20).all()
    return {"players": [_player_dict(p, user.id, db) for p in players]}

@router.get("/{user_id}")
def get_player(user_id: str, db: Session = Depends(get_db),
               user: User = Depends(get_user)):
    player = db.query(User).filter(User.id == user_id).first()
    if not player: return {"detail": "Not found"}, 404
    latest_video = db.query(Video).filter(Video.user_id == user_id)\
        .order_by(Video.created_at.desc()).first()
    if latest_video:
        record_video_event(db, latest_video.id, "profile_click", user.id)
        db.commit()
    data = _player_dict(player, user.id, db)
    data["videos"] = [v.to_dict(user.id) for v in player.videos]
    return {"player": data}

@router.post("/{user_id}/follow")
def follow(user_id: str, db: Session = Depends(get_db),
           user: User = Depends(get_user)):
    existing = db.query(Follow).filter(
        Follow.follower_id == user.id,
        Follow.following_id == user_id).first()
    if existing:
        db.delete(existing); db.commit()
        return {"following": False}
    db.add(Follow(id=str(uuid.uuid4()),
                  follower_id=user.id, following_id=user_id))
    latest_video = db.query(Video).filter(Video.user_id == user_id)\
        .order_by(Video.created_at.desc()).first()
    if latest_video:
        record_video_event(db, latest_video.id, "follow", user.id)
    db.commit()
    return {"following": True}

def _is_following(viewer_id, target_id, db):
    return bool(db.query(Follow).filter(
        Follow.follower_id == viewer_id,
        Follow.following_id == target_id).first())

def _player_dict(player: User, viewer_id: str, db):
    return {
        "id": player.id, "username": player.full_name,
        "avatar_url": player.avatar_url, "bio": player.bio,
        "position": player.position, "country": player.country,
        "club": player.club, "age_group": player.age_group,
        "followers": len(player.followers_rel),
        "following": len(player.following_rel),
        "earned": player.earned,
        "is_following": _is_following(viewer_id, player.id, db),
        "videos": [],
    }
