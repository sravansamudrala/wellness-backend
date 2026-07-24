from typing import Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.gym.exercise import Exercise, MuscleGroup
from app.models.gym.session import SessionExercise


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
        q: Optional[str] = None,
    ):
        query = db.query(Exercise)

        if muscle is not None:
            query = query.filter(Exercise.primary_muscle_group_id == muscle)
        if q:
            query = query.filter(Exercise.name.ilike(f"%{q}%"))

        return query.order_by(Exercise.name.asc()).all()

    @staticmethod
    def get_exercise(db: Session, exercise_id: UUID):
        return db.query(Exercise).filter(Exercise.id == exercise_id).first()

    @staticmethod
    def update_exercise(
        db: Session, exercise_id: UUID, name: str
    ) -> Tuple[Optional[Exercise], Optional[str]]:
        """Rename an exercise. Returns (exercise, error) — error is None on success,
        "not_found", or a name-conflict message."""
        exercise = db.query(Exercise).filter(Exercise.id == exercise_id).first()
        if exercise is None:
            return None, "not_found"

        name = name.strip()
        clash = db.query(Exercise).filter(Exercise.name == name).first()
        if clash is not None and clash.id != exercise.id:
            return None, f"An exercise named {name!r} already exists."

        exercise.name = name
        db.commit()
        db.refresh(exercise)
        return exercise, None

    @staticmethod
    def delete_exercise(db: Session, exercise_id: UUID) -> Tuple[bool, Optional[str]]:
        """Delete an exercise. Returns (deleted, error) — error is None on success,
        "not_found", or an explanation if it's already been logged."""
        exercise = db.query(Exercise).filter(Exercise.id == exercise_id).first()
        if exercise is None:
            return False, "not_found"

        logged_count = (
            db.query(SessionExercise)
            .filter(SessionExercise.exercise_id == exercise_id)
            .count()
        )
        if logged_count > 0:
            return False, (
                f"Can't delete {exercise.name!r} — already logged in "
                f"{logged_count} workout(s)."
            )

        db.delete(exercise)
        db.commit()
        return True, None

    @staticmethod
    def list_muscle_groups(db: Session):
        return db.query(MuscleGroup).order_by(MuscleGroup.name.asc()).all()