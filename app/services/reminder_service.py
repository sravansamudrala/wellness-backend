from sqlalchemy.orm import Session

from app.models.reminder_settings import ReminderSettings
from app.schemas.reminder_settings import ReminderSettingsUpdateRequest


class ReminderService:

    @staticmethod
    def get_settings(db: Session):

        settings = db.query(ReminderSettings).first()

        if settings is None:
            settings = ReminderSettings()
            db.add(settings)
            db.commit()
            db.refresh(settings)

        return settings

    @staticmethod
    def update_settings(
        db: Session,
        request: ReminderSettingsUpdateRequest
    ):

        settings = db.query(ReminderSettings).first()

        if settings is None:
            settings = ReminderSettings()
            db.add(settings)
            db.commit()
            db.refresh(settings)

        settings.morning_time = request.morning_time
        settings.evening_time = request.evening_time
        settings.notifications_enabled = request.notifications_enabled

        db.commit()
        db.refresh(settings)

        return settings