"""Set (or clear) one muscle group's shared image_url by exact name.

One image is shared across every exercise in that group (e.g. one "Chest"
icon shown for all chest exercises) — not a per-exercise image.

Usage:
    python -m scripts.set_muscle_group_image Chest --url "https://sijnkvkwkybxqyokioff.supabase.co/storage/v1/object/public/exercise-images/chest.png"
"""

import argparse

from app.database.session import SessionLocal
from app.models.gym.exercise import MuscleGroup


def main() -> None:
    parser = argparse.ArgumentParser(description="Set a muscle group's shared image_url.")
    parser.add_argument("name", help="exact muscle group name, e.g. Chest")
    parser.add_argument("--url", required=True, help="public image URL")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        group = db.query(MuscleGroup).filter(MuscleGroup.name == args.name).first()
        if group is None:
            print(f"No muscle group found named {args.name!r}.")
            return

        group.image_url = args.url
        db.commit()
        print(f"{group.name} -> {group.image_url}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
