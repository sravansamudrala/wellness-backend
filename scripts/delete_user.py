"""Delete a user and ALL data they own (no self-service account UI yet).

Deletes in foreign-key order (children first) so Postgres doesn't reject it.
Shared data (exercise catalog, seeded template plans with user_id IS NULL) is
NOT touched.

⚠️  This removes every row the user owns — including any legacy data they've
already CLAIMED. Don't delete an account that has claimed your real history; use
scripts.update_user to rename it instead.

Usage:
    python -m scripts.delete_user EMAIL
"""

import argparse

from app.database.session import SessionLocal
from app.models.gym.plan import PlanDay, PlanExercise, WorkoutPlan
from app.models.gym.session import SessionExercise, SessionSet, WorkoutSession
from app.models.gym.state import GymState
from app.models.push_subscription import PushSubscription
from app.models.reminder_dispatch_log import ReminderDispatchLog
from app.models.reminder_settings import ReminderSettings
from app.models.skincare import SkincareEntry
from app.models.user import User


def main() -> None:
    parser = argparse.ArgumentParser(description="Delete a user and their data.")
    parser.add_argument("email", help="the account's email")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        email = args.email.strip().lower()
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            print(f"No user found with email {email!r}.")
            return
        uid = user.id

        # 1) Gym sessions + their children (sets -> exercises -> sessions).
        session_ids = [
            s.id
            for s in db.query(WorkoutSession).filter(WorkoutSession.user_id == uid).all()
        ]
        if session_ids:
            se_ids = [
                se.id
                for se in db.query(SessionExercise)
                .filter(SessionExercise.session_id.in_(session_ids))
                .all()
            ]
            if se_ids:
                db.query(SessionSet).filter(
                    SessionSet.session_exercise_id.in_(se_ids)
                ).delete(synchronize_session=False)
            db.query(SessionExercise).filter(
                SessionExercise.session_id.in_(session_ids)
            ).delete(synchronize_session=False)
            db.query(WorkoutSession).filter(
                WorkoutSession.user_id == uid
            ).delete(synchronize_session=False)

        # 2) Gym cursor (references plans/days by FK, but nothing references it).
        db.query(GymState).filter(GymState.user_id == uid).delete(
            synchronize_session=False
        )

        # 3) The user's OWN custom plans + children (templates are user_id NULL → kept).
        plan_ids = [
            p.id
            for p in db.query(WorkoutPlan).filter(WorkoutPlan.user_id == uid).all()
        ]
        if plan_ids:
            day_ids = [
                d.id
                for d in db.query(PlanDay).filter(PlanDay.plan_id.in_(plan_ids)).all()
            ]
            if day_ids:
                db.query(PlanExercise).filter(
                    PlanExercise.plan_day_id.in_(day_ids)
                ).delete(synchronize_session=False)
            db.query(PlanDay).filter(PlanDay.plan_id.in_(plan_ids)).delete(
                synchronize_session=False
            )
            db.query(WorkoutPlan).filter(WorkoutPlan.id.in_(plan_ids)).delete(
                synchronize_session=False
            )

        # 4) Remaining user-owned rows.
        db.query(SkincareEntry).filter(SkincareEntry.user_id == uid).delete(
            synchronize_session=False
        )
        db.query(ReminderSettings).filter(ReminderSettings.user_id == uid).delete(
            synchronize_session=False
        )
        db.query(ReminderDispatchLog).filter(
            ReminderDispatchLog.user_id == uid
        ).delete(synchronize_session=False)
        db.query(PushSubscription).filter(PushSubscription.user_id == uid).delete(
            synchronize_session=False
        )

        # 5) Finally the user.
        db.query(User).filter(User.id == uid).delete(synchronize_session=False)

        db.commit()
        print(f"Deleted user {email!r} and all their owned data.")
    finally:
        db.close()


if __name__ == "__main__":
    main()