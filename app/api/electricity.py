from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_feature
from app.database.session import SessionLocal
from app.schemas.electricity import (
    InsightsResponse,
    MeterCreateRequest,
    MeterResponse,
    ReadingCreateRequest,
    ReadingResponse,
    SwitchEventCreateRequest,
    SwitchEventResponse,
)
from app.services.electricity_insights_service import get_insights
from app.services.electricity_service import ElectricityService

router = APIRouter(
    prefix="/api/v1/electricity",
    tags=["Electricity"],
    dependencies=[Depends(require_feature("electricity_tracker"))],
)

# Maps a ValueError code raised by the service layer to (status_code, detail).
_ERROR_RESPONSES = {
    "max_meters_reached": (status.HTTP_400_BAD_REQUEST, "Maximum of 2 meters per user"),
    "meter_not_found": (status.HTTP_404_NOT_FOUND, "Meter not found"),
    "reading_date_before_previous": (
        status.HTTP_400_BAD_REQUEST,
        "Reading date can't be before this meter's most recent reading",
    ),
    "reading_value_decreased": (
        status.HTTP_400_BAD_REQUEST,
        "Reading value can't be less than the previous reading",
    ),
    "no_active_meter": (status.HTTP_400_BAD_REQUEST, "No active meter to switch from"),
    "already_active_meter": (status.HTTP_400_BAD_REQUEST, "That meter is already active"),
}


def _raise_for(error: ValueError):
    status_code, detail = _ERROR_RESPONSES.get(
        str(error), (status.HTTP_400_BAD_REQUEST, str(error))
    )
    raise HTTPException(status_code=status_code, detail=detail)


# ----- Meters -----

@router.post("/meters", response_model=MeterResponse)
def create_meter(request: MeterCreateRequest, user_id: UUID = Depends(get_current_user)):
    db: Session = SessionLocal()
    try:
        try:
            return ElectricityService.create_meter(db, user_id, request)
        except ValueError as e:
            _raise_for(e)
    finally:
        db.close()


@router.get("/meters", response_model=List[MeterResponse])
def list_meters(user_id: UUID = Depends(get_current_user)):
    db: Session = SessionLocal()
    try:
        return ElectricityService.list_meters(db, user_id)
    finally:
        db.close()


# ----- Readings -----

@router.post("/meters/{meter_id}/readings", response_model=ReadingResponse)
def create_reading(
    meter_id: UUID,
    request: ReadingCreateRequest,
    user_id: UUID = Depends(get_current_user),
):
    db: Session = SessionLocal()
    try:
        try:
            return ElectricityService.create_reading(db, user_id, meter_id, request)
        except ValueError as e:
            _raise_for(e)
    finally:
        db.close()


@router.get("/meters/{meter_id}/readings", response_model=List[ReadingResponse])
def list_readings(meter_id: UUID, user_id: UUID = Depends(get_current_user)):
    db: Session = SessionLocal()
    try:
        try:
            return ElectricityService.list_readings(db, user_id, meter_id)
        except ValueError as e:
            _raise_for(e)
    finally:
        db.close()


# ----- Switch events -----

@router.post("/switch-events", response_model=SwitchEventResponse)
def create_switch_event(
    request: SwitchEventCreateRequest, user_id: UUID = Depends(get_current_user)
):
    db: Session = SessionLocal()
    try:
        try:
            return ElectricityService.create_switch_event(db, user_id, request)
        except ValueError as e:
            _raise_for(e)
    finally:
        db.close()


@router.get("/switch-events", response_model=List[SwitchEventResponse])
def list_switch_events(user_id: UUID = Depends(get_current_user)):
    db: Session = SessionLocal()
    try:
        return ElectricityService.list_switch_events(db, user_id)
    finally:
        db.close()


# ----- Insights -----

@router.get("/insights", response_model=InsightsResponse)
def get_electricity_insights(user_id: UUID = Depends(get_current_user)):
    db: Session = SessionLocal()
    try:
        return get_insights(db, user_id)
    finally:
        db.close()