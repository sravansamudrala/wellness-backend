from uuid import UUID

from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.database.session import SessionLocal
from app.schemas.reminder_settings import (
    ReminderSettingsResponse,
    ReminderSettingsUpdateRequest,
)
from app.services.reminder_service import ReminderService

router = APIRouter(
    prefix="/api/v1/settings/reminders",
    tags=["Reminder Settings"],
)


@router.get("", response_model=ReminderSettingsResponse)
def get_reminder_settings(user_id: UUID = Depends(get_current_user)):

    db: Session = SessionLocal()

    try:
        return ReminderService.get_settings(db, user_id)
    finally:
        db.close()


@router.put("", response_model=ReminderSettingsResponse)
def update_reminder_settings(
    request: ReminderSettingsUpdateRequest,
    user_id: UUID = Depends(get_current_user),
):

    db: Session = SessionLocal()

    try:
        return ReminderService.update_settings(db, user_id, request)
    finally:
        db.close()