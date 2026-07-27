from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class SkincareHabitResponse(BaseModel):
    id: UUID
    name: str
    is_active: bool
    sort_order: int
    created_at: datetime

    model_config = {
        "from_attributes": True
    }


class SkincareEntryHabitResponse(BaseModel):
    habit_id: UUID
    name: str
    completed: bool

    model_config = {
        "from_attributes": True
    }


class SkincareHabitUpsertItem(BaseModel):
    id: Optional[UUID] = None
    name: str
    is_active: bool
    sort_order: int


class SkincareHabitsUpsertRequest(BaseModel):
    habits: list[SkincareHabitUpsertItem]


class SkincareHabitCompletionItem(BaseModel):
    habit_id: UUID
    completed: bool