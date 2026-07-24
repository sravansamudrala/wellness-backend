from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel

from app.schemas.gym.exercise import MuscleGroupResponse


class GymStateResponse(BaseModel):
    id: UUID
    unit: str
    rotation_order: List[str]

    model_config = {
        "from_attributes": True
    }


class GymStateUpdateRequest(BaseModel):
    # Display unit for weights: "kg" or "lb". Storage is always canonical kg.
    unit: str
    rotation_order: List[str]


class NextCategoryResponse(BaseModel):
    muscle_group: Optional[MuscleGroupResponse] = None
