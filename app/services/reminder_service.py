from uuid import UUID

from sqlalchemy.orm import Session

from app.models.reminder_settings import ReminderSettings
from app.schemas.reminder_settings import ReminderSettingsUpdateRequest


class ReminderService:

    @staticmethod
    def get_settings(db: Session, user_id: UUID):
        # Get-or-create this user's single settings row.
        settings = (
            db.query(ReminderSettings)
            .filter(ReminderSettings.user_id == user_id)
            .first()
        )

        if settings is None:
            settings = ReminderSettings(user_id=user_id)
            db.add(settings)
            db.commit()
            db.refresh(settings)

        return settings

    @staticmethod
    def update_settings(
        db: Session,
        user_id: UUID,
        request: ReminderSettingsUpdateRequest
    ):

        settings = ReminderService.get_settings(db, user_id)

        settings.morning_time = request.morning_time
        settings.evening_time = request.evening_time
        settings.notifications_enabled = request.notifications_enabled

        db.commit()
        db.refresh(settings)

        return settings