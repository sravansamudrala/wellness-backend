import uuid
from datetime import datetime, date
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class SkincareEntry(Base):
    __tablename__ = "skincare_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Owner of this entry. Nullable so the migration can add the column to
    # existing rows; the first registered account claims the legacy NULL rows.
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )

    # One entry per (user, day). Was globally unique on `date` pre-multi-user.
    date: Mapped[date] = mapped_column(Date)

    __table_args__ = (
        UniqueConstraint("user_id", "date", name="uq_skincare_user_date"),
    )

    face_wash: Mapped[bool] = mapped_column(Boolean, default=False)
    vitamin_c: Mapped[bool] = mapped_column(Boolean, default=False)
    moisturizer: Mapped[bool] = mapped_column(Boolean, default=False)
    sunscreen: Mapped[bool] = mapped_column(Boolean, default=False)
    lipcare: Mapped[bool] = mapped_column(Boolean, default=False)

    cleanser: Mapped[bool] = mapped_column(Boolean, default=False)
    evening_moisturizer: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )