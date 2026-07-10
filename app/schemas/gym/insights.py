from datetime import date
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel


class GymStatsResponse(BaseModel):
    total_workouts: int
    current_streak: int
    best_streak: int
    this_week: int
    last_workout_date: Optional[date] = None
    days_since_last: Optional[int] = None
    message: str


class VolumePoint(BaseModel):
    date: date
    volume_kg: float


class VolumeResponse(BaseModel):
    range: str
    total_volume_kg: float
    points: List[VolumePoint] = []


class RecordResponse(BaseModel):
    exercise_id: UUID
    exercise_name: str
    max_weight_kg: Optional[float] = None
    estimated_1rm_kg: Optional[float] = None
    max_volume_kg: Optional[float] = None


class RecoveryItem(BaseModel):
    muscle_group_id: UUID
    muscle_group_name: str
    last_trained: Optional[date] = None
    days_since: Optional[int] = None