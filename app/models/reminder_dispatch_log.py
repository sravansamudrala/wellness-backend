import uuid
from datetime import datetime, date
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class ReminderDispatchLog(Base):
    """One row per reminder actually sent, keyed by (user, day, slot).

    Used to guarantee a reminder fires at most once per day per slot per user
    even though the dispatch endpoint is polled repeatedly by the cron caller.
    """

    __tablename__ = "reminder_dispatch_log"
    __table_args__ = (
        UniqueConstraint("user_id", "sent_on", "slot", name="uq_dispatch_user_day_slot"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )

    sent_on: Mapped[date] = mapped_column(Date)
    slot: Mapped[str] = mapped_column(String)  # "morning" | "evening"

    sent_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )