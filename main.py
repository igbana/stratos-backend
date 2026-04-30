from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes import auth, feed, videos, players, payments

app = FastAPI(title="Stratos API", version="1.0.0")

app.add_middleware(CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"])

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(feed.router, prefix="/api/v1/feed", tags=["feed"])
app.include_router(videos.router, prefix="/api/v1/videos", tags=["videos"])
app.include_router(players.router, prefix="/api/v1/players", tags=["players"])
app.include_router(payments.router, prefix="/api/v1/payments", tags=["payments"])