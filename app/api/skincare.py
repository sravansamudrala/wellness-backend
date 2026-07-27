from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database.session import SessionLocal
from app.schemas.skincare import (
    SkincareResponse,
    SkincareStatsResponse,
    SkincareUpdateRequest,
)
from app.schemas.skincare_habit import SkincareHabitResponse, SkincareHabitsUpsertRequest
from app.schemas.skincare_history import SkincareHistoryItem
from app.services.skincare_service import SkincareService

router = APIRouter(
    prefix="/api/v1/skincare",
    tags=["Skincare"]
)


@router.get("/today", response_model=SkincareResponse)
def get_today(user_id: UUID = Depends(get_current_user)):

    db: Session = SessionLocal()

    try:
        return SkincareService.get_today(db, user_id)
    finally:
        db.close()


@router.put("/today", response_model=SkincareResponse)
def update_today(
    request: SkincareUpdateRequest,
    user_id: UUID = Depends(get_current_user),
):

    db: Session = SessionLocal()

    try:
        entry, error = SkincareService.update_today(db, user_id, request)
        if error is not None:
            raise HTTPException(status_code=400, detail=error)
        return entry
    finally:
        db.close()


@router.get("/habits", response_model=List[SkincareHabitResponse])
def list_habits(user_id: UUID = Depends(get_current_user)):

    db: Session = SessionLocal()

    try:
        return SkincareService.list_habits(db, user_id)
    finally:
        db.close()


@router.put("/habits", response_model=List[SkincareHabitResponse])
def upsert_habits(
    request: SkincareHabitsUpsertRequest,
    user_id: UUID = Depends(get_current_user),
):

    db: Session = SessionLocal()

    try:
        habits, error = SkincareService.upsert_habits(db, user_id, request.habits)
        if error == "not_found":
            raise HTTPException(status_code=404, detail="Habit not found")
        if error is not None:
            raise HTTPException(status_code=400, detail=error)
        return habits
    finally:
        db.close()


@router.get("/history", response_model=List[SkincareHistoryItem])
def get_history(user_id: UUID = Depends(get_current_user)):

    db: Session = SessionLocal()

    try:
        return SkincareService.get_history(db, user_id)
    finally:
        db.close()


@router.get("/stats", response_model=SkincareStatsResponse)
def get_stats(user_id: UUID = Depends(get_current_user)):

    db: Session = SessionLocal()

    try:
        return SkincareService.get_stats(db, user_id)
    finally:
        db.close()