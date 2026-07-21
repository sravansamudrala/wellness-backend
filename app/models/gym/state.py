import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class GymState(Base):
    """Per-user cursor for the queue-based workout engine (one row per user).

    Holds the active plan and the rotation position. "Next workout" is derived as the
    plan_day after last_completed_day_id (by order_index), wrapping to the first day.
    This is the pointer to *what to do next* — distinct from the in-progress session,
    which is *what is being done now*. Get-or-create like ReminderService.get_settings.
    """

    __tablename__ = "gym_state"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # One cursor row per user (unique). Nullable for the migration/legacy claim.
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        unique=True,
        nullable=True,
    )

    active_plan_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workout_plans.id"),
        nullable=True,
    )

    last_completed_day_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("plan_days.id"),
        nullable=True,
    )

    # Display preference for weights: "kg" or "lb". Storage is always canonical kg.
    unit: Mapped[str] = mapped_column(String, default="kg")

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )