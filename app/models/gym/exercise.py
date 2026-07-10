import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class MuscleGroup(Base):
    """Master-data lookup (chest, back, legs, …). Seeded, referenced by exercises."""

    __tablename__ = "muscle_groups"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    name: Mapped[str] = mapped_column(String, unique=True, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )


class Equipment(Base):
    """Master-data lookup (barbell, dumbbell, machine, bodyweight, …)."""

    __tablename__ = "equipment"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    name: Mapped[str] = mapped_column(String, unique=True, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )


class Exercise(Base):
    """The Exercise Catalog — single source of truth for every trackable movement.

    Muscle group and equipment are single nullable FKs for the MVP; the many-to-many
    upgrades (roles, multiple equipment, alternatives) are deferred additive migrations.
    """

    __tablename__ = "exercises"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    name: Mapped[str] = mapped_column(String, unique=True, index=True)

    # e.g. "compound" / "isolation" — free-form string, validated in the schema layer.
    category: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    primary_muscle_group_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("muscle_groups.id"),
        nullable=True,
        index=True,
    )

    equipment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("equipment.id"),
        nullable=True,
        index=True,
    )

    # e.g. "beginner" / "intermediate" / "advanced".
    difficulty: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    video_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)

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