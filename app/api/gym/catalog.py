from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.schemas.gym.exercise import (
    EquipmentResponse,
    ExerciseResponse,
    MuscleGroupResponse,
)
from app.services.gym.catalog_service import CatalogService

router = APIRouter(tags=["Gym — Catalog"])


@router.get("/exercises", response_model=List[ExerciseResponse])
def list_exercises(
    muscle: Optional[UUID] = Query(default=None),
    equipment: Optional[UUID] = Query(default=None),
    q: Optional[str] = Query(default=None),
):
    db: Session = SessionLocal()

    try:
        return CatalogService.list_exercises(db, muscle=muscle, equipment=equipment, q=q)
    finally:
        db.close()


@router.get("/exercises/{exercise_id}", response_model=ExerciseResponse)
def get_exercise(exercise_id: UUID):
    db: Session = SessionLocal()

    try:
        exercise = CatalogService.get_exercise(db, exercise_id)
        if exercise is None:
            raise HTTPException(status_code=404, detail="Exercise not found")
        return exercise
    finally:
        db.close()


@router.get("/muscle-groups", response_model=List[MuscleGroupResponse])
def list_muscle_groups():
    db: Session = SessionLocal()

    try:
        return CatalogService.list_muscle_groups(db)
    finally:
        db.close()


@router.get("/equipment", response_model=List[EquipmentResponse])
def list_equipment():
    db: Session = SessionLocal()

    try:
        return CatalogService.list_equipment(db)
    finally:
        db.close()