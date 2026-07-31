from typing import Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.timezone import local_day_bounds_utc, local_today
from app.models.food import FoodEntry
from app.schemas.food import FoodEntryCreate


class FoodService:

    @staticmethod
    def create_entry(db: Session, user_id: UUID, data: FoodEntryCreate) -> FoodEntry:
        entry = FoodEntry(
            user_id=user_id,
            name=data.name,
            quantity=data.quantity,
            calories=data.calories,
            protein_g=data.protein_g,
            carbs_g=data.carbs_g,
            fat_g=data.fat_g,
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return entry

    @staticmethod
    def get_today(db: Session, user_id: UUID) -> dict:
        start_utc, end_utc = local_day_bounds_utc(local_today())

        entries = (
            db.query(FoodEntry)
            .filter(
                FoodEntry.user_id == user_id,
                FoodEntry.logged_at >= start_utc,
                FoodEntry.logged_at < end_utc,
            )
            .order_by(FoodEntry.logged_at.asc())
            .all()
        )

        return {
            "entries": entries,
            "total_calories": sum(e.calories for e in entries),
            "total_protein_g": sum(e.protein_g or 0 for e in entries),
            "total_carbs_g": sum(e.carbs_g or 0 for e in entries),
            "total_fat_g": sum(e.fat_g or 0 for e in entries),
        }

    @staticmethod
    def delete_entry(db: Session, user_id: UUID, entry_id: UUID) -> Tuple[bool, Optional[str]]:
        entry = (
            db.query(FoodEntry)
            .filter(FoodEntry.id == entry_id, FoodEntry.user_id == user_id)
            .first()
        )

        if entry is None:
            return False, "not_found"

        db.delete(entry)
        db.commit()

        return True, None