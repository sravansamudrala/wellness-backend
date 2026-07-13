"""Update a user's email and/or password (no self-service account UI yet).

Run locally from the repo root with the venv active. The new password is bcrypt-
hashed via the same helper registration uses — plaintext is never stored.

Usage:
    python -m scripts.update_user CURRENT_EMAIL --email NEW_EMAIL
    python -m scripts.update_user CURRENT_EMAIL --password NEW_PASSWORD
    python -m scripts.update_user CURRENT_EMAIL --email NEW_EMAIL --password NEW_PASSWORD
"""

import argparse

from app.core.security import hash_password
from app.database.session import SessionLocal
from app.models.user import User


def main() -> None:
    parser = argparse.ArgumentParser(description="Update a user's email/password.")
    parser.add_argument("current_email", help="the account's current email")
    parser.add_argument("--email", help="new email")
    parser.add_argument("--password", help="new password (min 8 chars)")
    args = parser.parse_args()

    if not args.email and not args.password:
        print("Nothing to do — pass --email and/or --password.")
        return

    db = SessionLocal()
    try:
        current = args.current_email.strip().lower()
        user = db.query(User).filter(User.email == current).first()
        if user is None:
            print(f"No user found with email {current!r}.")
            return

        if args.email:
            new_email = args.email.strip().lower()
            clash = db.query(User).filter(User.email == new_email).first()
            if clash is not None and clash.id != user.id:
                print(f"Email {new_email!r} is already taken.")
                return
            user.email = new_email
            print(f"  email    -> {new_email}")

        if args.password:
            if len(args.password) < 8:
                print("Password must be at least 8 characters.")
                return
            user.hashed_password = hash_password(args.password)
            print("  password -> updated")

        db.commit()
        print("Done. Log in with the new credentials.")
    finally:
        db.close()


if __name__ == "__main__":
    main()