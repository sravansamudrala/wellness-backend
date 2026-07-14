"""ONE-OFF: seed the Cardio section + missing exercises, and backfill Sravan's
Jul 12-14 workouts via the freestyle logger. Idempotent; delete after running.

Run (repo root, venv active):
    python -m scripts.setup_gym_categories
"""

from datetime import date, datetime

from sqlalchemy import func

from app.database.session import SessionLocal
from app.models.gym.exercise import Equipment, Exercise, MuscleGroup
from app.models.gym.session import SessionExercise, SessionSet, WorkoutSession
from app.models.user import User

EMAIL = "sravan@gmail.com"

# name -> (muscle_group, equipment, category)
EXERCISES = {
    "Treadmill": ("Cardio", "Machine", "cardio"),
    "Elliptical": ("Cardio", "Machine", "cardio"),
    "Chest-Supported Row": ("Back", "Machine", "compound"),
    "Incline Chest Press": ("Chest", "Machine", "compound"),
    "Plate-Loaded Chest Press": ("Chest", "Machine", "compound"),
}

# What Sravan actually did each day (mapped to catalog names).
DAYS = {
    date(2026, 7, 12): ["Seated Cable Row", "Chest-Supported Row", "Lat Pulldown", "Chest Fly", "Treadmill"],
    date(2026, 7, 13): ["Seated Cable Row", "Chest-Supported Row", "Lat Pulldown", "Chest Fly", "Plate-Loaded Chest Press", "Treadmill"],
    date(2026, 7, 14): ["Seated Cable Row", "Chest-Supported Row", "Lat Pulldown", "Chest Fly", "Plate-Loaded Chest Press", "Treadmill"],
}


def get_or_create(db, model, name, **defaults):
    row = db.query(model).filter(model.name == name).first()
    if row is None:
        row = model(name=name, **defaults)
        db.add(row)
        db.flush()
    return row


def main() -> None:
    db = SessionLocal()
    try:
        # 1) Cardio section + missing exercises
        get_or_create(db, MuscleGroup, "Cardio")
        for name, (muscle, equipment, category) in EXERCISES.items():
            if db.query(Exercise).filter(Exercise.name == name).first():
                continue
            mg = db.query(MuscleGroup).filter(MuscleGroup.name == muscle).first()
            eq = db.query(Equipment).filter(Equipment.name == equipment).first()
            db.add(Exercise(
                name=name, category=category, is_custom=False,
                primary_muscle_group_id=mg.id if mg else None,
                equipment_id=eq.id if eq else None,
            ))
        db.commit()
        print("Catalog ready (Cardio + missing exercises).")

        # 2) Backfill Sravan's 3 days
        user = db.query(User).filter(User.email == EMAIL).first()
        if user is None:
            print(f"No user {EMAIL!r} — skipping backfill (register first).")
            return

        ex_by_name = {e.name: e for e in db.query(Exercise).all()}
        for day, names in DAYS.items():
            exists = (
                db.query(WorkoutSession)
                .filter(
                    WorkoutSession.user_id == user.id,
                    WorkoutSession.status == "completed",
                    func.date(WorkoutSession.completed_at) == day,
                )
                .first()
            )
            if exists is not None:
                print(f"  {day} already logged — skipping")
                continue

            ts = datetime(day.year, day.month, day.day, 18, 0, 0)
            session = WorkoutSession(
                user_id=user.id, name="Back & Chest",
                status="completed", started_at=ts, completed_at=ts,
            )
            db.add(session)
            db.flush()
            for i, exname in enumerate(names):
                se = SessionExercise(session_id=session.id, exercise_id=ex_by_name[exname].id, order_index=i)
                db.add(se)
                db.flush()
                db.add(SessionSet(session_exercise_id=se.id, set_number=1, is_completed=True))
            print(f"  logged {day} — {len(names)} exercises")

        db.commit()
        total = db.query(WorkoutSession).filter(
            WorkoutSession.user_id == user.id, WorkoutSession.status == "completed"
        ).count()
        print(f"Done. Completed sessions for {EMAIL}: {total}")
    finally:
        db.close()


if __name__ == "__main__":
    main()