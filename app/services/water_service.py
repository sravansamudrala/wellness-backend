from datetime import date, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.water import WaterEntry, WaterSettings
from app.schemas.water import AddWaterRequest, WaterSettingsUpdateRequest


def _water_message(current_streak: int, best_streak: int, total_days: int) -> str:
    if total_days == 0:
        return "Log your first glass to start tracking hydration."

    if current_streak == 0:
        if best_streak == 0:
            return "A small sip still counts. Start with one entry today."
        return f"Your best hydration streak was {best_streak} days. Start a fresh one today."

    if current_streak == best_streak and current_streak >= 3:
        return f"{current_streak}-day hydration streak. New personal best."

    return f"{current_streak} days of hydration. Keep going."


class WaterService:

    @staticmethod
    def get_today(db: Session, user_id: UUID) -> WaterEntry:
        today = date.today()

        entry = (
            db.query(WaterEntry)
            .filter(
                WaterEntry.user_id == user_id,
                WaterEntry.date == today,
            )
            .first()
        )

        if entry:
            return entry

        entry = WaterEntry(user_id=user_id, date=today)

        db.add(entry)
        db.commit()
        db.refresh(entry)

        return entry

    @staticmethod
    def add_water(
        db: Session,
        user_id: UUID,
        request: AddWaterRequest,
    ) -> WaterEntry:
        entry = WaterService.get_today(db, user_id)

        entry.amount_ml += request.amount_ml

        db.commit()
        db.refresh(entry)

        return entry
    
    @staticmethod
    def get_history(db: Session, user_id: UUID):
        return (
            db.query(WaterEntry)
            .filter(WaterEntry.user_id == user_id)
            .order_by(WaterEntry.date.desc())
            .all()
        )
    
    @staticmethod
    def get_settings(db: Session, user_id: UUID) -> WaterSettings:
        settings = (
            db.query(WaterSettings)
            .filter(WaterSettings.user_id == user_id)
            .first()
        )

        if settings:
            return settings

        settings = WaterSettings(user_id=user_id)

        db.add(settings)
        db.commit()
        db.refresh(settings)

        return settings

    @staticmethod
    def update_settings(
        db: Session,
        user_id: UUID,
        request: WaterSettingsUpdateRequest,
    ) -> WaterSettings:
        settings = WaterService.get_settings(db, user_id)

        settings.daily_goal_ml = request.daily_goal_ml
        settings.reminders_enabled = request.reminders_enabled
        settings.reminder_start_time = request.reminder_start_time
        settings.reminder_end_time = request.reminder_end_time

        db.commit()
        db.refresh(settings)

        return settings
    

    @staticmethod
    def get_stats(db: Session, user_id: UUID):
        entries = (
            db.query(WaterEntry)
            .filter(WaterEntry.user_id == user_id)
            .order_by(WaterEntry.date.asc())
            .all()
        )

        total_days = len(entries)

        if total_days == 0:
            return {
                "current_streak": 0,
                "best_streak": 0,
                "total_days": 0,
                "average_completion": 0,
                "message": _water_message(0, 0, 0),
            }

        settings = WaterService.get_settings(db, user_id)
        daily_goal_ml = settings.daily_goal_ml

        total_progress = 0
        completed_dates = set()

        for entry in entries:
            progress = round((entry.amount_ml / daily_goal_ml) * 100)
            total_progress += min(progress, 100)

            if entry.amount_ml >= daily_goal_ml:
                completed_dates.add(entry.date)

        best_streak = 0
        run = 0
        previous_date = None

        for entry in entries:
            if entry.date in completed_dates:
                if (
                    previous_date is not None
                    and entry.date == previous_date + timedelta(days=1)
                ):
                    run += 1
                else:
                    run = 1

                best_streak = max(best_streak, run)
                previous_date = entry.date
            else:
                run = 0
                previous_date = None

        current_streak = 0
        cursor = date.today()

        if cursor not in completed_dates:
            cursor = cursor - timedelta(days=1)

        while cursor in completed_dates:
            current_streak += 1
            cursor = cursor - timedelta(days=1)

        return {
            "current_streak": current_streak,
            "best_streak": best_streak,
            "total_days": total_days,
            "average_completion": round(total_progress / total_days),
            "message": _water_message(current_streak, best_streak, total_days),
        }