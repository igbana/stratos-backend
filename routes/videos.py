from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from models.database import get_db, Video, Like, Save, User
from routes.auth import get_user
from utils.cloudinary_helper import upload_video as upload_video_to_cloudinary
import uuid

router = APIRouter()

@router.get("/trending")
def trending(db: Session = Depends(get_db), user: User = Depends(get_user)):
    videos = db.query(Video).order_by(Video.views.desc()).limit(20).all()
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
    existing = db.query(Like).filter(
        Like.user_id == user.id, Like.video_id == video_id).first()
    if existing:
        db.delete(existing); db.commit()
        return {"liked": False}
    db.add(Like(id=str(uuid.uuid4()), user_id=user.id, video_id=video_id))
    db.commit()
    return {"liked": True}

@router.post("/{video_id}/save")
def save_video(video_id: str, db: Session = Depends(get_db),
               user: User = Depends(get_user)):
    existing = db.query(Save).filter(
        Save.user_id == user.id, Save.video_id == video_id).first()
    if existing:
        db.delete(existing); db.commit()
        return {"saved": False}
    db.add(Save(id=str(uuid.uuid4()), user_id=user.id, video_id=video_id))
    db.commit()
    return {"saved": True}

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
