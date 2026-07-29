import logging

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

_cache: dict[tuple, str] = {}


def generate_message(cache_key: tuple, prompt: str, fallback: str) -> str:
    """Ask Groq for a short message; always falls back to `fallback` if the
    AI is unset, unreachable, or returns something unusable.

    Cached by `cache_key` only (never per-user) — the wording only depends on
    whatever numbers went into the prompt, so identical inputs across
    different users/requests share one cached phrase instead of re-billing
    Groq's free tier for the same message over and over.
    """
    if not settings.groq_api_key:
        return fallback

    if cache_key in _cache:
        return _cache[cache_key]

    try:
        response = requests.post(
            GROQ_API_URL,
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            json={
                "model": settings.groq_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.9,
                "max_tokens": 30,
            },
            timeout=8,
        )
        response.raise_for_status()
        message = response.json()["choices"][0]["message"]["content"].strip()
    except (requests.RequestException, KeyError, IndexError):
        logger.exception("Groq call failed for cache_key=%s — using fallback", cache_key)
        return fallback

    _cache[cache_key] = message
    return message


def generate_streak_message(
    feature: str, current_streak: int, best_streak: int, total_days: int, fallback: str
) -> str:
    if total_days == 0:
        return fallback

    prompt = (
        f"Write ONE short, punchy, casual sentence (max 10 words) with exactly "
        f"ONE relevant emoji, in the style of a modern habit-tracker app like "
        f"Duolingo. Speak DIRECTLY to the user — address them as 'you'/'your', "
        f"never in the third person — encouraging them about their {feature} "
        f"habit tracking. Current streak: {current_streak} days. Best streak "
        f"ever: {best_streak} days. Total days tracked: {total_days}. No quotes, "
        f"no markdown, just the sentence."
    )
    cache_key = ("streak", feature, current_streak, best_streak, total_days)
    return generate_message(cache_key, prompt, fallback)


def generate_hydration_message(percentage_bucket: int, fallback: str) -> str:
    prompt = (
        f"Write ONE short, punchy, casual sentence (max 10 words) with exactly "
        f"ONE relevant emoji, in the style of a modern habit-tracker app like "
        f"Duolingo. Speak DIRECTLY to the user — address them as 'you'/'your', "
        f"never in the third person — about their water drinking progress "
        f"today. You are roughly at {percentage_bucket}% of your daily "
        f"hydration goal. Describe the level qualitatively — do not state the "
        f"percentage number itself. No quotes, no markdown, just the sentence."
    )
    cache_key = ("hydration", percentage_bucket)
    return generate_message(cache_key, prompt, fallback)