from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database.session import SessionLocal
from app.schemas.gym.exercise import (
    ExerciseCreateRequest,
    ExerciseResponse,
    ExerciseUpdateRequest,
    MuscleGroupResponse,
)
from app.services.gym.catalog_service import CatalogService

router = APIRouter(tags=["Gym — Catalog"])


@router.post("/exercises", response_model=ExerciseResponse)
def create_exercise(
    request: ExerciseCreateRequest,
    _user_id: UUID = Depends(get_current_user),
):
    """Add a custom exercise to the catalog (shared). Auth-gated like the rest."""
    db: Session = SessionLocal()

    try:
        return CatalogService.create_exercise(
            db, request.name, request.muscle_group_id, request.category
        )
    finally:
        db.close()

# NOTE: the catalog is SHARED master data — same for every user, so we do NOT
# filter by user_id. The `_user_id` param only requires a valid login (auth
# gate); its value is intentionally unused.


@router.get("/exercises", response_model=List[ExerciseResponse])
def list_exercises(
    muscle: Optional[UUID] = Query(default=None),
    q: Optional[str] = Query(default=None),
    _user_id: UUID = Depends(get_current_user),
):
    db: Session = SessionLocal()

    try:
        return CatalogService.list_exercises(db, muscle=muscle, q=q)
    finally:
        db.close()


@router.get("/exercises/{exercise_id}", response_model=ExerciseResponse)
def get_exercise(
    exercise_id: UUID,
    _user_id: UUID = Depends(get_current_user),
):
    db: Session = SessionLocal()

    try:
        exercise = CatalogService.get_exercise(db, exercise_id)
        if exercise is None:
            raise HTTPException(status_code=404, detail="Exercise not found")
        return exercise
    finally:
        db.close()


@router.put("/exercises/{exercise_id}", response_model=ExerciseResponse)
def update_exercise(
    exercise_id: UUID,
    request: ExerciseUpdateRequest,
    _user_id: UUID = Depends(get_current_user),
):
    db: Session = SessionLocal()

    try:
        exercise, error = CatalogService.update_exercise(db, exercise_id, request.name)
        if error == "not_found":
            raise HTTPException(status_code=404, detail="Exercise not found")
        if error is not None:
            raise HTTPException(status_code=400, detail=error)
        return exercise
    finally:
        db.close()


@router.delete("/exercises/{exercise_id}")
def delete_exercise(
    exercise_id: UUID,
    _user_id: UUID = Depends(get_current_user),
):
    db: Session = SessionLocal()

    try:
        _deleted, error = CatalogService.delete_exercise(db, exercise_id)
        if error == "not_found":
            raise HTTPException(status_code=404, detail="Exercise not found")
        if error is not None:
            raise HTTPException(status_code=400, detail=error)
        return {"status": "ok"}
    finally:
        db.close()


@router.get("/muscle-groups", response_model=List[MuscleGroupResponse])
def list_muscle_groups(_user_id: UUID = Depends(get_current_user)):
    db: Session = SessionLocal()

    try:
        return CatalogService.list_muscle_groups(db)
    finally:
        db.close()
