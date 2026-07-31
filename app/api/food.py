from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.database.session import SessionLocal
from app.schemas.food import (
    FoodEntryCreate,
    FoodEntryResponse,
    FoodPhotoAnalysisResponse,
    FoodTodayResponse,
)
from app.services import food_vision_service
from app.services.food_service import FoodService

router = APIRouter(
    prefix="/api/v1/food",
    tags=["Food"]
)

MAX_PHOTO_BYTES = 10 * 1024 * 1024


@router.post("", response_model=FoodEntryResponse)
def create_entry(
    request: FoodEntryCreate,
    user_id: UUID = Depends(get_current_user),
):
    db: Session = SessionLocal()

    try:
        return FoodService.create_entry(db, user_id, request)
    finally:
        db.close()


@router.get("/today", response_model=FoodTodayResponse)
def get_today(user_id: UUID = Depends(get_current_user)):
    db: Session = SessionLocal()

    try:
        return FoodService.get_today(db, user_id)
    finally:
        db.close()


@router.delete("/{entry_id}")
def delete_entry(
    entry_id: UUID,
    user_id: UUID = Depends(get_current_user),
):
    db: Session = SessionLocal()

    try:
        ok, error = FoodService.delete_entry(db, user_id, entry_id)
        if error == "not_found":
            raise HTTPException(status_code=404, detail="Food entry not found")
        return {"ok": ok}
    finally:
        db.close()


@router.post("/analyze-photo", response_model=FoodPhotoAnalysisResponse)
def analyze_photo(
    file: UploadFile = File(...),
    _user_id: UUID = Depends(get_current_user),
):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    contents = file.file.read()
    if len(contents) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=400, detail="Image is too large (max 10MB)")

    items, error = food_vision_service.analyze_photo(contents)
    if error is not None:
        raise HTTPException(status_code=502, detail=error)

    return {"items": items}