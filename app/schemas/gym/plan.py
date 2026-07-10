from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel

from app.schemas.gym.exercise import ExerciseResponse


# ----- Requests (create / update a custom plan) -----

class PlanExerciseInput(BaseModel):
    exercise_id: UUID
    order_index: int
    target_sets: Optional[int] = None
    target_reps: Optional[str] = None
    target_rest_seconds: Optional[int] = None


class PlanDayInput(BaseModel):
    name: str
    order_index: int
    exercises: List[PlanExerciseInput] = []


class PlanCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    goal: Optional[str] = None
    days: List[PlanDayInput] = []


class PlanUpdateRequest(BaseModel):
    """Full replace of the plan's days/exercises."""
    name: str
    description: Optional[str] = None
    goal: Optional[str] = None
    days: List[PlanDayInput] = []


# ----- Responses -----

class PlanExerciseResponse(BaseModel):
    id: UUID
    order_index: int
    target_sets: Optional[int] = None
    target_reps: Optional[str] = None
    target_rest_seconds: Optional[int] = None
    exercise: ExerciseResponse

    model_config = {
        "from_attributes": True
    }


class PlanDayResponse(BaseModel):
    id: UUID
    name: str
    order_index: int
    exercises: List[PlanExerciseResponse] = []

    model_config = {
        "from_attributes": True
    }


class WorkoutPlanResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    goal: Optional[str] = None
    is_custom: bool

    model_config = {
        "from_attributes": True
    }


class WorkoutPlanDetailResponse(WorkoutPlanResponse):
    days: List[PlanDayResponse] = []
