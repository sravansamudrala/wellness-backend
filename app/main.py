from fastapi import FastAPI, Request
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
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.core.rate_limit import limiter

app = FastAPI()

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
    # security boundary.
    allow_origin_regex=r"https://wellness-tracker.*\.vercel\.app",
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

@app.get("/")
def root():
    return {"message": "AI Wellness API is running"}


@app.get("/debug/ip")
def debug_ip(request: Request):
    """TEMPORARY — remove once we've confirmed how Render forwards client IPs
    to the rate limiter's key_func. Not auth-gated on purpose: we need to hit
    it from arbitrary networks (phone, laptop, etc) to compare results."""
    return {
        "client_host": request.client.host if request.client else None,
        "x_forwarded_for": request.headers.get("x-forwarded-for"),
        "true_client_ip": request.headers.get("true-client-ip"),
        "cf_connecting_ip": request.headers.get("cf-connecting-ip"),
    }


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
