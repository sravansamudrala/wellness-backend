import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class FeatureFlag(Base):
    """Per-user, per-feature enable switch. Generic — any future beta module
    can gate itself behind a new `feature_key` without a schema change."""

    __tablename__ = "feature_flags"
    __table_args__ = (
        UniqueConstraint("user_id", "feature_key", name="uq_feature_flags_user_key"),
    )

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

    # e.g. "electricity_tracker" — matched against Depends(require_feature(...)).
    feature_key: Mapped[str] = mapped_column(String, index=True)

    enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )