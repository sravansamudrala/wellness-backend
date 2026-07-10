from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from app.schemas.gym.plan import PlanDayResponse, WorkoutPlanResponse


class GymStateResponse(BaseModel):
    id: UUID
    active_plan_id: Optional[UUID] = None
    last_completed_day_id: Optional[UUID] = None
    unit: str

    model_config = {
        "from_attributes": True
    }


class GymStateUpdateRequest(BaseModel):
    # Display unit for weights: "kg" or "lb". Storage is always canonical kg.
    unit: str


class ActiveWorkoutResponse(BaseModel):
    active_plan: Optional[WorkoutPlanResponse] = None
    next_day: Optional[PlanDayResponse] = None
    unit: str