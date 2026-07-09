from datetime import date

from pydantic import BaseModel


class SkincareHistoryItem(BaseModel):
    date: date

    completed: int
    total: int
    progress: int

    face_wash: bool
    vitamin_c: bool
    moisturizer: bool
    sunscreen: bool
    lipcare: bool

    cleanser: bool
    evening_moisturizer: bool

    model_config = {
        "from_attributes": True
    }