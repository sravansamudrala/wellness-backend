import logging

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)

MODEL_NAME = "aiwt-v1"


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

    try:
        response = requests.post(
            f"{settings.aiwt_service_url}/v1/generate",
            json={
                "model": MODEL_NAME,
                "notification_type": "water",
                "context": {
                    "amount_ml": amount_ml,
                    "goal_ml": goal_ml,
                    "current_streak": current_streak,
                    "hour": hour,
                },
            },
            # Render's free tier cold-starts after inactivity (can take
            # ~30-60s to wake); generous timeout since this runs in a
            # background cron dispatch, not a user-facing request.
            timeout=45,
        )
        response.raise_for_status()
        return response.json().get("message")
    except (requests.RequestException, ValueError, KeyError):
        logger.exception(
            "wellness-aiwt call failed for goal_ml=%s current_streak=%s hour=%s — using static fallback",
            goal_ml,
            current_streak,
            hour,
        )
        return None
