from pydantic import BaseModel


class SkincareStatsResponse(BaseModel):
    current_streak: int
    best_streak: int
    total_days: int
    average_completion: int