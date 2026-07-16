from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database.session import SessionLocal
from app.schemas.water import AddWaterRequest, WaterEntryResponse, WaterSettingsResponse, WaterSettingsUpdateRequest, WaterStatsResponse
from app.services.water_service import WaterService


router = APIRouter(
    prefix="/api/v1/water",
    tags=["Water"],
)


@router.get("/today", response_model=WaterEntryResponse)
def get_today(user_id: UUID = Depends(get_current_user)):
    db: Session = SessionLocal()

    try:
        return WaterService.get_today(db, user_id)
    finally:
        db.close()


@router.post("/today/add", response_model=WaterEntryResponse)
def add_water(
    request: AddWaterRequest,
    user_id: UUID = Depends(get_current_user),
):
    db: Session = SessionLocal()

    try:
        return WaterService.add_water(db, user_id, request)
    finally:
        db.close()


@router.get("/history", response_model=List[WaterEntryResponse])
def get_history(user_id: UUID = Depends(get_current_user)):
    db: Session = SessionLocal()

    try:
        return WaterService.get_history(db, user_id)
    finally:
        db.close()  


@router.get("/settings", response_model=WaterSettingsResponse)
def get_settings(user_id: UUID = Depends(get_current_user)):
    db: Session = SessionLocal()

    try:
        return WaterService.get_settings(db, user_id)
    finally:
        db.close()


@router.put("/settings", response_model=WaterSettingsResponse)
def update_settings(
    request: WaterSettingsUpdateRequest,
    user_id: UUID = Depends(get_current_user),
):
    db: Session = SessionLocal()

    try:
        return WaterService.update_settings(db, user_id, request)
    finally:
        db.close()


@router.get("/stats", response_model=WaterStatsResponse)
def get_stats(user_id: UUID = Depends(get_current_user)):
    db: Session = SessionLocal()

    try:
        return WaterService.get_stats(db, user_id)
    finally:
        db.close()