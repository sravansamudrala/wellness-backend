import base64
import io
import json
import logging
from typing import Optional, Tuple

import requests
from PIL import Image, UnidentifiedImageError

from app.core.config import settings

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

MAX_DIMENSION = 1024

PROMPT = (
    "You are a nutrition estimation assistant. Look at this photo of food and "
    "identify each distinct food item visible. For each item, estimate a "
    "realistic serving size and its nutrition. Respond with ONLY a JSON object "
    "in this exact shape, no other text: "
    '{"items": [{"name": string, "quantity": string (e.g. "1 bowl", "250g"), '
    '"calories": integer, "protein_g": number, "carbs_g": number, "fat_g": number}]}. '
    'If you can\'t identify any food, respond with {"items": []}.'
)


def _resize_image(image_bytes: bytes) -> bytes:
    """Downscale + re-encode as JPEG so the base64 payload stays well under
    Groq's 4MB-per-image limit — phone photos routinely exceed that raw."""
    image = Image.open(io.BytesIO(image_bytes))
    image = image.convert("RGB")
    image.thumbnail((MAX_DIMENSION, MAX_DIMENSION))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def analyze_photo(image_bytes: bytes) -> Tuple[Optional[list[dict]], Optional[str]]:
    """Ask Groq's vision model to identify food items and estimate calories.

    Unlike ai_message_service's text-only calls, there's no sensible fallback
    here — a wrong calorie guess is worse than a clear error telling the user
    to log manually, so failures are surfaced rather than papered over.
    """
    if not settings.groq_api_key:
        return None, "AI photo analysis is not configured."

    try:
        resized = _resize_image(image_bytes)
    except UnidentifiedImageError:
        return None, "That doesn't look like a valid image."

    b64_image = base64.b64encode(resized).decode("utf-8")

    try:
        response = requests.post(
            GROQ_API_URL,
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            json={
                "model": settings.groq_vision_model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"},
                            },
                        ],
                    }
                ],
                "response_format": {"type": "json_object"},
                # qwen3.6-27b is a hybrid reasoning model — without this it
                # wraps the reply in a <think>...</think> block first, which
                # both wastes tokens and breaks the plain json.loads() below.
                "reasoning_effort": "none",
                "temperature": 0.2,
                "max_tokens": 1024,
            },
            timeout=20,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    except (requests.RequestException, KeyError, IndexError):
        logger.exception("Groq vision call failed for food photo analysis")
        return None, "Couldn't reach the AI service — try again or log manually."

    try:
        items = json.loads(content)["items"]
        for item in items:
            item["name"] = str(item["name"])
            item["quantity"] = str(item["quantity"])
            item["calories"] = int(item["calories"])
            item["protein_g"] = float(item["protein_g"]) if item.get("protein_g") is not None else None
            item["carbs_g"] = float(item["carbs_g"]) if item.get("carbs_g") is not None else None
            item["fat_g"] = float(item["fat_g"]) if item.get("fat_g") is not None else None
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        logger.exception("Groq vision response was unparseable: %r", content)
        return None, "Couldn't read that photo — try again or log manually."

    return items, None