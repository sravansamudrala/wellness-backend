from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel

from app.schemas.gym.exercise import ExerciseResponse


# ----- Requests -----

class QuickLogRequest(BaseModel):
    """Freestyle 'Log Workout': a list of exercises done, saved as one completed
    session (each exercise marked done, weightless)."""
    name: Optional[str] = None
    exercise_ids: List[UUID] = []


# ----- Responses -----

class SessionSetResponse(BaseModel):
    id: UUID
    set_number: int
    reps: Optional[int] = None
    weight_kg: Optional[float] = None
    is_warmup: bool
    is_completed: bool
    rest_seconds: Optional[int] = None

    model_config = {
        "from_attributes": True
    }


class SessionExerciseResponse(BaseModel):
    id: UUID
    order_index: int
    notes: Optional[str] = None
    exercise: ExerciseResponse
    sets: List[SessionSetResponse] = []

    model_config = {
        "from_attributes": True
    }


class WorkoutSessionResponse(BaseModel):
    id: UUID
    name: str
    status: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    notes: Optional[str] = None

    model_config = {
        "from_attributes": True
    }


class WorkoutSessionDetailResponse(WorkoutSessionResponse):
    exercises: List[SessionExerciseResponse] = []