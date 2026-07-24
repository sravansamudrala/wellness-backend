"""Idempotent seed for the gym module's master data.

Seeds the 8 muscle-group categories and their exercises for the freestyle
"Log Workout" flow. Safe to re-run — every row is upserted by its unique name.

Run after the gym tables exist:  python -m app.seed.gym_seed
"""

from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.models.gym.exercise import Exercise, MuscleGroup


MUSCLE_GROUPS = [
    "Chest", "Back", "Shoulders", "Biceps", "Triceps", "Legs", "Core", "Cardio",
]

# name -> muscle group
EXERCISES = [
    # Chest
    ("Flat Barbell Bench Press", "Chest"),
    ("Incline Barbell Bench Press", "Chest"),
    ("Flat Dumbbell Press", "Chest"),
    ("Incline Dumbbell Press", "Chest"),
    ("Plate-Loaded Chest Press", "Chest"),
    ("Pec Deck (Chest Fly)", "Chest"),
    # Back
    ("Lat Pulldown", "Back"),
    ("Seated Cable Row", "Back"),
    ("Chest-Supported Row", "Back"),
    ("Straight-Arm Cable Pulldown", "Back"),
    # Shoulders
    ("Machine Shoulder Press", "Shoulders"),
    ("Dumbbell Overhead Press", "Shoulders"),
    ("Dumbbell Lateral Raise", "Shoulders"),
    ("Dumbbell Rear Delt Raise", "Shoulders"),
    ("Rear Delt Fly (Machine)", "Shoulders"),
    ("Face Pull", "Shoulders"),
    ("Barbell Shrug", "Shoulders"),
    # Biceps
    ("Standing EZ Bar Curl", "Biceps"),
    ("Dumbbell Bicep Curl", "Biceps"),
    ("Hammer Curl", "Biceps"),
    ("Cross-Body Hammer Curl", "Biceps"),
    ("EZ Bar Preacher Curl", "Biceps"),
    ("Standing Cable Bicep Curl (Straight Bar)", "Biceps"),
    # Triceps
    ("Cable Rope Pushdown", "Triceps"),
    ("Straight Bar Pushdown", "Triceps"),
    ("Overhead Cable Triceps Extension", "Triceps"),
    ("Overhead Dumbbell Triceps Extension", "Triceps"),
    ("Bench Dips", "Triceps"),
    ("Skull Crushers (EZ Bar)", "Triceps"),
    ("Close-Grip Bench Press", "Triceps"),
    # Legs
    ("Foam Roller Wall Squat", "Legs"),
    ("Static Lunge (Split Squat)", "Legs"),
    ("Leg Extension", "Legs"),
    ("Seated Leg Curl", "Legs"),
    ("Seated Calf Raise", "Legs"),
    # Core
    ("Plank", "Core"),
    ("Side Plank", "Core"),
    ("Dead Bug", "Core"),
    ("Bird Dog", "Core"),
    ("Bicycle Crunch", "Core"),
    ("Mountain Climbers", "Core"),
    ("Hanging Knee Raise", "Core"),
    ("Hanging Leg Raise", "Core"),
    ("Cable Crunch", "Core"),
    ("Russian Twist", "Core"),
    # Cardio
    ("Elliptical", "Cardio"),
    ("Treadmill", "Cardio"),
    ("Cycling", "Cardio"),
]


def _get_or_create_by_name(db: Session, model, name: str, **defaults):
    row = db.query(model).filter(model.name == name).first()
    if row is None:
        row = model(name=name, **defaults)
        db.add(row)
        db.flush()
    return row


def seed(db: Session) -> dict:
    # Muscle groups
    muscle_map = {}
    for name in MUSCLE_GROUPS:
        muscle_map[name] = _get_or_create_by_name(db, MuscleGroup, name)

    # Exercises
    exercise_map = {}
    for name, muscle in EXERCISES:
        row = db.query(Exercise).filter(Exercise.name == name).first()
        if row is None:
            row = Exercise(
                name=name,
                primary_muscle_group_id=muscle_map[muscle].id,
                is_custom=False,
            )
            db.add(row)
            db.flush()
        exercise_map[name] = row

    db.commit()

    return {
        "muscle_groups": len(muscle_map),
        "exercises": len(exercise_map),
    }


def main():
    db = SessionLocal()
    try:
        summary = seed(db)
        print("Gym seed complete:", summary)
    finally:
        db.close()


if __name__ == "__main__":
    main()
