import logging
import time

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)

MODEL_NAME = "aiwt-v1"

# Render's free tier spins wellness-aiwt down after 15min idle; the front
# proxy returns 429 for a brief window while a spun-down instance wakes
# back up (observed: resolves on its own within a few seconds), so retry
# a couple times on 429 specifically before giving up.
MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 3


def generate_water_message(amount_ml: int, goal_ml: int, current_streak: int, hour: int) -> str | None:
    """Calls the standalone wellness-aiwt service (github.com/
    sravansamudrala/wellness-aiwt) for a personalized water-reminder
    message. Sends raw values, not pre-bucketed strings - the service's
    own contexts/water.py does the bucketing, so it doesn't need
    duplicating here.

    Returns None if the service URL is unset, unreachable, or returns no
    usable message (e.g. every generation attempt failed guardrails on
    the service side) - caller should fall back to its own static
    message, same contract as ai_message_service.generate_message."""
    if not settings.aiwt_service_url:
        return None

    payload = {
        "model": MODEL_NAME,
        "notification_type": "water",
        "context": {
            "amount_ml": amount_ml,
            "goal_ml": goal_ml,
            "current_streak": current_streak,
            "hour": hour,
        },
    }

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = requests.post(
                f"{settings.aiwt_service_url}/v1/generate",
                json=payload,
                # Render's free tier cold-starts after inactivity (can take
                # ~30-60s to wake); generous timeout since this runs in a
                # background cron dispatch, not a user-facing request.
                timeout=45,
            )
            response.raise_for_status()
            return response.json().get("message")
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 429 and attempt < MAX_ATTEMPTS:
                logger.warning(
                    "wellness-aiwt 429 (attempt %d/%d) for goal_ml=%s current_streak=%s hour=%s — retrying",
                    attempt,
                    MAX_ATTEMPTS,
                    goal_ml,
                    current_streak,
                    hour,
                )
                time.sleep(RETRY_DELAY_SECONDS)
                continue
            logger.exception(
                "wellness-aiwt call failed for goal_ml=%s current_streak=%s hour=%s — using static fallback",
                goal_ml,
                current_streak,
                hour,
            )
            return None
        except (requests.RequestException, ValueError, KeyError):
            logger.exception(
                "wellness-aiwt call failed for goal_ml=%s current_streak=%s hour=%s — using static fallback",
                goal_ml,
                current_streak,
                hour,
            )
            return None

    return None
