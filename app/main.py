from fastapi import FastAPI
from sqlalchemy import text

from app.database.base import Base
from app.database.session import engine, SessionLocal
import app.models
from app.api.skincare import router as skincare_router

app = FastAPI()

# Create all database tables
Base.metadata.create_all(bind=engine)

app.include_router(skincare_router)


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