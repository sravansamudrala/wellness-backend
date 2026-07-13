"""ONE-OFF: make all pre-auth data belong to a single account.

Before auth existed, every row had no owner (user_id IS NULL). The migration
adds the user_id columns; this script hands those legacy rows to your account.

It "adopts" the legacy data: for each user-owned table it first DELETES the
account's own rows (the empty defaults auto-created when you open the app, e.g.
gym_state / reminder_settings / today's skincare) and then reassigns the legacy
NULL rows to you. Doing it in that order avoids duplicate-key errors on the
per-user unique tables (gym_state, reminder_settings, skincare date).

workout_plans is intentionally left alone — its NULL rows are shared templates.
Safe to re-run (the second time there's nothing left to adopt). Delete after use.

Usage (repo root, venv active):
    python -m scripts.claim_legacy_data you@example.com
    python -m scripts.claim_legacy_data          # if there's exactly one user
"""

import sys

from app.database.session import SessionLocal
from app.models.gym.session import SessionExercise, SessionSet, WorkoutSession
from app.models.gym.state import GymState
from app.models.push_subscription import PushSubscription
from app.models.reminder_dispatch_log import ReminderDispatchLog
from app.models.reminder_settings import ReminderSettings
from app.models.skincare import SkincareEntry
from app.models.user import User

# All user-owned tables that get adopted (workout_plans excluded — templates).
OWNED_MODELS = [
    SkincareEntry,
    ReminderSettings,
    PushSubscription,
    ReminderDispatchLog,
    GymState,
    WorkoutSession,
]


def _clear_account_rows(db, uid) -> None:
    """Remove the account's own (default) rows so adopting can't collide."""
    # Gym session children first (sets -> exercises -> sessions).
    session_ids = [
        s.id for s in db.query(WorkoutSession).filter(WorkoutSession.user_id == uid).all()
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

    for model in OWNED_MODELS:
        db.query(model).filter(model.user_id == uid).delete(
            synchronize_session=False
        )


def main() -> None:
    email = sys.argv[1].strip().lower() if len(sys.argv) > 1 else None

    db = SessionLocal()
    try:
        if email:
            user = db.query(User).filter(User.email == email).first()
            if user is None:
                print(f"No user with email {email!r}. Register that account first.")
                return
        else:
            users = db.query(User).all()
            if len(users) != 1:
                print(
                    f"Expected exactly one user (found {len(users)}). "
                    "Pass the target email explicitly."
                )
                return
            user = users[0]

        print(f"Adopting legacy data for {user.email} ({user.id}):")

        # 1) Clear the account's own default rows so step 2 can't collide.
        _clear_account_rows(db, user.id)

        # 2) Reassign every orphaned (user_id IS NULL) row to this account.
        for model in OWNED_MODELS:
            adopted = (
                db.query(model)
                .filter(model.user_id.is_(None))
                .update({model.user_id: user.id}, synchronize_session=False)
            )
            print(f"  {model.__tablename__:22} adopted {adopted} rows")

        db.commit()
        print("Done.")
    finally:
        db.close()


if __name__ == "__main__":
    main()