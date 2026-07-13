import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class WorkoutPlan(Base):
    """A workout plan (PPL, Bro Split, Upper/Lower, …). Templates are seeded;
    user-made plans set is_custom=True. Plans are data, never hardcoded."""

    __tablename__ = "workout_plans"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # NULL = a shared seeded template (visible to everyone); a value = a user's
    # own custom plan (visible only to them).
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # e.g. "fat_loss" / "muscle_gain" / "strength" — free-form, validated in schema.
    goal: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class PlanDay(Base):
    """One training day within a plan (Push, Pull, Legs, …). order_index is the
    sequential rotation position — execution is queue-based, not calendar-based,
    so rest days are not modeled here."""

    __tablename__ = "plan_days"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workout_plans.id"),
        index=True,
    )

    name: Mapped[str] = mapped_column(String)
    order_index: Mapped[int] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )


class PlanExercise(Base):
    """A prescribed exercise within a plan day (the template / target)."""

    __tablename__ = "plan_exercises"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    plan_day_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("plan_days.id"),
        index=True,
    )

    exercise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exercises.id"),
        index=True,
    )

    order_index: Mapped[int] = mapped_column(Integer)

    target_sets: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # A range like "8-12" is common, so keep this a string.
    target_reps: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    target_rest_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )