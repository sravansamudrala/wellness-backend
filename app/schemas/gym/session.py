from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel

from app.schemas.gym.exercise import ExerciseResponse


# ----- Requests -----

class StartSessionRequest(BaseModel):
    # If omitted, the next queued plan day is started. Provide plan_day_id to start a
    # specific day, or a name (with no plan_day_id) for a freestyle session.
    plan_day_id: Optional[UUID] = None
    name: Optional[str] = None


class SetInput(BaseModel):
    set_number: int
    reps: Optional[int] = None
    weight_kg: Optional[float] = None
    is_warmup: bool = False
    is_completed: bool = False
    rest_seconds: Optional[int] = None


class SessionExerciseSetsInput(BaseModel):
    session_exercise_id: UUID
    sets: List[SetInput] = []


class LogSetsRequest(BaseModel):
    """Replace the logged sets for one or more session exercises."""
    exercises: List[SessionExerciseSetsInput] = []


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
    plan_day_id: Optional[UUID] = None
    plan_id: Optional[UUID] = None
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