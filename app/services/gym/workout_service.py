from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.gym.plan import PlanDay, PlanExercise, WorkoutPlan
from app.models.gym.session import SessionExercise, SessionSet, WorkoutSession
from app.models.gym.state import GymState
from app.schemas.gym.session import LogSetsRequest, StartSessionRequest
from app.schemas.gym.state import GymStateUpdateRequest
from app.services.gym.builders import build_day_detail, build_session_detail


class WorkoutService:
    """The queue engine + workout-session lifecycle."""

    # ----- State (singleton cursor) -----

    @staticmethod
    def get_state(db: Session) -> GymState:
        state = db.query(GymState).first()
        if state is None:
            state = GymState()
            db.add(state)
            db.commit()
            db.refresh(state)
        return state

    @staticmethod
    def update_state(db: Session, request: GymStateUpdateRequest) -> GymState:
        state = WorkoutService.get_state(db)
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
    def get_next_day(db: Session):
        """Resolve the next plan day in the rotation, or None if no active plan."""
        state = WorkoutService.get_state(db)
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

        # Cursor points at a day not in the active plan (e.g. plan changed) — restart.
        return days[0]

    @staticmethod
    def get_active(db: Session) -> dict:
        state = WorkoutService.get_state(db)

        active_plan = None
        if state.active_plan_id is not None:
            active_plan = (
                db.query(WorkoutPlan)
                .filter(WorkoutPlan.id == state.active_plan_id)
                .first()
            )

        next_day = WorkoutService.get_next_day(db)
        next_day_detail = build_day_detail(db, next_day) if next_day else None

        return {
            "active_plan": active_plan,
            "next_day": next_day_detail,
            "unit": state.unit,
        }

    # ----- Sessions -----

    @staticmethod
    def get_current_session(db: Session):
        return (
            db.query(WorkoutSession)
            .filter(WorkoutSession.status == "in_progress")
            .order_by(WorkoutSession.started_at.desc())
            .first()
        )

    @staticmethod
    def get_current_session_detail(db: Session):
        session = WorkoutService.get_current_session(db)
        if session is None:
            return None
        return build_session_detail(db, session)

    @staticmethod
    def start_session(db: Session, request: StartSessionRequest) -> dict:
        # One in-progress session at a time — resume the existing one if present.
        existing = WorkoutService.get_current_session(db)
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
            plan_day = WorkoutService.get_next_day(db)

        if plan_day is not None:
            session = WorkoutSession(
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
                name=request.name or "Workout",
                status="in_progress",
            )
            db.add(session)
            db.flush()

        db.commit()
        db.refresh(session)
        return build_session_detail(db, session)

    @staticmethod
    def log_sets(db: Session, session_id: UUID, request: LogSetsRequest):
        session = (
            db.query(WorkoutSession)
            .filter(WorkoutSession.id == session_id)
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
    def complete_session(db: Session, session_id: UUID):
        session = (
            db.query(WorkoutSession)
            .filter(WorkoutSession.id == session_id)
            .first()
        )
        if session is None:
            return None

        session.status = "completed"
        session.completed_at = datetime.utcnow()

        # Advance the rotation cursor only for a day of the currently active plan.
        if session.plan_day_id is not None:
            state = WorkoutService.get_state(db)
            if session.plan_id == state.active_plan_id:
                state.last_completed_day_id = session.plan_day_id

        db.commit()
        db.refresh(session)
        return build_session_detail(db, session)

    @staticmethod
    def abandon_session(db: Session, session_id: UUID):
        session = (
            db.query(WorkoutSession)
            .filter(WorkoutSession.id == session_id)
            .first()
        )
        if session is None:
            return None

        session.status = "abandoned"
        db.commit()
        db.refresh(session)
        return build_session_detail(db, session)

    @staticmethod
    def get_history(db: Session):
        return (
            db.query(WorkoutSession)
            .order_by(WorkoutSession.started_at.desc())
            .all()
        )

    @staticmethod
    def get_session(db: Session, session_id: UUID):
        session = (
            db.query(WorkoutSession)
            .filter(WorkoutSession.id == session_id)
            .first()
        )
        if session is None:
            return None
        return build_session_detail(db, session)
