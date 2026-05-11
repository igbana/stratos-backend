from collections import Counter, defaultdict
from datetime import datetime, timedelta
import math
import uuid

from sqlalchemy.orm import Session

from models.database import Follow, User, Video, VideoEvent


EVENT_WEIGHTS = {
    "view": 1.0,
    "watch_time": 0.1,
    "complete": 4.0,
    "replay": 4.0,
    "like": 3.0,
    "save": 5.0,
    "share": 6.0,
    "profile_click": 7.0,
    "follow": 8.0,
    "fund_click": 12.0,
    "fund": 20.0,
    "skip": -3.0,
    "report": -20.0,
}


def record_video_event(
    db: Session,
    video_id: str,
    event_type: str,
    user_id: str | None = None,
    value: float | None = None,
) -> VideoEvent:
    event = VideoEvent(
        id=str(uuid.uuid4()),
        user_id=user_id,
        video_id=video_id,
        event_type=event_type,
        value=value if value is not None else 1.0,
    )
    db.add(event)
    return event


def rank_feed_videos(
    db: Session,
    user: User,
    page: int,
    per_page: int = 10,
) -> list[Video]:
    candidates = (
        db.query(Video)
        .order_by(Video.created_at.desc())
        .limit(max(page * per_page * 5, 100))
        .all()
    )
    context = _build_rank_context(db, user, candidates)
    ranked = sorted(
        candidates,
        key=lambda video: _feed_score(video, user, context),
        reverse=True,
    )
    start = (page - 1) * per_page
    return ranked[start : start + per_page]


def rank_trending_videos(db: Session, user: User, limit: int = 20) -> list[Video]:
    candidates = (
        db.query(Video)
        .order_by(Video.created_at.desc())
        .limit(max(limit * 10, 200))
        .all()
    )
    context = _build_rank_context(db, user, candidates)
    return sorted(
        candidates,
        key=lambda video: _trending_score(video, context),
        reverse=True,
    )[:limit]


def _build_rank_context(db: Session, user: User, videos: list[Video]) -> dict:
    video_ids = [video.id for video in videos]
    since_24h = datetime.utcnow() - timedelta(hours=24)
    since_30d = datetime.utcnow() - timedelta(days=30)

    recent_events = (
        db.query(VideoEvent)
        .filter(VideoEvent.video_id.in_(video_ids), VideoEvent.created_at >= since_24h)
        .all()
        if video_ids
        else []
    )
    recent_by_video = defaultdict(Counter)
    for event in recent_events:
        recent_by_video[event.video_id][event.event_type] += event.value or 1.0

    follows = (
        db.query(Follow.following_id)
        .filter(Follow.follower_id == user.id)
        .all()
    )
    followed_user_ids = {row[0] for row in follows}

    interest_events = (
        db.query(VideoEvent)
        .filter(
            VideoEvent.user_id == user.id,
            VideoEvent.created_at >= since_30d,
            VideoEvent.event_type.in_(("view", "like", "save", "complete", "watch_time")),
        )
        .all()
    )
    interest_video_ids = {event.video_id for event in interest_events}
    interest_videos = (
        db.query(Video).filter(Video.id.in_(interest_video_ids)).all()
        if interest_video_ids
        else []
    )

    position_interest = Counter(
        video.user.position for video in interest_videos if video.user and video.user.position
    )
    country_interest = Counter(
        video.user.country for video in interest_videos if video.user and video.user.country
    )

    return {
        "recent_by_video": recent_by_video,
        "followed_user_ids": followed_user_ids,
        "position_interest": position_interest,
        "country_interest": country_interest,
    }


def _feed_score(video: Video, user: User, context: dict) -> float:
    recent_score = _weighted_recent_events(video, context)
    personalization = _personalization_score(video, user, context)
    creator_quality = _creator_quality_score(video)
    freshness = _freshness_score(video, half_life_hours=36)
    relationship = 1.0 if video.user_id in context["followed_user_ids"] else 0.0

    return (
        0.30 * personalization
        + 0.20 * _normalize(recent_score, 60)
        + 0.15 * freshness
        + 0.15 * creator_quality
        + 0.10 * relationship
        + 0.10 * _diversity_bonus(video, user)
    )


def _trending_score(video: Video, context: dict) -> float:
    velocity = _weighted_recent_events(video, context)
    events = context["recent_by_video"][video.id]
    views = max(events.get("view", 0), 1)
    quality = 0.5 + min(events.get("complete", 0) / views, 1.0)
    if events.get("replay", 0):
        quality += min(events["replay"] / views, 0.5)
    trust_safety = 0.0 if events.get("report", 0) >= 3 else 1.0

    return velocity * quality * _freshness_score(video, half_life_hours=12) * trust_safety


def _weighted_recent_events(video: Video, context: dict) -> float:
    score = 0.0
    for event_type, count in context["recent_by_video"][video.id].items():
        score += EVENT_WEIGHTS.get(event_type, 0.0) * count
    score += len(video.likes) * EVENT_WEIGHTS["like"]
    score += len(video.saves) * EVENT_WEIGHTS["save"]
    return max(score, 0.0)


def _personalization_score(video: Video, user: User, context: dict) -> float:
    if not video.user:
        return 0.0

    score = 0.0
    if video.user_id in context["followed_user_ids"]:
        score += 0.45
    if user.country and video.user.country == user.country:
        score += 0.20
    if user.position and video.user.position == user.position:
        score += 0.20

    position_interest = context["position_interest"]
    if video.user.position and position_interest:
        score += min(position_interest[video.user.position] / 10, 0.25)

    country_interest = context["country_interest"]
    if video.user.country and country_interest:
        score += min(country_interest[video.user.country] / 10, 0.20)

    return min(score, 1.0)


def _creator_quality_score(video: Video) -> float:
    if not video.user:
        return 0.0
    engagement = video.views + 3 * len(video.likes) + 5 * len(video.saves)
    profile_bonus = 0.1 if video.user.position and video.user.country else 0.0
    return min(math.log1p(engagement) / 8 + profile_bonus, 1.0)


def _freshness_score(video: Video, half_life_hours: int) -> float:
    age_hours = max((datetime.utcnow() - video.created_at).total_seconds() / 3600, 0)
    return 1 / (1 + age_hours / half_life_hours)


def _diversity_bonus(video: Video, user: User) -> float:
    if video.user_id == user.id:
        return 0.0
    return 0.5 if video.views < 100 else 0.2


def _normalize(value: float, scale: float) -> float:
    return min(value / scale, 1.0)
