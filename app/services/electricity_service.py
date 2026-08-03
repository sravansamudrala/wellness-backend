"""Writes for the electricity module: meter/reading CRUD and the compound
'Switch Meter' action. Read-only cross-entity logic (active-meter
resolution, cumulative-vs-slab) lives in electricity_insights_service.py.

Validation failures raise ValueError("<code>") rather than HTTPException —
same convention as auth_service.py — and the router translates the code
into the right HTTP response.
"""

from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.electricity import Meter, MeterReading, MeterShare, MeterSwitchEvent, SlabThreshold
from app.models.user import User
from app.schemas.electricity import (
    MeterCreateRequest,
    ReadingCreateRequest,
    SwitchEventCreateRequest,
)
from app.services.electricity_insights_service import (
    accessible_meter_ids,
    resolve_active_meter_id,
    shared_emails_by_meter,
)

MAX_METERS_PER_USER = 2


def _meter_response(
    meter: Meter,
    slab_thresholds: List[SlabThreshold],
    viewer_user_id: UUID,
    shared_emails: List[str],
) -> dict:
    is_owner = meter.user_id == viewer_user_id
    return {
        "id": meter.id,
        "label": meter.label,
        "meter_number": meter.meter_number,
        "last_billed_reading_id": meter.last_billed_reading_id,
        "created_at": meter.created_at,
        "slab_thresholds": slab_thresholds,
        "is_owner": is_owner,
        # Only the owner should see who else has access — a shared viewer
        # has no business relationship with the meter's *other* viewers.
        "shared_with": shared_emails if is_owner else [],
    }


def _switch_event_response(event: MeterSwitchEvent, readings_by_id: dict) -> dict:
    return {
        "id": event.id,
        "outgoing_meter_id": event.outgoing_meter_id,
        "incoming_meter_id": event.incoming_meter_id,
        "reading_date": event.reading_date,
        "switched_at": event.switched_at,
        "outgoing_reading": readings_by_id[event.outgoing_reading_id],
        "incoming_reading": readings_by_id[event.incoming_reading_id],
    }


