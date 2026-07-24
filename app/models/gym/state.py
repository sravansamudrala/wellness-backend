import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class GymState(Base):
    """Per-user settings for the freestyle Log Workout flow (one row per user).

    Get-or-create like ReminderService.get_settings.
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

    # Display preference for weights: "kg" or "lb". Storage is always canonical kg.
    unit: Mapped[str] = mapped_column(String, default="kg")

    # Ordered list of muscle-group names the "next up" suggestion cycles through
    # (e.g. ["Chest", "Biceps", "Back", "Shoulders", "Legs", "Triceps"]). Falls back
    # to WorkoutService.DEFAULT_ROTATION_ORDER when null.
    rotation_order: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )