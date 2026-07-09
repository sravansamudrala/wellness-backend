from sqlalchemy.orm import Session
from fastapi import APIRouter

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
def get_reminder_settings():

    db: Session = SessionLocal()

    try:
        return ReminderService.get_settings(db)
    finally:
        db.close()


@router.put("", response_model=ReminderSettingsResponse)
def update_reminder_settings(
    request: ReminderSettingsUpdateRequest,
):

    db: Session = SessionLocal()

    try:
        return ReminderService.update_settings(db, request)
    finally:
        db.close()