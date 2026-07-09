from datetime import datetime, time
from uuid import UUID

from pydantic import BaseModel


class ReminderSettingsResponse(BaseModel):
    id: UUID

    morning_time: time
    evening_time: time

    notifications_enabled: bool

    created_at: datetime
    updated_at: datetime

    model_config = {
        "from_attributes": True
    }


class ReminderSettingsUpdateRequest(BaseModel):
    morning_time: time
    evening_time: time

    notifications_enabled: bool