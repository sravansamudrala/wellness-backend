from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.gym.exercise import Equipment, Exercise, MuscleGroup


class CatalogService:
    """Access to the Exercise Catalog master data (shared across users)."""

    @staticmethod
    def create_exercise(
        db: Session,
        name: str,
        muscle_group_id: Optional[UUID] = None,
        category: Optional[str] = None,
    ) -> Exercise:
        """Add a user-created exercise to the (shared) catalog.

        Idempotent-ish: if an exercise with the same name already exists, return
        it instead of creating a duplicate (exercises.name is unique).
        """
        name = name.strip()
        existing = db.query(Exercise).filter(Exercise.name == name).first()
        if existing is not None:
            return existing

        exercise = Exercise(
            name=name,
            primary_muscle_group_id=muscle_group_id,
            category=category,
            is_custom=True,
        )
        db.add(exercise)
        db.commit()
        db.refresh(exercise)
        return exercise

    @staticmethod
    def list_exercises(
        db: Session,
        muscle: Optional[UUID] = None,
        equipment: Optional[UUID] = None,
        q: Optional[str] = None,
    ):
        query = db.query(Exercise)

        if muscle is not None:
            query = query.filter(Exercise.primary_muscle_group_id == muscle)
        if equipment is not None:
            query = query.filter(Exercise.equipment_id == equipment)
        if q:
            query = query.filter(Exercise.name.ilike(f"%{q}%"))

        return query.order_by(Exercise.name.asc()).all()

    @staticmethod
    def get_exercise(db: Session, exercise_id: UUID):
        return db.query(Exercise).filter(Exercise.id == exercise_id).first()

    @staticmethod
    def list_muscle_groups(db: Session):
        return db.query(MuscleGroup).order_by(MuscleGroup.name.asc()).all()

    @staticmethod
    def list_equipment(db: Session):
        return db.query(Equipment).order_by(Equipment.name.asc()).all()