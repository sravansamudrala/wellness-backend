from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database.session import SessionLocal
from app.schemas.gym.session import (
    QuickLogRequest,
    WorkoutSessionDetailResponse,
    WorkoutSessionResponse,
)
from app.schemas.gym.state import (
    GymStateResponse,
    GymStateUpdateRequest,
    NextCategoryResponse,
)
from app.services.gym.workout_service import WorkoutService

router = APIRouter(tags=["Gym — Workouts"])


# ----- State (unit preference + rotation order) -----

@router.get("/state", response_model=GymStateResponse)
def get_state(user_id: UUID = Depends(get_current_user)):
    db: Session = SessionLocal()

    try:
        return WorkoutService.get_state(db, user_id)
    finally:
        db.close()


@router.put("/state", response_model=GymStateResponse)
def update_state(
    request: GymStateUpdateRequest,
    user_id: UUID = Depends(get_current_user),
):
    db: Session = SessionLocal()

    try:
        return WorkoutService.update_state(db, user_id, request)
    finally:
        db.close()


@router.get("/log/next-category", response_model=NextCategoryResponse)
def get_next_category(user_id: UUID = Depends(get_current_user)):
    db: Session = SessionLocal()

    try:
        return {"muscle_group": WorkoutService.get_next_log_category(db, user_id)}
    finally:
        db.close()


# ----- Sessions -----

@router.post("/sessions/quick-log", response_model=WorkoutSessionDetailResponse)
def quick_log(
    request: QuickLogRequest,
    user_id: UUID = Depends(get_current_user),
):
    db: Session = SessionLocal()

    try:
        return WorkoutService.quick_log(db, user_id, request)
    finally:
        db.close()


@router.get("/sessions", response_model=List[WorkoutSessionResponse])
def get_history(user_id: UUID = Depends(get_current_user)):
    db: Session = SessionLocal()

    try:
        return WorkoutService.get_history(db, user_id)
    finally:
        db.close()


@router.get("/sessions/{session_id}", response_model=WorkoutSessionDetailResponse)
def get_session(
    session_id: UUID,
    user_id: UUID = Depends(get_current_user),
):
    db: Session = SessionLocal()

    try:
        session = WorkoutService.get_session(db, user_id, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return session
    finally:
        db.close()
