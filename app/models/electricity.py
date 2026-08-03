import uuid
from datetime import date as date_, datetime
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Meter(Base):
    """One of a user's (at most 2, enforced in the service layer) physical
    electricity meters."""

    __tablename__ = "meters"

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

    label: Mapped[str] = mapped_column(String)
    meter_number: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # The reading last marked as a bill point (see MeterReading.is_billed_reading).
    # Cumulative-vs-slab is computed relative to this reading, not all-time —
    # real meters never reset, so without an anchor the cumulative total would
    # permanently peg at its highest bracket after the very first bill.
    # Nullable: unset until the meter's first bill is logged.
    #
    # use_alter=True: this FK and meter_readings.meter_id (below) form a
    # circular reference between the two tables. Without use_alter,
    # Base.metadata.create_all/drop_all (used by main.py's startup and the
    # test suite) can't figure out a create/drop order and raises
    # CircularDependencyError — this tells SQLAlchemy to add/drop this one
    # column's constraint via a separate ALTER TABLE step instead.
    last_billed_reading_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "meter_readings.id",
            use_alter=True,
            name="fk_meters_last_billed_reading_id_meter_readings",
        ),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )


class MeterReading(Base):
    """A single logged reading for one meter. `units_consumed` is the delta
    from that meter's previous reading (by reading_date) — null on a meter's
    first-ever reading, which is its baseline."""

    __tablename__ = "meter_readings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    meter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meters.id"),
        index=True,
    )

    reading_value: Mapped[float] = mapped_column(Numeric)
    reading_date: Mapped[date_] = mapped_column(Date)

    units_consumed: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)

    # "manual" | "photo" — validated in the schema layer, not a DB enum (no
    # Enum-column precedent elsewhere in this codebase). "photo" is Phase 2;
    # the column exists now so Phase 2 needs no migration.
    entry_method: Mapped[str] = mapped_column(String)

    # Marks this reading as the point the utility actually billed at — see
    # Meter.last_billed_reading_id.
    is_billed_reading: Mapped[bool] = mapped_column(Boolean, default=False)

    # Supabase storage path — Phase 2 (OCR entry). Unused while entry_method
    # is always "manual".
    photo_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )


class MeterSwitchEvent(Base):
    """A single 'Switch Meter' action: the outgoing meter's closing reading
    and the incoming meter's opening reading, taken at the same moment, plus
    which meter became active. The current active meter for a user = the
    incoming_meter_id of their most recent switch event, or their first
    created meter if they've never switched."""

    __tablename__ = "meter_switch_events"

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

    outgoing_meter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meters.id"),
    )
    incoming_meter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meters.id"),
    )

    # Linked so switch history can show each side's reading without
    # re-deriving it from timestamps.
    outgoing_reading_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meter_readings.id"),
    )
    incoming_reading_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meter_readings.id"),
    )

    # Shared by both readings — a switch happens at one point in time.
    reading_date: Mapped[date_] = mapped_column(Date)

    switched_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )


class SlabThreshold(Base):
    """One bracket of a meter's slab-based rate schedule. No rate_per_unit —
    cost calculation is out of scope for v1."""

    __tablename__ = "slab_thresholds"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    meter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meters.id"),
        index=True,
    )

    slab_min: Mapped[float] = mapped_column(Numeric)
    # Null = open-ended top slab.
    slab_max: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)



class MeterShare(Base):
    """Grants a user other than the owner access to a meter — they can view
    and log readings on it, same as the owner. See Meter.user_id for the
    owner; this table is the extra viewers/loggers on top of that."""
    __tablename__ = "meter_shares"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    meter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("meters.id"),
        index=True,
    )

    shared_with_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )
