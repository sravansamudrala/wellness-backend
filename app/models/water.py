import uuid
from datetime import datetime, date, time

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Time, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class WaterEntry(Base):
    __tablename__ = "water_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        index=True,
    )

    date: Mapped[date] = mapped_column(Date)

    amount_ml: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_water_user_date"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class WaterSettings(Base):
    __tablename__ = "water_settings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        unique=True,
    )

    daily_goal_ml: Mapped[int] = mapped_column(Integer, default=2000)

    reminders_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    # Hourly reminders fire on the hour within [reminder_start_time, reminder_end_time].
    reminder_start_time: Mapped[time] = mapped_column(Time, default=time(9, 0))
    reminder_end_time: Mapped[time] = mapped_column(Time, default=time(21, 0))

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )