"""Idempotent seed for the gym module's master data.

Seeds muscle groups, equipment, a starter exercise catalog, and template workout
plans (PPL, Bro Split, Upper/Lower, Fat Loss, Muscle Gain). Safe to re-run — every
row is upserted by its unique name, and a plan is only built if it doesn't exist yet.

Run after the gym tables exist:  python -m app.seed.gym_seed
"""

from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.models.gym.exercise import Equipment, Exercise, MuscleGroup
from app.models.gym.plan import PlanDay, PlanExercise, WorkoutPlan


MUSCLE_GROUPS = [
    "Chest", "Back", "Shoulders", "Biceps", "Triceps",
    "Quads", "Hamstrings", "Glutes", "Calves", "Core", "Forearms",
]

EQUIPMENT = [
    "Barbell", "Dumbbell", "Machine", "Cable", "Bodyweight",
    "Kettlebell", "Smith Machine", "EZ Bar",
]

# name, primary muscle, equipment, category, difficulty
EXERCISES = [
    # Chest
    ("Barbell Bench Press", "Chest", "Barbell", "compound", "intermediate"),
    ("Incline Dumbbell Press", "Chest", "Dumbbell", "compound", "intermediate"),
    ("Chest Fly", "Chest", "Machine", "isolation", "beginner"),
    ("Push-Up", "Chest", "Bodyweight", "compound", "beginner"),
    # Back
    ("Deadlift", "Back", "Barbell", "compound", "advanced"),
    ("Pull-Up", "Back", "Bodyweight", "compound", "intermediate"),
    ("Barbell Row", "Back", "Barbell", "compound", "intermediate"),
    ("Lat Pulldown", "Back", "Cable", "compound", "beginner"),
    ("Seated Cable Row", "Back", "Cable", "compound", "beginner"),
    # Shoulders
    ("Overhead Press", "Shoulders", "Barbell", "compound", "intermediate"),
    ("Dumbbell Shoulder Press", "Shoulders", "Dumbbell", "compound", "beginner"),
    ("Lateral Raise", "Shoulders", "Dumbbell", "isolation", "beginner"),
    ("Face Pull", "Shoulders", "Cable", "isolation", "beginner"),
    # Biceps
    ("Barbell Curl", "Biceps", "Barbell", "isolation", "beginner"),
    ("Dumbbell Curl", "Biceps", "Dumbbell", "isolation", "beginner"),
    ("Hammer Curl", "Biceps", "Dumbbell", "isolation", "beginner"),
    # Triceps
    ("Tricep Pushdown", "Triceps", "Cable", "isolation", "beginner"),
    ("Skull Crusher", "Triceps", "EZ Bar", "isolation", "intermediate"),
    ("Close-Grip Bench Press", "Triceps", "Barbell", "compound", "intermediate"),
    ("Dip", "Triceps", "Bodyweight", "compound", "intermediate"),
    # Quads
    ("Barbell Squat", "Quads", "Barbell", "compound", "intermediate"),
    ("Leg Press", "Quads", "Machine", "compound", "beginner"),
    ("Leg Extension", "Quads", "Machine", "isolation", "beginner"),
    ("Lunge", "Quads", "Dumbbell", "compound", "beginner"),
    # Hamstrings
    ("Romanian Deadlift", "Hamstrings", "Barbell", "compound", "intermediate"),
    ("Leg Curl", "Hamstrings", "Machine", "isolation", "beginner"),
    # Glutes
    ("Hip Thrust", "Glutes", "Barbell", "compound", "intermediate"),
    # Calves
    ("Standing Calf Raise", "Calves", "Machine", "isolation", "beginner"),
    # Core
    ("Plank", "Core", "Bodyweight", "isolation", "beginner"),
    ("Hanging Leg Raise", "Core", "Bodyweight", "isolation", "intermediate"),
    ("Cable Crunch", "Core", "Cable", "isolation", "beginner"),
]

