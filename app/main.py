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
from app.api.auth import router as auth_router
from app.api.water import router as water_router
from app.api.food import router as food_router
from app.api.feature_flags import router as feature_flags_router
from app.api.electricity import router as electricity_router
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.logging import setup_logging

setup_logging()
app = FastAPI(
    docs_url="/docs" if settings.enable_api_docs else None,
    redoc_url="/redoc" if settings.enable_api_docs else None,
    openapi_url="/openapi.json" if settings.enable_api_docs else None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:4173",
    ],
    # Match every Vercel deployment URL for this project (production alias +
    # per-deploy/preview hashes like wellness-tracker-<hash>-ssk12.vercel.app),
    # so a new Vercel URL never breaks CORS again. Authorization is enforced by
    # the JWT gate (app/api/deps.py), not by this allow-list — CORS only
    # controls which browser origins may call the API, it isn't itself a
    # security boundary. Also match any localhost port — Vite auto-increments
    # (5173 -> 5174 -> ...) whenever the default port is already taken, so a
    # fixed allow_origins entry breaks the moment that happens.
    #
    # Two project-name prefixes are matched because the Vercel project was
    # renamed (aiwellnesstracker) but the original wellness-tracker*.vercel.app
    # domain is still a live alias to the same deployment — found 2026-07-29
    # when login broke with a CORS error because the old regex only matched
    # the pre-rename prefix.
    allow_origin_regex=r"https://(wellness-tracker|aiwellnesstracker).*\.vercel\.app|http://localhost:\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create all database tables
Base.metadata.create_all(bind=engine)

app.include_router(auth_router)
app.include_router(skincare_router)
app.include_router(reminder_settings_router)
app.include_router(push_router)
app.include_router(gym_router)
app.include_router(water_router)
app.include_router(food_router)
app.include_router(feature_flags_router)
app.include_router(electricity_router)

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
