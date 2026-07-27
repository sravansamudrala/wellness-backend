from datetime import date, timedelta
from typing import Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.skincare import SkincareEntry, SkincareEntryHabit, SkincareHabit
from app.schemas.skincare import SkincareUpdateRequest
from app.schemas.skincare_habit import SkincareHabitUpsertItem


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
    def _get_or_create_today_entry(db: Session, user_id: UUID) -> SkincareEntry:
        today = date.today()

        entry = (
            db.query(SkincareEntry)
            .filter(
                SkincareEntry.user_id == user_id,
                SkincareEntry.date == today,
            )
            .first()
        )

        if entry is None:
            entry = SkincareEntry(user_id=user_id, date=today)
            db.add(entry)
            db.commit()
            db.refresh(entry)

        SkincareService._sync_entry_habits(db, user_id, entry)

        return entry

    @staticmethod
    def _sync_entry_habits(db: Session, user_id: UUID, entry: SkincareEntry) -> None:
        """Ensure today's entry has an entry_habit row for every active habit.

        Handles a habit created mid-day — never touches rows for habits
        that are no longer active or that already have a row.
        """
        active_ids = {
            row[0]
            for row in db.query(SkincareHabit.id).filter(
                SkincareHabit.user_id == user_id,
                SkincareHabit.is_active.is_(True),
            )
        }

        existing_ids = {
            row[0]
            for row in db.query(SkincareEntryHabit.habit_id).filter(
                SkincareEntryHabit.entry_id == entry.id
            )
        }

        missing = active_ids - existing_ids

        if not missing:
            return

        for habit_id in missing:
            db.add(SkincareEntryHabit(entry_id=entry.id, habit_id=habit_id, completed=False))

        db.commit()

    @staticmethod
    def _habit_rows_for_entry(db: Session, entry_id: UUID) -> list[dict]:
        rows = (
            db.query(SkincareEntryHabit.habit_id, SkincareEntryHabit.completed, SkincareHabit.name)
            .join(SkincareHabit, SkincareHabit.id == SkincareEntryHabit.habit_id)
            .filter(
                SkincareEntryHabit.entry_id == entry_id,
                SkincareHabit.is_active.is_(True),
            )
            .order_by(SkincareHabit.sort_order.asc(), SkincareHabit.created_at.asc())
            .all()
        )

        return [
            {"habit_id": habit_id, "name": name, "completed": completed}
            for habit_id, completed, name in rows
        ]

    @staticmethod
    def _habit_rows_by_entry(db: Session, user_id: UUID) -> dict[UUID, list[dict]]:
        """One grouped query for every entry_habit row across a user's history.

        Avoids an N+1 join per entry in get_history/get_stats, which iterate
        every historical entry with no pagination.
        """
        rows = (
            db.query(
                SkincareEntryHabit.entry_id,
                SkincareEntryHabit.habit_id,
                SkincareEntryHabit.completed,
                SkincareHabit.name,
            )
            .join(SkincareEntry, SkincareEntry.id == SkincareEntryHabit.entry_id)
            .join(SkincareHabit, SkincareHabit.id == SkincareEntryHabit.habit_id)
            .filter(SkincareEntry.user_id == user_id)
            .all()
        )

        by_entry: dict[UUID, list[dict]] = {}
        for entry_id, habit_id, completed, name in rows:
            by_entry.setdefault(entry_id, []).append(
                {"habit_id": habit_id, "name": name, "completed": completed}
            )
        return by_entry

    @staticmethod
    def _serialize_entry(db: Session, entry: SkincareEntry) -> dict:
        return {
            "id": entry.id,
            "date": entry.date,
            "created_at": entry.created_at,
            "updated_at": entry.updated_at,
            "habits": SkincareService._habit_rows_for_entry(db, entry.id),
        }

    @staticmethod
    def get_today(db: Session, user_id: UUID) -> dict:
        entry = SkincareService._get_or_create_today_entry(db, user_id)
        return SkincareService._serialize_entry(db, entry)

    @staticmethod
    def update_today(
        db: Session, user_id: UUID, request: SkincareUpdateRequest
    ) -> Tuple[Optional[dict], Optional[str]]:

        entry = SkincareService._get_or_create_today_entry(db, user_id)

        # Only currently-active habits count for today's set — a habit
        # disabled after its entry_habit row was created must disappear from
        # today immediately, same as one that was never synced in.
        entry_habits = (
            db.query(SkincareEntryHabit)
            .join(SkincareHabit, SkincareHabit.id == SkincareEntryHabit.habit_id)
            .filter(
                SkincareEntryHabit.entry_id == entry.id,
                SkincareHabit.is_active.is_(True),
            )
            .all()
        )

        active_ids = {eh.habit_id for eh in entry_habits}
        payload_ids = {item.habit_id for item in request.habits}

        if payload_ids != active_ids:
            return None, "Payload must include exactly today's active habits — none missing, none extra."

        completed_by_id = {item.habit_id: item.completed for item in request.habits}

        for entry_habit in entry_habits:
            entry_habit.completed = completed_by_id[entry_habit.habit_id]

        db.commit()

        return SkincareService._serialize_entry(db, entry), None

    @staticmethod
    def get_history(db: Session, user_id: UUID) -> list[dict]:

        entries = (
            db.query(SkincareEntry)
            .filter(SkincareEntry.user_id == user_id)
            .order_by(SkincareEntry.date.desc())
            .all()
        )

        habits_by_entry = SkincareService._habit_rows_by_entry(db, user_id)

        history = []

        for entry in entries:
            habits = habits_by_entry.get(entry.id, [])
            total = len(habits)
            completed = sum(1 for h in habits if h["completed"])
            progress = round((completed / total) * 100) if total else 0

            history.append(
                {
                    "date": entry.date,
                    "completed": completed,
                    "total": total,
                    "progress": progress,
                    "habits": habits,
                }
            )

        return history

    @staticmethod
    def get_stats(db: Session, user_id: UUID) -> dict:

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

        habits_by_entry = SkincareService._habit_rows_by_entry(db, user_id)

        total_progress = 0
        perfect_dates = set()

        for entry in entries:
            habits = habits_by_entry.get(entry.id, [])
            total = len(habits)
            completed = sum(1 for h in habits if h["completed"])

            total_progress += round((completed / total) * 100) if total else 0

            # A day with zero configured habits is never a "perfect" day.
            if total > 0 and completed == total:
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

    @staticmethod
    def list_habits(db: Session, user_id: UUID) -> list[SkincareHabit]:
        return (
            db.query(SkincareHabit)
            .filter(SkincareHabit.user_id == user_id)
            .order_by(SkincareHabit.sort_order.asc(), SkincareHabit.created_at.asc())
            .all()
        )

    @staticmethod
    def upsert_habits(
        db: Session, user_id: UUID, items: list[SkincareHabitUpsertItem]
    ) -> Tuple[Optional[list[SkincareHabit]], Optional[str]]:

        existing = (
            db.query(SkincareHabit)
            .filter(SkincareHabit.user_id == user_id)
            .all()
        )
        existing_by_id = {habit.id: habit for habit in existing}

        for item in items:
            if item.id is not None and item.id not in existing_by_id:
                return None, "not_found"

        payload_names = [item.name for item in items]
        if len(payload_names) != len(set(payload_names)):
            return None, "Duplicate habit name in request."

        # Names stay reserved even once disabled, so any existing habit not
        # included in this payload still blocks reuse of its name.
        payload_ids = {item.id for item in items if item.id is not None}
        untouched_names = {habit.name for habit in existing if habit.id not in payload_ids}
        if untouched_names & set(payload_names):
            return None, "Habit name already in use."

        for item in items:
            if item.id is None:
                db.add(
                    SkincareHabit(
                        user_id=user_id,
                        name=item.name,
                        is_active=item.is_active,
                        sort_order=item.sort_order,
                    )
                )
            else:
                habit = existing_by_id[item.id]
                habit.name = item.name
                habit.is_active = item.is_active
                habit.sort_order = item.sort_order

        db.commit()

        return SkincareService.list_habits(db, user_id), None
