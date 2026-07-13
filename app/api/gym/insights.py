from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
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
def get_stats(user_id: UUID = Depends(get_current_user)):
    db: Session = SessionLocal()

    try:
        return InsightsService.get_stats(db, user_id)
    finally:
        db.close()


@router.get("/insights/volume", response_model=VolumeResponse)
def get_volume(
    range: str = Query(default="all"),
    user_id: UUID = Depends(get_current_user),
):
    db: Session = SessionLocal()

    try:
        return InsightsService.get_volume(db, user_id, range=range)
    finally:
        db.close()


@router.get("/insights/records", response_model=List[RecordResponse])
def get_records(user_id: UUID = Depends(get_current_user)):
    db: Session = SessionLocal()

    try:
        return InsightsService.get_records(db, user_id)
    finally:
        db.close()


@router.get("/insights/recovery", response_model=List[RecoveryItem])
def get_recovery(user_id: UUID = Depends(get_current_user)):
    db: Session = SessionLocal()

    try:
        return InsightsService.get_recovery(db, user_id)
    finally:
        db.close()
