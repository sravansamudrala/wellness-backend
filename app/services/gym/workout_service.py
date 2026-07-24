from datetime import date, datetime
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.gym.exercise import Exercise, MuscleGroup
from app.models.gym.session import SessionExercise, SessionSet, WorkoutSession
from app.models.gym.state import GymState
from app.schemas.gym.session import QuickLogRequest
from app.schemas.gym.state import GymStateUpdateRequest
from app.services.gym.builders import build_session_detail

# Default cycle for the "next up" suggestion in Log Workout. Cardio and Core are
# deliberately excluded — logged alongside whatever day it is, not their own turn.
DEFAULT_ROTATION_ORDER = ["Chest", "Biceps", "Back", "Shoulders", "Legs", "Triceps"]


class WorkoutService:
    """Freestyle workout logging + the Log Workout rotation suggestion, scoped to
    one user."""

    # ----- State (per-user settings: unit + rotation order) -----

    @staticmethod
    def get_state(db: Session, user_id: UUID) -> GymState:
        state = (
            db.query(GymState)
            .filter(GymState.user_id == user_id)
            .first()
        )
        if state is None:
            state = GymState(user_id=user_id, rotation_order=DEFAULT_ROTATION_ORDER)
            db.add(state)
            db.commit()
            db.refresh(state)
        elif state.rotation_order is None:
            # Row predates the rotation_order column (or was cleared) — backfill.
            state.rotation_order = DEFAULT_ROTATION_ORDER
            db.commit()
            db.refresh(state)
        return state

    @staticmethod
    def update_state(
        db: Session, user_id: UUID, request: GymStateUpdateRequest
    ) -> GymState:
        state = WorkoutService.get_state(db, user_id)
        state.unit = request.unit
        state.rotation_order = request.rotation_order
        db.commit()
        db.refresh(state)
        return state

    # ----- Rotation suggestion -----

    @staticmethod
    def _session_muscle_group_names(db: Session, session_id: UUID):
        """Ordered, deduped muscle-group names touched by a session's exercises,
        in the order they were added."""
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
            return []

        names_map = {
            mg.id: mg.name
            for mg in db.query(MuscleGroup).filter(MuscleGroup.id.in_(ordered_ids)).all()
        }
        return [names_map[i] for i in ordered_ids if i in names_map]

    @staticmethod
    def get_next_log_category(db: Session, user_id: UUID):
        """Which muscle group should be suggested next in Log Workout, based on a
        rotating cycle (not a calendar) — advances past every rotation category the
        most recent completed session touched, wrapping around."""
        state = WorkoutService.get_state(db, user_id)
        rotation = state.rotation_order or DEFAULT_ROTATION_ORDER
        if not rotation:
            return None

        last_session = (
            db.query(WorkoutSession)
            .filter(
                WorkoutSession.user_id == user_id,
                WorkoutSession.status == "completed",
            )
            .order_by(WorkoutSession.started_at.desc())
            .first()
        )

        if last_session is None:
            next_name = rotation[0]
        else:
            touched = WorkoutService._session_muscle_group_names(db, last_session.id)
            touched_indices = [rotation.index(n) for n in touched if n in rotation]
            if not touched_indices:
                next_name = rotation[0]
            else:
                next_index = (max(touched_indices) + 1) % len(rotation)
                next_name = rotation[next_index]

        return db.query(MuscleGroup).filter(MuscleGroup.name == next_name).first()

    # ----- Sessions -----

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
        names = WorkoutService._session_muscle_group_names(db, session_id)
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
