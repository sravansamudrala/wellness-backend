from typing import List

from fastapi import APIRouter, Query
from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.schemas.gym.insights import (
    GymStatsResponse,
    RecordResponse,
    RecoveryItem,
    VolumeResponse,
)
from app.services.gym.insights_service import InsightsService

router = APIRouter(tags=["Gym — Insights"])


@router.get("/insights/stats", response_model=GymStatsResponse)
def get_stats():
    db: Session = SessionLocal()

    try:
        return InsightsService.get_stats(db)
    finally:
        db.close()


@router.get("/insights/volume", response_model=VolumeResponse)
def get_volume(range: str = Query(default="all")):
    db: Session = SessionLocal()

    try:
        return InsightsService.get_volume(db, range=range)
    finally:
        db.close()


@router.get("/insights/records", response_model=List[RecordResponse])
def get_records():
    db: Session = SessionLocal()

    try:
        return InsightsService.get_records(db)
    finally:
        db.close()


@router.get("/insights/recovery", response_model=List[RecoveryItem])
def get_recovery():
    db: Session = SessionLocal()

    try:
        return InsightsService.get_recovery(db)
    finally:
        db.close()