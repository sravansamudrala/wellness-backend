import json
from datetime import datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo
from pywebpush import webpush, WebPushException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.timezone import local_today
from app.models.electricity import Meter, MeterShare
from app.models.feature_flag import FeatureFlag
from app.models.push_subscription import PushSubscription
from app.models.reminder_dispatch_log import ReminderDispatchLog
from app.models.reminder_settings import ReminderSettings
from app.models.water import WaterEntry, WaterSettings
from app.schemas.push import PushSubscriptionRequest
from app.services.meter_slab_recommendation_service import evaluate_switch_recommendation
import logging

logger = logging.getLogger(__name__)

# How long after a reminder time we'll still send it (guards against a late or
# missed cron tick without firing hours later).
GRACE_MINUTES = 60

# Per-slot notification copy.
SLOT_MESSAGES = {
    "morning": ("🧴 Morning skincare", "Time for your morning routine!"),
    "evening": ("🌙 Evening skincare", "Time to wind down — evening routine!"),
}

WATER_MESSAGE = ("💧 Hydration check", "Time to drink some water!")

METER_SLAB_MESSAGE = (
    "⚡ Consider switching meters",
    "Your usage is approaching the next slab. Switching your active meter may help keep one meter within the lower usage slab.",
)


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
                logger.warning("Push failed for subscription %s: %s (status %s)", subscription.id, detail, status)
                if status in (404, 410):
                    logger.info("Dropping dead subscription %s (status %s)", subscription.id, status)
                    db.delete(subscription)
            except Exception as exc:
                # Bad VAPID key, encryption error, etc. — isolate the failure
                # so one bad subscription can't 500 the whole dispatch.
                errors.append({"type": type(exc).__name__, "detail": str(exc)[:200]})
                logger.error("Unexpected push failure for subscription %s: %s", subscription.id, exc, exc_info=True)


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
        logger.info(
            "Push dispatch: %d users processed, %d notifications sent, %d errors",
            result["processed_users"],
            len(result["sent"]),
            len(result["errors"]),
        )
        return result

    @staticmethod
    def dispatch_water_due(db: Session) -> dict:
        """Cron entry point. For every user with hourly water reminders enabled,
        send once per hour within their configured window — skipping a user who
        already hit today's goal, and deduping via the same dispatch log keyed
        by an hour-specific slot (e.g. "water_14")."""
        result = {"processed_users": 0, "sent": [], "errors": []}

        now = datetime.now(ZoneInfo(settings.reminder_timezone))
        today = now.date()
        now_naive = now.replace(tzinfo=None)

        water_settings_rows = (
            db.query(WaterSettings)
            .filter(WaterSettings.reminders_enabled.is_(True))
            .all()
        )

        for water_settings in water_settings_rows:
            result["processed_users"] += 1
            user_id = water_settings.user_id

            # Skip once today's goal is already met.
            entry = (
                db.query(WaterEntry)
                .filter(WaterEntry.user_id == user_id, WaterEntry.date == today)
                .first()
            )
            if entry is not None and entry.amount_ml >= water_settings.daily_goal_ml:
                continue

            start_hour = water_settings.reminder_start_time.hour
            end_hour = water_settings.reminder_end_time.hour

            for hour in range(start_hour, end_hour + 1):
                reminder_dt = datetime.combine(today, time(hour, 0))

                # Due only once we're past the hour mark and still within the
                # grace window after it.
                if now_naive < reminder_dt:
                    continue
                if now_naive - reminder_dt > timedelta(minutes=GRACE_MINUTES):
                    continue

                slot = f"water_{hour:02d}"

                # Per-user dedup: one notification per (user, day, hour).
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

                title, body = WATER_MESSAGE
                count, errs = PushService.send_to_user(db, user_id, title, body)
                result["errors"].extend(errs)

                if count > 0:
                    db.add(ReminderDispatchLog(user_id=user_id, sent_on=today, slot=slot))
                    db.commit()

                result["sent"].append(
                    {"user_id": str(user_id), "slot": slot, "subscriptions": count}
                )

        logger.info(
            "Water push dispatch: %d users processed, %d notifications sent, %d errors",
            result["processed_users"],
            len(result["sent"]),
            len(result["errors"]),
        )
        return result

    @staticmethod
    def dispatch_meter_slab_recommendation(db: Session) -> dict:
        """Cron entry point. For every user who owns or has shared access to
        at least one meter, re-evaluate the smart meter-slab-switch
        recommendation fresh (no cached state) and send it once per
        recipient per calendar day. Independent of skincare/water dispatch."""
        result = {"processed_users": 0, "sent": [], "errors": []}

        today = local_today()

        owner_ids = {row.user_id for row in db.query(Meter.user_id).distinct()}
        shared_ids = {
            row.shared_with_user_id
            for row in db.query(MeterShare.shared_with_user_id).distinct()
        }
        candidate_ids = owner_ids | shared_ids

        for user_id in candidate_ids:
            result["processed_users"] += 1

            flag = (
                db.query(FeatureFlag)
                .filter(
                    FeatureFlag.user_id == user_id,
                    FeatureFlag.feature_key == "electricity_tracker",
                    FeatureFlag.enabled.is_(True),
                )
                .first()
            )
            if flag is None:
                continue

            try:
                recommendation = evaluate_switch_recommendation(db, user_id, today)
                if recommendation is None:
                    continue

                active_meter = (
                    db.query(Meter).filter(Meter.id == recommendation.active_meter_id).first()
                )
                slot = f"meter_slab_recommendation_{active_meter.last_billed_reading_id}"

                # Per-recipient dedup: one notification per (user, day, slot).
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

                title, body = METER_SLAB_MESSAGE
                count, errs = PushService.send_to_user(db, user_id, title, body)
                result["errors"].extend(errs)

                if count > 0:
                    try:
                        db.add(ReminderDispatchLog(user_id=user_id, sent_on=today, slot=slot))
                        db.commit()
                    except IntegrityError:
                        # Another concurrent dispatch run already logged this
                        # slot for today — treat as an already-sent no-op.
                        db.rollback()

                result["sent"].append(
                    {"user_id": str(user_id), "slot": slot, "subscriptions": count}
                )
            except Exception as exc:
                db.rollback()
                result["errors"].append(
                    {"type": type(exc).__name__, "user_id": str(user_id), "detail": str(exc)[:200]}
                )

        logger.info(
            "Meter-slab-recommendation dispatch: %d users processed, %d notifications sent, %d errors",
            result["processed_users"],
            len(result["sent"]),
            len(result["errors"]),
        )
        return result