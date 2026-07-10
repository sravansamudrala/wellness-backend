from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.schemas.gym.session import (
    LogSetsRequest,
    StartSessionRequest,
    WorkoutSessionDetailResponse,
    WorkoutSessionResponse,
)
from app.schemas.gym.state import (
    ActiveWorkoutResponse,
    GymStateResponse,
    GymStateUpdateRequest,
)
from app.services.gym.workout_service import WorkoutService

router = APIRouter(tags=["Gym — Workouts"])


# ----- Active workout + cursor state -----

@router.get("/active", response_model=ActiveWorkoutResponse)
def get_active():
    db: Session = SessionLocal()

    try:
        return WorkoutService.get_active(db)
    finally:
        db.close()


@router.get("/state", response_model=GymStateResponse)
def get_state():
    db: Session = SessionLocal()

    try:
        return WorkoutService.get_state(db)
    finally:
        db.close()


@router.put("/state", response_model=GymStateResponse)
def update_state(request: GymStateUpdateRequest):
    db: Session = SessionLocal()

    try:
        return WorkoutService.update_state(db, request)
    finally:
        db.close()


# ----- Sessions -----

@router.get("/sessions/current", response_model=Optional[WorkoutSessionDetailResponse])
def get_current_session():
    db: Session = SessionLocal()

    try:
        return WorkoutService.get_current_session_detail(db)
    finally:
        db.close()


@router.post("/sessions/start", response_model=WorkoutSessionDetailResponse)
def start_session(request: StartSessionRequest):
    db: Session = SessionLocal()

    try:
        return WorkoutService.start_session(db, request)
    finally:
        db.close()


@router.put("/sessions/{session_id}/sets", response_model=WorkoutSessionDetailResponse)
def log_sets(session_id: UUID, request: LogSetsRequest):
    db: Session = SessionLocal()

    try:
        session = WorkoutService.log_sets(db, session_id, request)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return session
    finally:
        db.close()


@router.post("/sessions/{session_id}/complete", response_model=WorkoutSessionDetailResponse)
def complete_session(session_id: UUID):
    db: Session = SessionLocal()

    try:
        session = WorkoutService.complete_session(db, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return session
    finally:
        db.close()


@router.post("/sessions/{session_id}/abandon", response_model=WorkoutSessionDetailResponse)
def abandon_session(session_id: UUID):
    db: Session = SessionLocal()

    try:
        session = WorkoutService.abandon_session(db, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return session
    finally:
        db.close()


@router.get("/sessions", response_model=List[WorkoutSessionResponse])
def get_history():
    db: Session = SessionLocal()

    try:
        return WorkoutService.get_history(db)
    finally:
        db.close()


@router.get("/sessions/{session_id}", response_model=WorkoutSessionDetailResponse)
def get_session(session_id: UUID):
    db: Session = SessionLocal()

    try:
        session = WorkoutService.get_session(db, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return session
    finally:
        db.close()