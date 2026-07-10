from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class MuscleGroupResponse(BaseModel):
    id: UUID
    name: str

    model_config = {
        "from_attributes": True
    }


class EquipmentResponse(BaseModel):
    id: UUID
    name: str

    model_config = {
        "from_attributes": True
    }


class ExerciseResponse(BaseModel):
    id: UUID
    name: str
    category: Optional[str] = None
    primary_muscle_group_id: Optional[UUID] = None
    equipment_id: Optional[UUID] = None
    difficulty: Optional[str] = None
    instructions: Optional[str] = None
    image_url: Optional[str] = None
    video_url: Optional[str] = None
    is_custom: bool

    model_config = {
        "from_attributes": True
    }