class ElectricityService:
    # ----- Meters -----

    @staticmethod
    def create_meter(db: Session, user_id: UUID, request: MeterCreateRequest) -> dict:
        # Lock the user's existing meter rows for the rest of this
        # transaction, so two concurrent "add meter" requests can't both
        # pass this count check before either commits (a plain count()
        # query without the lock would allow exactly that race).
        existing = (
            db.query(Meter)
            .filter(Meter.user_id == user_id)
            .with_for_update()
            .all()
        )
        if len(existing) >= MAX_METERS_PER_USER:
            raise ValueError("max_meters_reached")

        meter = Meter(
            user_id=user_id,
            label=request.label,
            meter_number=request.meter_number,
        )
        db.add(meter)
        db.flush()

        slabs = []
        for slab_req in request.slab_thresholds:
            slab = SlabThreshold(
                meter_id=meter.id,
                slab_min=slab_req.slab_min,
                slab_max=slab_req.slab_max,
            )
            db.add(slab)
            slabs.append(slab)

        db.commit()
        db.refresh(meter)
        for slab in slabs:
            db.refresh(slab)
        return _meter_response(meter, slabs, user_id, [])

    @staticmethod
    def list_meters(db: Session, user_id: UUID) -> List[dict]:
        meter_ids = accessible_meter_ids(db, user_id)
        if not meter_ids:
            return []

        meters = (
            db.query(Meter)
            .filter(Meter.id.in_(meter_ids))
            .order_by(Meter.created_at.asc())
            .all()
        )

        slabs = (
            db.query(SlabThreshold)
            .filter(SlabThreshold.meter_id.in_(meter_ids))
            .all()
        )
        slabs_by_meter: dict = {}
        for slab in slabs:
            slabs_by_meter.setdefault(slab.meter_id, []).append(slab)

        shared_by_meter = shared_emails_by_meter(db, meter_ids)

        return [
            _meter_response(
                m, slabs_by_meter.get(m.id, []), user_id, shared_by_meter.get(m.id, [])
            )
            for m in meters
        ]

    @staticmethod
    def _get_accessible_meter(db: Session, user_id: UUID, meter_id: UUID) -> Meter:
        if meter_id not in accessible_meter_ids(db, user_id):
            raise ValueError("meter_not_found")
        meter = db.query(Meter).filter(Meter.id == meter_id).first()
        if meter is None:
            raise ValueError("meter_not_found")
        return meter

    @staticmethod
    def share_meter(db: Session, owner_user_id: UUID, meter_id: UUID, email: str) -> dict:
        # Filtered on user_id up front, same as every other meter lookup —
        # a non-owner gets the same meter_not_found whether the id belongs to
        # someone else's meter or doesn't exist at all. Two different error
        # codes here would let a non-owner probe arbitrary meter ids for
        # existence, which _get_accessible_meter is careful to avoid too.
        meter = db.query(Meter).filter(Meter.id == meter_id, Meter.user_id == owner_user_id).first()
        if meter is None:
            raise ValueError("meter_not_found")

        target_user = db.query(User).filter(User.email == email).first()
        if target_user is None:
            raise ValueError("user_not_found")
        if target_user.id == owner_user_id:
            raise ValueError("cannot_share_with_self")

        existing_share = (
            db.query(MeterShare)
            .filter(MeterShare.meter_id == meter_id, MeterShare.shared_with_user_id == target_user.id)
            .first()
        )
        if existing_share is None:
            db.add(MeterShare(meter_id=meter_id, shared_with_user_id=target_user.id))
            db.commit()

        slabs = db.query(SlabThreshold).filter(SlabThreshold.meter_id == meter_id).all()
        shared_emails = shared_emails_by_meter(db, [meter_id]).get(meter_id, [])
        return _meter_response(meter, slabs, owner_user_id, shared_emails)

    # ----- Readings -----

    @staticmethod
    def _latest_reading(db: Session, meter_id: UUID) -> Optional[MeterReading]:
        return (
            db.query(MeterReading)
            .filter(MeterReading.meter_id == meter_id)
            .order_by(MeterReading.reading_date.desc(), MeterReading.created_at.desc())
            .first()
        )

    @staticmethod
    def _build_reading(
        meter_id: UUID,
        reading_value: float,
        reading_date,
        previous: Optional[MeterReading],
        is_billed_reading: bool,
    ) -> MeterReading:
        """Validates against the meter's previous reading (readings only
        increase, and can't be dated before it — backdating is only
        supported up to the meter's latest existing reading, not further
        back than that) and computes the delta."""
        if previous is not None:
            if reading_date < previous.reading_date:
                raise ValueError("reading_date_before_previous")
            if reading_value < float(previous.reading_value):
                raise ValueError("reading_value_decreased")
            units_consumed = reading_value - float(previous.reading_value)
        else:
            units_consumed = None

        return MeterReading(
            meter_id=meter_id,
            reading_value=reading_value,
            reading_date=reading_date,
            units_consumed=units_consumed,
            entry_method="manual",
            is_billed_reading=is_billed_reading,
        )

    @staticmethod
    def create_reading(
        db: Session, user_id: UUID, meter_id: UUID, request: ReadingCreateRequest
    ) -> MeterReading:
        meter = ElectricityService._get_accessible_meter(db, user_id, meter_id)
        previous = ElectricityService._latest_reading(db, meter_id)

        reading = ElectricityService._build_reading(
            meter_id,
            request.reading_value,
            request.reading_date,
            previous,
            request.is_billed_reading,
        )
        db.add(reading)
        db.flush()

        if request.is_billed_reading:
            meter.last_billed_reading_id = reading.id

        db.commit()
        db.refresh(reading)
        return reading

    @staticmethod
    def list_readings(db: Session, user_id: UUID, meter_id: UUID) -> List[MeterReading]:
        ElectricityService._get_accessible_meter(db, user_id, meter_id)
        return (
            db.query(MeterReading)
            .filter(MeterReading.meter_id == meter_id)
            .order_by(MeterReading.reading_date.desc())
            .all()
        )

    # ----- Switch events -----

    @staticmethod
    def create_switch_event(
        db: Session, user_id: UUID, request: SwitchEventCreateRequest
    ) -> dict:
        outgoing_meter_id = resolve_active_meter_id(db, user_id)
        if outgoing_meter_id is None:
            raise ValueError("no_active_meter")
        if outgoing_meter_id == request.incoming_meter_id:
            raise ValueError("already_active_meter")

        outgoing_meter = ElectricityService._get_accessible_meter(db, user_id, outgoing_meter_id)
        incoming_meter = ElectricityService._get_accessible_meter(
            db, user_id, request.incoming_meter_id
        )

        outgoing_reading = ElectricityService._build_reading(
            outgoing_meter.id,
            request.outgoing_reading_value,
            request.reading_date,
            ElectricityService._latest_reading(db, outgoing_meter.id),
            request.is_billed_reading,
        )
        incoming_reading = ElectricityService._build_reading(
            incoming_meter.id,
            request.incoming_reading_value,
            request.reading_date,
            ElectricityService._latest_reading(db, incoming_meter.id),
            # is_billed_reading only ever applies to the outgoing side — see
            # SwitchEventCreateRequest's docstring.
            False,
        )
        db.add(outgoing_reading)
        db.add(incoming_reading)
        db.flush()

        if request.is_billed_reading:
            outgoing_meter.last_billed_reading_id = outgoing_reading.id

        switch_event = MeterSwitchEvent(
            user_id=user_id,
            outgoing_meter_id=outgoing_meter.id,
            incoming_meter_id=incoming_meter.id,
            outgoing_reading_id=outgoing_reading.id,
            incoming_reading_id=incoming_reading.id,
            reading_date=request.reading_date,
        )
        db.add(switch_event)
        db.commit()
        db.refresh(switch_event)
        db.refresh(outgoing_reading)
        db.refresh(incoming_reading)

        return _switch_event_response(
            switch_event,
            {outgoing_reading.id: outgoing_reading, incoming_reading.id: incoming_reading},
        )

    @staticmethod
    def list_switch_events(db: Session, user_id: UUID) -> List[dict]:
        # Based on the accessible meter set, not switch_events.user_id — a
        # shared user should see switches the owner made too, same reasoning
        # as resolve_active_meter_id.
        meter_ids = accessible_meter_ids(db, user_id)
        events = (
            db.query(MeterSwitchEvent)
            .filter(
                MeterSwitchEvent.outgoing_meter_id.in_(meter_ids)
                | MeterSwitchEvent.incoming_meter_id.in_(meter_ids)
            )
            .order_by(MeterSwitchEvent.switched_at.desc())
            .all()
        )
        if not events:
            return []

        reading_ids = set()
        for event in events:
            reading_ids.add(event.outgoing_reading_id)
            reading_ids.add(event.incoming_reading_id)
        readings_by_id = {
            r.id: r
            for r in db.query(MeterReading).filter(MeterReading.id.in_(reading_ids)).all()
        }

        return [_switch_event_response(event, readings_by_id) for event in events]