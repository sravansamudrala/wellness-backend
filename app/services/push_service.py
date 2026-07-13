import json
from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from pywebpush import webpush, WebPushException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.push_subscription import PushSubscription
from app.models.reminder_dispatch_log import ReminderDispatchLog
from app.models.reminder_settings import ReminderSettings
from app.schemas.push import PushSubscriptionRequest

# How long after a reminder time we'll still send it (guards against a late or
# missed cron tick without firing hours later).
GRACE_MINUTES = 60

# Per-slot notification copy.
SLOT_MESSAGES = {
    "morning": ("🧴 Morning skincare", "Time for your morning routine!"),
    "evening": ("🌙 Evening skincare", "Time to wind down — evening routine!"),
}


class PushService:

    @staticmethod
    def save_subscription(
        db: Session, user_id: UUID, request: PushSubscriptionRequest
    ) -> PushSubscription:
        subscription = (
            db.query(PushSubscription)
            .filter(PushSubscription.endpoint == request.endpoint)
            .first()
        )

        if subscription is None:
            subscription = PushSubscription(endpoint=request.endpoint)
            db.add(subscription)

        # Attach (or re-attach) this device to the current user.
        subscription.user_id = user_id
        subscription.p256dh = request.keys.p256dh
        subscription.auth = request.keys.auth

        db.commit()
        db.refresh(subscription)

        return subscription

    @staticmethod
    def send_to_user(db: Session, user_id: UUID, title: str, body: str):
        """Push to all of ONE user's devices. Returns (sent_count, errors)."""
        subscriptions = (
            db.query(PushSubscription)
            .filter(PushSubscription.user_id == user_id)
            .all()
        )

        payload = json.dumps({"title": title, "body": body})
        vapid_claims = {"sub": settings.vapid_subject}

        sent = 0
        errors = []

        for subscription in subscriptions:
            try:
                webpush(
                    subscription_info={
                        "endpoint": subscription.endpoint,
                        "keys": {
                            "p256dh": subscription.p256dh,
                            "auth": subscription.auth,
                        },
                    },
                    data=payload,
                    vapid_private_key=settings.vapid_private_key,
                    vapid_claims=dict(vapid_claims),
                )
                sent += 1
            except WebPushException as exc:
                # 404/410 mean the subscription is dead — drop it.
                status = getattr(exc.response, "status_code", None)
                detail = exc.response.text[:200] if exc.response is not None else str(exc)
                errors.append({"type": "WebPushException", "status": status, "detail": detail})
                if status in (404, 410):
                    db.delete(subscription)
            except Exception as exc:
                # Bad VAPID key, encryption error, etc. — isolate the failure
                # so one bad subscription can't 500 the whole dispatch.
                errors.append({"type": type(exc).__name__, "detail": str(exc)[:200]})

        db.commit()
        return sent, errors

    @staticmethod
    def dispatch_due(db: Session) -> dict:
        """Cron entry point. For every user with notifications enabled, send any
        slot that's due now (and not already sent today for that user)."""
        result = {"processed_users": 0, "sent": [], "errors": []}

        now = datetime.now(ZoneInfo(settings.reminder_timezone))
        today = now.date()
        now_time = now.time()

        # Every user who has reminders turned on (multi-user: was one global row).
        reminder_rows = (
            db.query(ReminderSettings)
            .filter(
                ReminderSettings.notifications_enabled.is_(True),
                ReminderSettings.user_id.isnot(None),
            )
            .all()
        )

        for reminder in reminder_rows:
            result["processed_users"] += 1
            user_id = reminder.user_id

            slots = {
                "morning": reminder.morning_time,
                "evening": reminder.evening_time,
            }

            for slot, reminder_time in slots.items():
                # Due only once we're past the reminder time and still within the
                # grace window after it.
                if now_time < reminder_time:
                    continue

                reminder_dt = datetime.combine(today, reminder_time)
                if now.replace(tzinfo=None) - reminder_dt > timedelta(minutes=GRACE_MINUTES):
                    continue

                # Per-user dedup: one notification per (user, day, slot).
                already = (
                    db.query(ReminderDispatchLog)
                    .filter(
                        ReminderDispatchLog.user_id == user_id,
                        ReminderDispatchLog.sent_on == today,
                        ReminderDispatchLog.slot == slot,
                    )
                    .first()
                )
                if already is not None:
                    continue

                # Send first, then record the dedup log only if at least one push
                # was accepted — so a transient failure doesn't consume the slot.
                title, body = SLOT_MESSAGES[slot]
                count, errs = PushService.send_to_user(db, user_id, title, body)
                result["errors"].extend(errs)

                if count > 0:
                    db.add(ReminderDispatchLog(user_id=user_id, sent_on=today, slot=slot))
                    db.commit()

                result["sent"].append(
                    {"user_id": str(user_id), "slot": slot, "subscriptions": count}
                )

        return result