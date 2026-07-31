from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class FoodEntryCreate(BaseModel):
    name: str
    quantity: str
    calories: int
    protein_g: Optional[float] = None
    carbs_g: Optional[float] = None
    fat_g: Optional[float] = None


class FoodEntryResponse(BaseModel):
    id: UUID
    name: str
    quantity: str
    calories: int
    protein_g: Optional[float]
    carbs_g: Optional[float]
    fat_g: Optional[float]
    logged_at: datetime

    model_config = {
        "from_attributes": True
    }


class FoodTodayResponse(BaseModel):
    entries: list[FoodEntryResponse]
    total_calories: int
    total_protein_g: float
    total_carbs_g: float
    total_fat_g: float


class FoodPhotoItem(BaseModel):
    name: str
    quantity: str
    calories: int
    protein_g: Optional[float] = None
    carbs_g: Optional[float] = None
    fat_g: Optional[float] = None


class FoodPhotoAnalysisResponse(BaseModel):
    items: list[FoodPhotoItem]