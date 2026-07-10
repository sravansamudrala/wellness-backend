"""Shared response-shape builders for the gym services.

These assemble the nested dicts (plan → days → exercises, session → exercises → sets)
that the detail endpoints return. Kept in a neutral module so plan_service and
workout_service can both use them without importing each other.
"""

from sqlalchemy.orm import Session

from app.models.gym.exercise import Exercise
from app.models.gym.plan import PlanDay, PlanExercise, WorkoutPlan
from app.models.gym.session import SessionExercise, SessionSet, WorkoutSession


def _exercise_map(db: Session, exercise_ids):
    if not exercise_ids:
        return {}
    rows = db.query(Exercise).filter(Exercise.id.in_(list(exercise_ids))).all()
    return {row.id: row for row in rows}


def build_day_detail(db: Session, day: PlanDay) -> dict:
    plan_exercises = (
        db.query(PlanExercise)
        .filter(PlanExercise.plan_day_id == day.id)
        .order_by(PlanExercise.order_index.asc())
        .all()
    )

    ex_map = _exercise_map(db, [pe.exercise_id for pe in plan_exercises])

    exercises = [
        {
            "id": pe.id,
            "order_index": pe.order_index,
            "target_sets": pe.target_sets,
            "target_reps": pe.target_reps,
            "target_rest_seconds": pe.target_rest_seconds,
            "exercise": ex_map.get(pe.exercise_id),
        }
        for pe in plan_exercises
    ]

    return {
        "id": day.id,
        "name": day.name,
        "order_index": day.order_index,
        "exercises": exercises,
    }


def build_plan_detail(db: Session, plan: WorkoutPlan) -> dict:
    days = (
        db.query(PlanDay)
        .filter(PlanDay.plan_id == plan.id)
        .order_by(PlanDay.order_index.asc())
        .all()
    )

    return {
        "id": plan.id,
        "name": plan.name,
        "description": plan.description,
        "goal": plan.goal,
        "is_custom": plan.is_custom,
        "days": [build_day_detail(db, day) for day in days],
    }


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
        "plan_day_id": session.plan_day_id,
        "plan_id": session.plan_id,
        "name": session.name,
        "status": session.status,
        "started_at": session.started_at,
        "completed_at": session.completed_at,
        "notes": session.notes,
        "exercises": exercises,
    }