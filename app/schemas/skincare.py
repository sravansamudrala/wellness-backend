from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel


class SkincareResponse(BaseModel):
    id: UUID
    date: date

    face_wash: bool
    vitamin_c: bool
    moisturizer: bool
    sunscreen: bool

    cleanser: bool
    evening_moisturizer: bool

    created_at: datetime
    updated_at: datetime

    model_config = {
        "from_attributes": True
    }

class SkincareUpdateRequest(BaseModel):
    face_wash: bool
    vitamin_c: bool
    moisturizer: bool
    sunscreen: bool
    cleanser: bool
    evening_moisturizer: bool