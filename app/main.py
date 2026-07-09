from fastapi import FastAPI
from sqlalchemy import text
from fastapi.middleware.cors import CORSMiddleware

from app.database.base import Base
from app.database.session import engine, SessionLocal
import app.models
from app.api.skincare import router as skincare_router
from app.api.reminder_settings import router as reminder_settings_router

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://wellness-tracker-tan.vercel.app",
        "https://wellness-tracker-fb4jckhh3-ssk12.vercel.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create all database tables
Base.metadata.create_all(bind=engine)

app.include_router(skincare_router)
app.include_router(reminder_settings_router)

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