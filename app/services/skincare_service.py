from datetime import date, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.skincare import SkincareEntry
from app.schemas.skincare import SkincareUpdateRequest


def _streak_message(current_streak: int, best_streak: int, total_days: int) -> str:
    """Pick an encouraging message for the user's current streak.

    Special cases are checked before the generic per-streak tiers.
    """
    if total_days == 0:
        return "Add your first habit to start a streak! 🌱"

    if current_streak == 0:
        if best_streak == 0:
            return "Every routine counts — check one off to begin! 💧"
        return f"Your best run was {best_streak} days. Start a new one today! 🔄"

    if current_streak == best_streak and current_streak >= 3:
        return f"🔥 {current_streak}-day streak — a new personal best!"

    if current_streak <= 2:
        return "Nice start — keep it going tomorrow! 👍"
    if current_streak <= 6:
        return f"{current_streak} days strong — momentum's building! 💪"
    if current_streak <= 13:
        return f"A full week+! {current_streak} days of consistency. 🌟"
    if current_streak <= 29:
        return f"{current_streak} days — this is becoming a habit! 🏆"
    return f"{current_streak} days! Incredible dedication. 👑"


class SkincareService:

    @staticmethod
    def get_today(db: Session, user_id: UUID) -> SkincareEntry:
        today = date.today()

        skincare = (
            db.query(SkincareEntry)
            .filter(
                SkincareEntry.user_id == user_id,
                SkincareEntry.date == today,
            )
            .first()
        )

        if skincare:
            return skincare

        skincare = SkincareEntry(user_id=user_id, date=today)

        db.add(skincare)
        db.commit()
        db.refresh(skincare)

        return skincare

    @staticmethod
    def update_today(
        db: Session, user_id: UUID, request: SkincareUpdateRequest
    ) -> SkincareEntry:

        skincare = SkincareService.get_today(db, user_id)

        skincare.face_wash = request.face_wash
        skincare.vitamin_c = request.vitamin_c
        skincare.moisturizer = request.moisturizer
        skincare.sunscreen = request.sunscreen
        skincare.cleanser = request.cleanser
        skincare.evening_moisturizer = request.evening_moisturizer
        skincare.lipcare = request.lipcare

        db.commit()
        db.refresh(skincare)

        return skincare

    @staticmethod
    def get_history(db: Session, user_id: UUID):

        entries = (
            db.query(SkincareEntry)
            .filter(SkincareEntry.user_id == user_id)
            .order_by(SkincareEntry.date.desc())
            .all()
        )

        history = []

        for entry in entries:

            completed = sum([
                entry.face_wash,
                entry.vitamin_c,
                entry.moisturizer,
                entry.sunscreen,
                entry.lipcare,
                entry.cleanser,
                entry.evening_moisturizer,
            ])

            total = 7

            progress = round((completed / total) * 100)

            history.append(
                {
                    "date": entry.date,

                    "completed": completed,
                    "total": total,
                    "progress": progress,

                    "face_wash": entry.face_wash,
                    "vitamin_c": entry.vitamin_c,
                    "moisturizer": entry.moisturizer,
                    "sunscreen": entry.sunscreen,
                    "lipcare": entry.lipcare,

                    "cleanser": entry.cleanser,
                    "evening_moisturizer": entry.evening_moisturizer,
                }
            )

        return history

    @staticmethod
    def get_stats(db: Session, user_id: UUID):

        entries = (
            db.query(SkincareEntry)
            .filter(SkincareEntry.user_id == user_id)
            .order_by(SkincareEntry.date.asc())
            .all()
        )

        total_days = len(entries)

        if total_days == 0:
            return {
                "current_streak": 0,
                "best_streak": 0,
                "total_days": 0,
                "average_completion": 0,
                "message": _streak_message(0, 0, 0),
            }

        total_progress = 0
        perfect_dates = set()

        for entry in entries:

            completed = sum([
                entry.face_wash,
                entry.vitamin_c,
                entry.moisturizer,
                entry.sunscreen,
                entry.lipcare,
                entry.cleanser,
                entry.evening_moisturizer,
            ])

            total_progress += round((completed / 7) * 100)

            if completed == 7:
                perfect_dates.add(entry.date)

        # Best streak: longest run of consecutive *calendar days* that were
        # 100% complete. A gap (a skipped or non-100% day) resets the run.
        best_streak = 0
        run = 0
        prev_date = None

        for entry in entries:
            if entry.date in perfect_dates:
                if prev_date is not None and entry.date == prev_date + timedelta(days=1):
                    run += 1
                else:
                    run = 1
                best_streak = max(best_streak, run)
                prev_date = entry.date
            else:
                run = 0
                prev_date = None

        # Current streak: consecutive 100% days ending today, walking back one
        # calendar day at a time. Today not being logged/complete yet doesn't
        # break a streak, so start from yesterday in that case.
        current_streak = 0
        cursor = date.today()

        if cursor not in perfect_dates:
            cursor = cursor - timedelta(days=1)

        while cursor in perfect_dates:
            current_streak += 1
            cursor = cursor - timedelta(days=1)

        return {
            "current_streak": current_streak,
            "best_streak": best_streak,
            "total_days": total_days,
            "average_completion": round(total_progress / total_days),
            "message": _streak_message(current_streak, best_streak, total_days),
        }
