import logging
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.gym.exercise import Exercise, MuscleGroup
from app.models.gym.plan import PlanDay, PlanExercise, WorkoutPlan
from app.models.gym.session import SessionExercise, SessionSet, WorkoutSession
from app.models.gym.state import GymState
from app.schemas.gym.session import (
    LogSetsRequest,
    QuickLogRequest,
    StartSessionRequest,
)
from app.schemas.gym.state import GymStateUpdateRequest
from app.services.gym.builders import build_day_detail, build_session_detail

logger = logging.getLogger(__name__)


class WorkoutService:
    """The queue engine + workout-session lifecycle, scoped to one user."""

    # ----- State (per-user singleton cursor) -----

    @staticmethod
    def get_state(db: Session, user_id: UUID) -> GymState:
        state = (
            db.query(GymState)
            .filter(GymState.user_id == user_id)
            .first()
        )
        if state is None:
            state = GymState(user_id=user_id)
            db.add(state)
            db.commit()
            db.refresh(state)
        return state

    @staticmethod
    def update_state(
        db: Session, user_id: UUID, request: GymStateUpdateRequest
    ) -> GymState:
        state = WorkoutService.get_state(db, user_id)
        state.unit = request.unit
        db.commit()
        db.refresh(state)
        return state

    # ----- Queue resolution -----

    @staticmethod
    def _plan_days(db: Session, plan_id: UUID):
        return (
            db.query(PlanDay)
            .filter(PlanDay.plan_id == plan_id)
            .order_by(PlanDay.order_index.asc())
            .all()
        )

    @staticmethod
    def get_next_day(db: Session, user_id: UUID):
        """Resolve the next plan day in the rotation, or None if no active plan."""
        state = WorkoutService.get_state(db, user_id)
        if state.active_plan_id is None:
            return None

        days = WorkoutService._plan_days(db, state.active_plan_id)
        if not days:
            return None

        if state.last_completed_day_id is None:
            return days[0]

        ids = [day.id for day in days]
        if state.last_completed_day_id in ids:
            idx = ids.index(state.last_completed_day_id)
            return days[(idx + 1) % len(days)]

        # The user's last-completed day isn't in their current plan anymore
        # (they switched plans) — so just start over from day 1.
        logger.info("User %s switched plans — restarting from day 1", user_id)
        return days[0]

    @staticmethod
    def get_active(db: Session, user_id: UUID) -> dict:
        state = WorkoutService.get_state(db, user_id)

        active_plan = None
        if state.active_plan_id is not None:
            active_plan = (
                db.query(WorkoutPlan)
                .filter(WorkoutPlan.id == state.active_plan_id)
                .first()
            )

        next_day = WorkoutService.get_next_day(db, user_id)
        next_day_detail = build_day_detail(db, next_day) if next_day else None

        return {
            "active_plan": active_plan,
            "next_day": next_day_detail,
            "unit": state.unit,
        }

    # ----- Sessions -----

    @staticmethod
    def get_current_session(db: Session, user_id: UUID):
        return (
            db.query(WorkoutSession)
            .filter(
                WorkoutSession.user_id == user_id,
                WorkoutSession.status == "in_progress",
            )
            .order_by(WorkoutSession.started_at.desc())
            .first()
        )

    @staticmethod
    def get_current_session_detail(db: Session, user_id: UUID):
        session = WorkoutService.get_current_session(db, user_id)
        if session is None:
            return None
        return build_session_detail(db, session)

    @staticmethod
    def start_session(
        db: Session, user_id: UUID, request: StartSessionRequest
    ) -> dict:
        # One in-progress session at a time per user — resume the existing one.
        existing = WorkoutService.get_current_session(db, user_id)
        if existing is not None:
            return build_session_detail(db, existing)

        plan_day = None
        if request.plan_day_id is not None:
            plan_day = (
                db.query(PlanDay)
                .filter(PlanDay.id == request.plan_day_id)
                .first()
            )
        elif request.name is None:
            # No specific day and no freestyle name → start the next queued day.
            plan_day = WorkoutService.get_next_day(db, user_id)

        if plan_day is not None:
            session = WorkoutSession(
                user_id=user_id,
                plan_day_id=plan_day.id,
                plan_id=plan_day.plan_id,
                name=plan_day.name,
                status="in_progress",
            )
            db.add(session)
            db.flush()

            # Seed the session's exercises from the plan day's prescription.
            plan_exercises = (
                db.query(PlanExercise)
                .filter(PlanExercise.plan_day_id == plan_day.id)
                .order_by(PlanExercise.order_index.asc())
                .all()
            )
            for pe in plan_exercises:
                db.add(
                    SessionExercise(
                        session_id=session.id,
                        exercise_id=pe.exercise_id,
                        order_index=pe.order_index,
                    )
                )
        else:
            # Freestyle session (no plan day).
            session = WorkoutSession(
                user_id=user_id,
                name=request.name or "Workout",
                status="in_progress",
            )
            db.add(session)
            db.flush()

        db.commit()
        db.refresh(session)
        return build_session_detail(db, session)

    @staticmethod
    def log_sets(db: Session, user_id: UUID, session_id: UUID, request: LogSetsRequest):
        session = (
            db.query(WorkoutSession)
            .filter(
                WorkoutSession.id == session_id,
                WorkoutSession.user_id == user_id,
            )
            .first()
        )
        if session is None:
            return None

        for entry in request.exercises:
            se = (
                db.query(SessionExercise)
                .filter(
                    SessionExercise.id == entry.session_exercise_id,
                    SessionExercise.session_id == session_id,
                )
                .first()
            )
            if se is None:
                continue

            # Replace the logged sets for this exercise.
            db.query(SessionSet).filter(
                SessionSet.session_exercise_id == se.id
            ).delete()

            for s in entry.sets:
                db.add(
                    SessionSet(
                        session_exercise_id=se.id,
                        set_number=s.set_number,
                        reps=s.reps,
                        weight_kg=s.weight_kg,
                        is_warmup=s.is_warmup,
                        is_completed=s.is_completed,
                        rest_seconds=s.rest_seconds,
                    )
                )

        db.commit()
        db.refresh(session)
        return build_session_detail(db, session)

    @staticmethod
    def complete_session(db: Session, user_id: UUID, session_id: UUID):
        session = (
            db.query(WorkoutSession)
            .filter(
                WorkoutSession.id == session_id,
                WorkoutSession.user_id == user_id,
            )
            .first()
        )
        if session is None:
            return None

        session.status = "completed"
        session.completed_at = datetime.utcnow()

        # Advance the rotation cursor only for a day of the currently active plan.
        if session.plan_day_id is not None:
            state = WorkoutService.get_state(db, user_id)
            if session.plan_id == state.active_plan_id:
                state.last_completed_day_id = session.plan_day_id

        db.commit()
        db.refresh(session)
        return build_session_detail(db, session)

    @staticmethod
    def abandon_session(db: Session, user_id: UUID, session_id: UUID):
        session = (
            db.query(WorkoutSession)
            .filter(
                WorkoutSession.id == session_id,
                WorkoutSession.user_id == user_id,
            )
            .first()
        )
        if session is None:
            return None

        session.status = "abandoned"
        db.commit()
        db.refresh(session)
        return build_session_detail(db, session)

    @staticmethod
    def get_history(db: Session, user_id: UUID):
        return (
            db.query(WorkoutSession)
            .filter(WorkoutSession.user_id == user_id)
            .order_by(WorkoutSession.started_at.desc())
            .all()
        )

    @staticmethod
    def get_session(db: Session, user_id: UUID, session_id: UUID):
        session = (
            db.query(WorkoutSession)
            .filter(
                WorkoutSession.id == session_id,
                WorkoutSession.user_id == user_id,
            )
            .first()
        )
        if session is None:
            return None
        return build_session_detail(db, session)

    @staticmethod
    def _derive_workout_name(db: Session, session_id: UUID) -> str:
        """Name a session from the distinct muscle groups of its exercises, in the
        order they were added, e.g. 'Back, Chest & Cardio'. 'Workout' if none."""
        rows = (
            db.query(Exercise.primary_muscle_group_id)
            .join(SessionExercise, SessionExercise.exercise_id == Exercise.id)
            .filter(SessionExercise.session_id == session_id)
            .order_by(SessionExercise.order_index.asc())
            .all()
        )
        ordered_ids = []
        for (mg_id,) in rows:
            if mg_id is not None and mg_id not in ordered_ids:
                ordered_ids.append(mg_id)
        if not ordered_ids:
            return "Workout"

        names_map = {
            mg.id: mg.name
            for mg in db.query(MuscleGroup).filter(MuscleGroup.id.in_(ordered_ids)).all()
        }
        names = [names_map[i] for i in ordered_ids if i in names_map]
        if not names:
            return "Workout"
        if len(names) == 1:
            return names[0]
        return ", ".join(names[:-1]) + " & " + names[-1]

    @staticmethod
    def quick_log(db: Session, user_id: UUID, request: QuickLogRequest):
        """Freestyle 'Log Workout'. Same-day saves MERGE into one workout: the
        exercises are appended (deduped) to today's session, which is then
        (re)named from the muscle groups trained. Weightless (one done set each)."""
        today = date.today()
        session = (
            db.query(WorkoutSession)
            .filter(
                WorkoutSession.user_id == user_id,
                WorkoutSession.status == "completed",
                func.date(WorkoutSession.completed_at) == today,
            )
            .order_by(WorkoutSession.started_at.asc())
            .first()
        )

        if session is None:
            now = datetime.utcnow()
            session = WorkoutSession(
                user_id=user_id,
                name="Workout",
                status="completed",
                started_at=now,
                completed_at=now,
            )
            db.add(session)
            db.flush()

        existing_ids = {
            se.exercise_id
            for se in db.query(SessionExercise)
            .filter(SessionExercise.session_id == session.id)
            .all()
        }
        order = len(existing_ids)
        for exercise_id in request.exercise_ids:
            if exercise_id in existing_ids:
                continue  # already logged today — dedupe
            se = SessionExercise(
                session_id=session.id, exercise_id=exercise_id, order_index=order
            )
            order += 1
            db.add(se)
            db.flush()
            db.add(SessionSet(session_exercise_id=se.id, set_number=1, is_completed=True))
            existing_ids.add(exercise_id)

        # (Re)derive the name from everything now in the session.
        session.name = request.name or WorkoutService._derive_workout_name(db, session.id)

        db.commit()
        db.refresh(session)
        return build_session_detail(db, session)