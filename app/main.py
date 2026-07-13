from fastapi import FastAPI
from sqlalchemy import text
from fastapi.middleware.cors import CORSMiddleware

from app.database.base import Base
from app.database.session import engine, SessionLocal
import app.models
from app.api.skincare import router as skincare_router
from app.api.reminder_settings import router as reminder_settings_router
from app.api.push import router as push_router
from app.api.gym import router as gym_router

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:4173",
    ],
    # Match every Vercel deployment URL for this project (production alias +
    # per-deploy/preview hashes like wellness-tracker-<hash>-ssk12.vercel.app),
    # so a new Vercel URL never breaks CORS again. The API has no auth, so this
    # is not a security boundary.
    allow_origin_regex=r"https://wellness-tracker.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create all database tables
Base.metadata.create_all(bind=engine)

app.include_router(skincare_router)
app.include_router(reminder_settings_router)
app.include_router(push_router)
app.include_router(gym_router)

@app.get("/")
def root():
    return {"message": "AI Wellness API is running"}


@app.get("/health/db")
def database_health():

    db = SessionLocal()

    try:
        result = db.execute(text("SELECT 1"))
        value = result.scalar()

        return {
            "database": "Connected",
            "result": value
        }

    finally:
        db.close()