from datetime import date

from pydantic import BaseModel


class SkincareHistoryItem(BaseModel):
    date: date

    completed: int
    total: int
    progress: int

    model_config = {
        "from_attributes": True
    }