"""Shared response-shape builder for the gym services.

Assembles the nested dict (session → exercises → sets) that session detail
endpoints return. Kept in a neutral module so services that need it don't
have to duplicate the query.
"""

from sqlalchemy.orm import Session

from app.models.gym.exercise import Exercise
from app.models.gym.session import SessionExercise, SessionSet, WorkoutSession


def _exercise_map(db: Session, exercise_ids):
    if not exercise_ids:
        return {}
    rows = db.query(Exercise).filter(Exercise.id.in_(list(exercise_ids))).all()
    return {row.id: row for row in rows}


def build_session_detail(db: Session, session: WorkoutSession) -> dict:
    session_exercises = (
        db.query(SessionExercise)
        .filter(SessionExercise.session_id == session.id)
        .order_by(SessionExercise.order_index.asc())
        .all()
    )

    ex_map = _exercise_map(db, [se.exercise_id for se in session_exercises])

    exercises = []
    for se in session_exercises:
        sets = (
            db.query(SessionSet)
            .filter(SessionSet.session_exercise_id == se.id)
            .order_by(SessionSet.set_number.asc())
            .all()
        )
        exercises.append(
            {
                "id": se.id,
                "order_index": se.order_index,
                "notes": se.notes,
                "exercise": ex_map.get(se.exercise_id),
                "sets": sets,
            }
        )

    return {
        "id": session.id,
        "name": session.name,
        "status": session.status,
        "started_at": session.started_at,
        "completed_at": session.completed_at,
        "notes": session.notes,
        "exercises": exercises,
    }
