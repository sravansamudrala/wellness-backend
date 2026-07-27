from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.skincare_habit import SkincareEntryHabitResponse, SkincareHabitCompletionItem


class SkincareResponse(BaseModel):
    id: UUID
    date: date

    habits: list[SkincareEntryHabitResponse]

    created_at: datetime
    updated_at: datetime

    model_config = {
        "from_attributes": True
    }

class SkincareStatsResponse(BaseModel):
    current_streak: int
    best_streak: int
    total_days: int
    average_completion: int
    message: str

class SkincareUpdateRequest(BaseModel):
    habits: list[SkincareHabitCompletionItem]