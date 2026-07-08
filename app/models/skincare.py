import uuid
from datetime import datetime, date

from sqlalchemy import Boolean, Date, DateTime
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

    date: Mapped[date] = mapped_column(Date, unique=True)

    face_wash: Mapped[bool] = mapped_column(Boolean, default=False)
    vitamin_c: Mapped[bool] = mapped_column(Boolean, default=False)
    moisturizer: Mapped[bool] = mapped_column(Boolean, default=False)
    sunscreen: Mapped[bool] = mapped_column(Boolean, default=False)

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