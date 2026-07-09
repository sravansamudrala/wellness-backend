from datetime import datetime, time
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, Time
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class ReminderSettings(Base):
    __tablename__ = "reminder_settings"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4
    )

    morning_time: Mapped[time] = mapped_column(
        Time,
        default=time(8, 0)
    )

    evening_time: Mapped[time] = mapped_column(
        Time,
        default=time(21, 30)
    )

    notifications_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )