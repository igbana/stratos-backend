from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from models.database import get_db, Video, Like, Save, User
from routes.auth import get_user
from utils.cloudinary_helper import upload_video as upload_video_to_cloudinary
from utils.ranking import record_video_event, rank_trending_videos
import uuid

router = APIRouter()

class VideoEventIn(BaseModel):
    event_type: str
    value: float | None = None

class VideoViewIn(BaseModel):
    watch_seconds: float | None = None
    completed: bool = False
    replayed: bool = False
    skipped: bool = False

@router.get("/trending")
def trending(db: Session = Depends(get_db), user: User = Depends(get_user)):
    videos = rank_trending_videos(db, user)
    return {"videos": [v.to_dict(user.id) for v in videos]}

@router.get("/liked")
def liked(db: Session = Depends(get_db), user: User = Depends(get_user)):
    likes = db.query(Like).filter(Like.user_id == user.id).all()
    return {"videos": [l.video.to_dict(user.id) for l in likes if l.video]}

@router.get("/saved")
def saved(db: Session = Depends(get_db), user: User = Depends(get_user)):
    saves = db.query(Save).filter(Save.user_id == user.id).all()
    return {"videos": [s.video.to_dict(user.id) for s in saves if s.video]}

@router.post("/{video_id}/like")
def like_video(video_id: str, db: Session = Depends(get_db),
               user: User = Depends(get_user)):
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(404, "Video not found")
    existing = db.query(Like).filter(
        Like.user_id == user.id, Like.video_id == video_id).first()
    if existing:
        db.delete(existing); db.commit()
        return {"liked": False}
    db.add(Like(id=str(uuid.uuid4()), user_id=user.id, video_id=video_id))
    record_video_event(db, video_id, "like", user.id)
    db.commit()
    return {"liked": True}

@router.post("/{video_id}/save")
def save_video(video_id: str, db: Session = Depends(get_db),
               user: User = Depends(get_user)):
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(404, "Video not found")
    existing = db.query(Save).filter(
        Save.user_id == user.id, Save.video_id == video_id).first()
    if existing:
        db.delete(existing); db.commit()
        return {"saved": False}
    db.add(Save(id=str(uuid.uuid4()), user_id=user.id, video_id=video_id))
    record_video_event(db, video_id, "save", user.id)
    db.commit()
    return {"saved": True}

@router.post("/{video_id}/view")
def view_video(video_id: str, body: VideoViewIn | None = None,
               db: Session = Depends(get_db),
               user: User = Depends(get_user)):
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(404, "Video not found")

    video.views = (video.views or 0) + 1
    record_video_event(db, video_id, "view", user.id)
    if body and body.watch_seconds:
        record_video_event(db, video_id, "watch_time", user.id, body.watch_seconds)
    if body and body.completed:
        record_video_event(db, video_id, "complete", user.id)
    if body and body.replayed:
        record_video_event(db, video_id, "replay", user.id)
    if body and body.skipped:
        record_video_event(db, video_id, "skip", user.id)

    db.commit()
    db.refresh(video)
    return {"views": video.views}

@router.post("/{video_id}/event")
def track_video_event(video_id: str, body: VideoEventIn,
                      db: Session = Depends(get_db),
                      user: User = Depends(get_user)):
    allowed_events = {
        "share", "profile_click", "fund_click", "report",
        "complete", "replay", "skip", "watch_time",
    }
    if body.event_type not in allowed_events:
        raise HTTPException(400, "Unsupported video event")
    if not db.query(Video).filter(Video.id == video_id).first():
        raise HTTPException(404, "Video not found")

    record_video_event(db, video_id, body.event_type, user.id, body.value)
    db.commit()
    return {"tracked": True}

@router.post("/upload")
async def upload_video(caption: str = Form(...), video: UploadFile = File(...),
                       db: Session = Depends(get_db),
                       user: User = Depends(get_user)):
    try:
        upload = await run_in_threadpool(
            upload_video_to_cloudinary,
            video.file,
            filename=video.filename,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Video upload failed: {exc}")
    finally:
        await video.close()

    vid = Video(id=str(uuid.uuid4()), user_id=user.id,
                caption=caption, video_url=upload["url"],
                thumbnail_url=upload["thumbnail_url"],
                duration=upload["duration"])
    db.add(vid); db.commit(); db.refresh(vid)
    return {"video": vid.to_dict(user.id)}