# Template plans. Each exercise entry: (exercise_name, target_sets, target_reps, rest_seconds)
PLANS = [
    {
        "name": "Push Pull Legs (PPL)",
        "goal": "muscle_gain",
        "description": "A 3-day rotation hitting pushing, pulling, and leg muscles separately.",
        "days": [
            ("Push", [
                ("Barbell Bench Press", 4, "6-8", 120),
                ("Overhead Press", 3, "8-10", 90),
                ("Incline Dumbbell Press", 3, "8-12", 90),
                ("Lateral Raise", 3, "12-15", 60),
                ("Tricep Pushdown", 3, "10-15", 60),
            ]),
            ("Pull", [
                ("Deadlift", 3, "5", 150),
                ("Pull-Up", 3, "6-10", 120),
                ("Barbell Row", 3, "8-10", 90),
                ("Face Pull", 3, "12-15", 60),
                ("Barbell Curl", 3, "10-12", 60),
            ]),
            ("Legs", [
                ("Barbell Squat", 4, "6-8", 150),
                ("Romanian Deadlift", 3, "8-10", 120),
                ("Leg Press", 3, "10-12", 90),
                ("Leg Curl", 3, "12-15", 60),
                ("Standing Calf Raise", 4, "12-15", 45),
            ]),
        ],
    },
    {
        "name": "Bro Split",
        "goal": "muscle_gain",
        "description": "A 5-day split with one muscle group focus per day.",
        "days": [
            ("Chest", [
                ("Barbell Bench Press", 4, "8-10", 120),
                ("Incline Dumbbell Press", 3, "8-12", 90),
                ("Chest Fly", 3, "12-15", 60),
                ("Push-Up", 2, "AMRAP", 60),
            ]),
            ("Back", [
                ("Barbell Row", 4, "8-10", 120),
                ("Lat Pulldown", 3, "10-12", 90),
                ("Seated Cable Row", 3, "10-12", 90),
                ("Pull-Up", 2, "AMRAP", 90),
            ]),
            ("Shoulders", [
                ("Overhead Press", 4, "8-10", 120),
                ("Dumbbell Shoulder Press", 3, "10-12", 90),
                ("Lateral Raise", 4, "12-15", 60),
                ("Face Pull", 3, "15-20", 60),
            ]),
            ("Arms", [
                ("Barbell Curl", 4, "8-12", 75),
                ("Skull Crusher", 4, "8-12", 75),
                ("Hammer Curl", 3, "10-12", 60),
                ("Tricep Pushdown", 3, "12-15", 60),
            ]),
            ("Legs", [
                ("Barbell Squat", 4, "8-10", 150),
                ("Leg Press", 3, "10-12", 90),
                ("Leg Curl", 3, "12-15", 60),
                ("Standing Calf Raise", 4, "15-20", 45),
            ]),
        ],
    },
    {
        "name": "Upper / Lower",
        "goal": "strength",
        "description": "A 2-day rotation alternating upper- and lower-body sessions.",
        "days": [
            ("Upper", [
                ("Barbell Bench Press", 4, "6-8", 120),
                ("Barbell Row", 4, "6-8", 120),
                ("Overhead Press", 3, "8-10", 90),
                ("Lat Pulldown", 3, "10-12", 90),
                ("Barbell Curl", 3, "10-12", 60),
                ("Tricep Pushdown", 3, "10-12", 60),
            ]),
            ("Lower", [
                ("Barbell Squat", 4, "6-8", 150),
                ("Romanian Deadlift", 3, "8-10", 120),
                ("Leg Press", 3, "10-12", 90),
                ("Leg Curl", 3, "12-15", 60),
                ("Standing Calf Raise", 4, "12-15", 45),
                ("Plank", 3, "60s", 45),
            ]),
        ],
    },
    {
        "name": "Fat Loss",
        "goal": "fat_loss",
        "description": "Full-body circuits with short rest to keep the heart rate up.",
        "days": [
            ("Full Body A", [
                ("Barbell Squat", 3, "12-15", 45),
                ("Push-Up", 3, "15-20", 45),
                ("Seated Cable Row", 3, "12-15", 45),
                ("Lunge", 3, "12-15", 45),
                ("Plank", 3, "45s", 30),
            ]),
            ("Full Body B", [
                ("Romanian Deadlift", 3, "12-15", 45),
                ("Dumbbell Shoulder Press", 3, "12-15", 45),
                ("Lat Pulldown", 3, "12-15", 45),
                ("Hip Thrust", 3, "12-15", 45),
                ("Hanging Leg Raise", 3, "12-15", 30),
            ]),
        ],
    },
    {
        "name": "Muscle Gain",
        "goal": "muscle_gain",
        "description": "A 4-day upper/lower hypertrophy plan with higher volume.",
        "days": [
            ("Upper Power", [
                ("Barbell Bench Press", 4, "6-8", 120),
                ("Barbell Row", 4, "6-8", 120),
                ("Overhead Press", 3, "8-10", 90),
                ("Pull-Up", 3, "8-10", 90),
            ]),
            ("Lower Power", [
                ("Barbell Squat", 4, "6-8", 150),
                ("Romanian Deadlift", 3, "8-10", 120),
                ("Leg Press", 3, "10-12", 90),
                ("Standing Calf Raise", 4, "12-15", 45),
            ]),
            ("Upper Hypertrophy", [
                ("Incline Dumbbell Press", 4, "10-12", 75),
                ("Seated Cable Row", 4, "10-12", 75),
                ("Lateral Raise", 4, "12-15", 60),
                ("Barbell Curl", 3, "10-12", 60),
                ("Tricep Pushdown", 3, "12-15", 60),
            ]),
            ("Lower Hypertrophy", [
                ("Leg Press", 4, "12-15", 75),
                ("Leg Curl", 4, "12-15", 60),
                ("Hip Thrust", 3, "10-12", 75),
                ("Cable Crunch", 3, "12-15", 45),
            ]),
        ],
    },
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

    # Equipment
    equipment_map = {}
    for name in EQUIPMENT:
        equipment_map[name] = _get_or_create_by_name(db, Equipment, name)

    # Exercises
    exercise_map = {}
    for name, muscle, equipment, category, difficulty in EXERCISES:
        row = db.query(Exercise).filter(Exercise.name == name).first()
        if row is None:
            row = Exercise(
                name=name,
                category=category,
                difficulty=difficulty,
                primary_muscle_group_id=muscle_map[muscle].id,
                equipment_id=equipment_map[equipment].id,
                is_custom=False,
            )
            db.add(row)
            db.flush()
        exercise_map[name] = row

    # Template plans (skipped if a plan of the same name already exists)
    plans_created = 0
    for plan_def in PLANS:
        existing = (
            db.query(WorkoutPlan)
            .filter(WorkoutPlan.name == plan_def["name"])
            .first()
        )
        if existing is not None:
            continue

        plan = WorkoutPlan(
            name=plan_def["name"],
            description=plan_def["description"],
            goal=plan_def["goal"],
            is_custom=False,
        )
        db.add(plan)
        db.flush()

        for day_index, (day_name, exercises) in enumerate(plan_def["days"]):
            plan_day = PlanDay(
                plan_id=plan.id,
                name=day_name,
                order_index=day_index,
            )
            db.add(plan_day)
            db.flush()

            for ex_index, (ex_name, sets, reps, rest) in enumerate(exercises):
                db.add(
                    PlanExercise(
                        plan_day_id=plan_day.id,
                        exercise_id=exercise_map[ex_name].id,
                        order_index=ex_index,
                        target_sets=sets,
                        target_reps=reps,
                        target_rest_seconds=rest,
                    )
                )
        plans_created += 1

    db.commit()

    return {
        "muscle_groups": len(muscle_map),
        "equipment": len(equipment_map),
        "exercises": len(exercise_map),
        "plans_created": plans_created,
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