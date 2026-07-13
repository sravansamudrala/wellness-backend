import uuid
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class User(Base):
    """An account. Every user-owned row (skincare entries, gym sessions, …)
    carries a user_id foreign key pointing back to one of these."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # unique=True means the DB itself rejects a second row with the same email
    # (a hard guarantee, not just an app-level check). index=True speeds up the
    # email lookup we do on every login.
    email: Mapped[str] = mapped_column(String, unique=True, index=True)

    # We store the bcrypt hash from security.hash_password — never the password.
    hashed_password: Mapped[str] = mapped_column(String)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )
