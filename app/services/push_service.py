import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pywebpush import webpush, WebPushException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.push_subscription import PushSubscription
from app.models.reminder_dispatch_log import ReminderDispatchLog
from app.schemas.push import PushSubscriptionRequest
from app.services.reminder_service import ReminderService

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
    def save_subscription(db: Session, request: PushSubscriptionRequest) -> PushSubscription:
        subscription = (
            db.query(PushSubscription)
            .filter(PushSubscription.endpoint == request.endpoint)
            .first()
        )

        if subscription is None:
            subscription = PushSubscription(endpoint=request.endpoint)
            db.add(subscription)

        subscription.p256dh = request.keys.p256dh
        subscription.auth = request.keys.auth

        db.commit()
        db.refresh(subscription)

        return subscription

    @staticmethod
    def send_to_all(db: Session, title: str, body: str) -> int:
        subscriptions = db.query(PushSubscription).all()

        payload = json.dumps({"title": title, "body": body})
        vapid_claims = {"sub": settings.vapid_subject}

        sent = 0

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
                if status in (404, 410):
                    db.delete(subscription)

        db.commit()
        return sent

    @staticmethod
    def dispatch_due(db: Session) -> dict:
        result = {"enabled": False, "sent": []}

        reminder = ReminderService.get_settings(db)
        if not reminder.notifications_enabled:
            return result

        result["enabled"] = True

        now = datetime.now(ZoneInfo(settings.reminder_timezone))
        today = now.date()
        now_time = now.time()

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

            already = (
                db.query(ReminderDispatchLog)
                .filter(
                    ReminderDispatchLog.sent_on == today,
                    ReminderDispatchLog.slot == slot,
                )
                .first()
            )
            if already is not None:
                continue

            # Record first (unique constraint is the real guard against a race
            # between two concurrent cron ticks), then send.
            db.add(ReminderDispatchLog(sent_on=today, slot=slot))
            db.commit()

            title, body = SLOT_MESSAGES[slot]
            count = PushService.send_to_all(db, title, body)
            result["sent"].append({"slot": slot, "subscriptions": count})

        return result