from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class WaterEntryResponse(BaseModel):
    id: UUID
    date: date
    amount_ml: int
    created_at: datetime
    updated_at: datetime

    model_config = {
        "from_attributes": True
    }


class AddWaterRequest(BaseModel):
    amount_ml: int = Field(gt=0, description="Amount of water in milliliters. Must be greater than 0.")


class WaterSettingsResponse(BaseModel):
    id: UUID
    daily_goal_ml: int
    created_at: datetime
    updated_at: datetime

    model_config = {
        "from_attributes": True
    }


class WaterSettingsUpdateRequest(BaseModel):
    daily_goal_ml: int = Field(gt=0, description="Daily water intake goal in milliliters. Must be greater than 0.")



class WaterStatsResponse(BaseModel):
    current_streak: int
    best_streak: int
    total_days: int
    average_completion: int
    message: str
