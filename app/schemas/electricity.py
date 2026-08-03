from datetime import date, datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel


# ----- Requests -----

class SlabThresholdCreateRequest(BaseModel):
    slab_min: float
    slab_max: Optional[float] = None


class MeterCreateRequest(BaseModel):
    label: str
    meter_number: Optional[str] = None
    # Slab boundaries are set once, here, at meter creation — they don't
    # change, so there's no separate slab-threshold endpoint.
    slab_thresholds: List[SlabThresholdCreateRequest] = []


class ReadingCreateRequest(BaseModel):
    """Phase 1 is manual-entry only — no photo/OCR fields here yet (see
    MeterReading.photo_url, added for Phase 2 without a future migration)."""
    reading_value: float
    reading_date: date
    is_billed_reading: bool = False


class SwitchEventCreateRequest(BaseModel):
    """Both readings of a switch share one date and entry method — a switch
    happens at a single point in time. is_billed_reading, if set, always
    applies to the OUTGOING reading: that's the meter ending its active
    stretch, so it's the one the utility would have just read."""
    incoming_meter_id: UUID
    reading_date: date
    outgoing_reading_value: float
    incoming_reading_value: float
    is_billed_reading: bool = False


# ----- Responses -----

class SlabThresholdResponse(BaseModel):
    id: UUID
    meter_id: UUID
    slab_min: float
    slab_max: Optional[float] = None

    model_config = {"from_attributes": True}


class MeterResponse(BaseModel):
    id: UUID
    label: str
    meter_number: Optional[str] = None
    last_billed_reading_id: Optional[UUID] = None
    created_at: datetime
    slab_thresholds: List[SlabThresholdResponse] = []

    model_config = {"from_attributes": True}


class ReadingResponse(BaseModel):
    id: UUID
    meter_id: UUID
    reading_value: float
    reading_date: date
    units_consumed: Optional[float] = None
    entry_method: str
    is_billed_reading: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class SwitchEventResponse(BaseModel):
    id: UUID
    outgoing_meter_id: UUID
    incoming_meter_id: UUID
    reading_date: date
    switched_at: datetime
    outgoing_reading: ReadingResponse
    incoming_reading: ReadingResponse

    model_config = {"from_attributes": True}


class SlabBracketResponse(BaseModel):
    slab_min: float
    slab_max: Optional[float] = None

    model_config = {"from_attributes": True}


class InsightsMeterResponse(BaseModel):
    meter_id: UUID
    label: str
    meter_number: Optional[str] = None
    status: str  # "active" | "standby"
    cumulative_units: float
    last_reading: Optional[ReadingResponse] = None
    last_billed_reading: Optional[ReadingResponse] = None
    days_since_bill: Optional[int] = None
    current_bracket: Optional[SlabBracketResponse] = None
    next_slab_min: Optional[float] = None
    nudge_text: Optional[str] = None


class InsightsResponse(BaseModel):
    meters: List[InsightsMeterResponse]
