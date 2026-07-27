from datetime import date

from pydantic import BaseModel

from app.schemas.skincare_habit import SkincareEntryHabitResponse


class SkincareHistoryItem(BaseModel):
    date: date

    completed: int
    total: int
    progress: int

    habits: list[SkincareEntryHabitResponse]

    model_config = {
        "from_attributes": True
    }