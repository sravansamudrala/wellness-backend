from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.gym.exercise import Equipment, Exercise, MuscleGroup


class CatalogService:
    """Read-only access to the Exercise Catalog master data."""

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