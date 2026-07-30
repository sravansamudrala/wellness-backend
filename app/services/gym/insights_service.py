from datetime import date, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.timezone import local_today, to_local_date
from app.models.gym.exercise import Exercise, MuscleGroup
from app.models.gym.session import SessionExercise, SessionSet, WorkoutSession
from app.services.ai_message_service import generate_gym_coach_message
from app.services.gym.workout_service import WorkoutService


def _workout_date(session: WorkoutSession) -> date:
    dt = session.completed_at or session.started_at
    return to_local_date(dt)


def _stats_message(current_streak: int, total_workouts: int, days_since_last) -> str:
    if total_workouts == 0:
        return "Start your first workout to kick things off! 🏋️"
    if days_since_last is not None and days_since_last >= 3:
        return f"It's been {days_since_last} days — time to get back to it! 💪"
    if current_streak >= 7:
        return f"🔥 {current_streak} days in a row — you're on fire!"
    if current_streak >= 3:
        return f"{current_streak}-day streak — momentum's building! 💪"
    if current_streak >= 1:
        return "Nice work today — keep the streak alive! 👍"
    return "Ready when you are — start today's workout! 🚀"


class InsightsService:
    """All insights are derived from a single user's completed workout sessions."""

    @staticmethod
    def _completed_sessions(db: Session, user_id: UUID):
        return (
            db.query(WorkoutSession)
            .filter(
                WorkoutSession.user_id == user_id,
                WorkoutSession.status == "completed",
            )
            .order_by(WorkoutSession.started_at.asc())
            .all()
        )

    @staticmethod
    def get_stats(db: Session, user_id: UUID) -> dict:
        sessions = InsightsService._completed_sessions(db, user_id)
        total_workouts = len(sessions)

        if total_workouts == 0:
            return {
                "total_workouts": 0,
                "current_streak": 0,
                "best_streak": 0,
                "this_week": 0,
                "last_workout_date": None,
                "days_since_last": None,
                "message": _stats_message(0, 0, None),
            }

        workout_dates = sorted({_workout_date(s) for s in sessions})
        date_set = set(workout_dates)
        today = local_today()

        # Best streak: longest run of consecutive calendar days with a workout.
        best_streak = 0
        run = 0
        prev = None
        for d in workout_dates:
            if prev is not None and d == prev + timedelta(days=1):
                run += 1
            else:
                run = 1
            best_streak = max(best_streak, run)
            prev = d

        # Current streak: consecutive days ending today (or yesterday if not trained today).
        current_streak = 0
        cursor = today
        if cursor not in date_set:
            cursor = cursor - timedelta(days=1)
        while cursor in date_set:
            current_streak += 1
            cursor = cursor - timedelta(days=1)

        # Monday-start calendar week — kept identical between this_week and
        # trained_this_week below, not a rolling 7-day window.
        week_start = today - timedelta(days=today.weekday())
        this_week = sum(1 for d in workout_dates if d >= week_start)

        last_workout_date = workout_dates[-1]
        days_since_last = (today - last_workout_date).days

        fallback_message = _stats_message(current_streak, total_workouts, days_since_last)

        # Recovery reflects which muscle groups were trained, not weights —
        # volume/records need weight_kg, which freestyle quick-log sessions
        # don't carry, so they'd be sparse/empty for real usage here.
        recovery = InsightsService.get_recovery(db, user_id)
        trained_this_week = [
            r["muscle_group_name"]
            for r in sorted(
                (r for r in recovery if r["last_trained"] is not None and r["last_trained"] >= week_start),
                key=lambda r: r["days_since"],
            )
        ]
        # "Needs attention" only makes sense for muscle groups on the user's
        # rotation — Cardio/Core are deliberately excluded there too (see
        # WorkoutService.DEFAULT_ROTATION_ORDER): they're logged alongside any
        # day rather than following a recovery cycle, so flagging them as
        # "overdue" would be misleading.
        rotation = set(WorkoutService.get_state(db, user_id).rotation_order or [])
        overdue = sorted(
            (
                r
                for r in recovery
                if r["days_since"] is not None
                and r["days_since"] > 6
                and r["muscle_group_name"] in rotation
            ),
            key=lambda r: r["days_since"],
            reverse=True,
        )
        stalest_group = overdue[0]["muscle_group_name"] if overdue else None
        stalest_days = overdue[0]["days_since"] if overdue else None

        return {
            "total_workouts": total_workouts,
            "current_streak": current_streak,
            "best_streak": best_streak,
            "this_week": this_week,
            "last_workout_date": last_workout_date,
            "days_since_last": days_since_last,
            "message": generate_gym_coach_message(
                current_streak,
                this_week,
                total_workouts,
                trained_this_week,
                stalest_group,
                stalest_days,
                [r["muscle_group_name"] for r in recovery],
                fallback_message,
            ),
        }

    @staticmethod
    def _session_volume(db: Session, session_id) -> float:
        volume = 0.0
        session_exercises = (
            db.query(SessionExercise)
            .filter(SessionExercise.session_id == session_id)
            .all()
        )
        for se in session_exercises:
            sets = (
                db.query(SessionSet)
                .filter(SessionSet.session_exercise_id == se.id)
                .all()
            )
            for s in sets:
                if s.reps and s.weight_kg:
                    volume += s.reps * float(s.weight_kg)
        return volume

    @staticmethod
    def get_volume(db: Session, user_id: UUID, range: str = "all") -> dict:
        sessions = InsightsService._completed_sessions(db, user_id)

        today = local_today()
        if range == "week":
            cutoff = today - timedelta(days=6)
        elif range == "month":
            cutoff = today - timedelta(days=29)
        else:
            range = "all"
            cutoff = None

        points = []
        total = 0.0
        for s in sessions:
            d = _workout_date(s)
            if cutoff is not None and d < cutoff:
                continue
            vol = InsightsService._session_volume(db, s.id)
            total += vol
            points.append({"date": d, "volume_kg": round(vol, 2)})

        return {
            "range": range,
            "total_volume_kg": round(total, 2),
            "points": points,
        }

    @staticmethod
    def get_records(db: Session, user_id: UUID):
        sessions = InsightsService._completed_sessions(db, user_id)
        session_ids = [s.id for s in sessions]
        if not session_ids:
            return []

        session_exercises = (
            db.query(SessionExercise)
            .filter(SessionExercise.session_id.in_(session_ids))
            .all()
        )

        # exercise_id -> aggregated records
        records = {}
        for se in session_exercises:
            sets = (
                db.query(SessionSet)
                .filter(SessionSet.session_exercise_id == se.id)
                .all()
            )
            for s in sets:
                if not (s.reps and s.weight_kg):
                    continue
                weight = float(s.weight_kg)
                est_1rm = weight * (1 + s.reps / 30)  # Epley formula
                set_volume = s.reps * weight

                rec = records.setdefault(
                    se.exercise_id,
                    {"max_weight_kg": 0.0, "estimated_1rm_kg": 0.0, "max_volume_kg": 0.0},
                )
                rec["max_weight_kg"] = max(rec["max_weight_kg"], weight)
                rec["estimated_1rm_kg"] = max(rec["estimated_1rm_kg"], est_1rm)
                rec["max_volume_kg"] = max(rec["max_volume_kg"], set_volume)

        if not records:
            return []

        ex_rows = (
            db.query(Exercise)
            .filter(Exercise.id.in_(list(records.keys())))
            .all()
        )
        names = {row.id: row.name for row in ex_rows}

        result = []
        for exercise_id, rec in records.items():
            result.append(
                {
                    "exercise_id": exercise_id,
                    "exercise_name": names.get(exercise_id, "Unknown"),
                    "max_weight_kg": round(rec["max_weight_kg"], 2),
                    "estimated_1rm_kg": round(rec["estimated_1rm_kg"], 2),
                    "max_volume_kg": round(rec["max_volume_kg"], 2),
                }
            )

        result.sort(key=lambda r: r["exercise_name"])
        return result

    @staticmethod
    def get_recovery(db: Session, user_id: UUID):
        """Days since each muscle group was last trained (via exercise.primary_muscle_group).

        Muscle groups are shared master data; recency is derived from this
        user's completed sessions only.
        """
        muscle_groups = db.query(MuscleGroup).order_by(MuscleGroup.name.asc()).all()
        if not muscle_groups:
            return []

        today = local_today()

        # Map exercise_id -> primary_muscle_group_id (only exercises that have one).
        exercises = (
            db.query(Exercise)
            .filter(Exercise.primary_muscle_group_id.isnot(None))
            .all()
        )
        ex_to_muscle = {e.id: e.primary_muscle_group_id for e in exercises}

        sessions = InsightsService._completed_sessions(db, user_id)

        # muscle_group_id -> latest trained date.
        last_trained = {}
        for s in sessions:
            d = _workout_date(s)
            ses = (
                db.query(SessionExercise)
                .filter(SessionExercise.session_id == s.id)
                .all()
            )
            for se in ses:
                muscle_id = ex_to_muscle.get(se.exercise_id)
                if muscle_id is None:
                    continue
                if muscle_id not in last_trained or d > last_trained[muscle_id]:
                    last_trained[muscle_id] = d

        result = []
        for mg in muscle_groups:
            trained = last_trained.get(mg.id)
            result.append(
                {
                    "muscle_group_id": mg.id,
                    "muscle_group_name": mg.name,
                    "last_trained": trained,
                    "days_since": (today - trained).days if trained else None,
                }
            )
        return result
