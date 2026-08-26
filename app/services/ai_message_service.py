import logging
import re

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

    if not message:
        # Reasoning-model defaults (e.g. groq_model getting switched to one
        # later) can burn max_tokens on hidden reasoning and return empty
        # content with no error — treat that the same as a request failure.
        logger.warning("Groq returned empty content for cache_key=%s — using fallback", cache_key)
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


def generate_gym_coach_message(
    current_streak: int,
    this_week: int,
    total_workouts: int,
    trained_this_week: list,
    stalest_group: str | None,
    stalest_days: int | None,
    all_muscle_groups: list,
    fallback: str,
) -> str:
    if total_workouts == 0:
        return fallback

    facts = [
        f"Current streak: {current_streak} days",
        f"Workouts this week: {this_week}",
        f"Total workouts logged: {total_workouts}",
    ]
    if trained_this_week:
        facts.append("Trained recently: " + ", ".join(trained_this_week))
    if stalest_group is not None:
        facts.append(f"Needs attention: {stalest_group} ({stalest_days}d since trained)")
    facts_text = "; ".join(facts)

    prompt = (
        f"Write ONE short, punchy, casual sentence (max 18 words) with exactly "
        f"ONE relevant emoji, in the style of a modern fitness app like "
        f"Duolingo/Whoop. Speak DIRECTLY to the user — address them as "
        f"'you'/'your', never in the third person. Summarize their week using "
        f"ONLY these facts — do not invent numbers, muscle groups, or specific "
        f"timeframes (e.g. 'today', 'yesterday', a day of the week) that aren't "
        f"explicitly given below; 'trained recently' means sometime this week "
        f"(the current calendar week, starting Monday), not any particular day: "
        f"{facts_text}. No quotes, no markdown, just the sentence."
    )
    cache_key = ("gym_stats", current_streak, this_week, total_workouts, tuple(trained_this_week), stalest_group, stalest_days)
    message = generate_message(cache_key, prompt, fallback)

    # Small/fast models don't always obey "don't invent muscle groups" — verify
    # the response doesn't name a muscle group that wasn't actually given
    # (e.g. claiming "legs" were trained when only biceps data was passed in).
    # A wrong claim about what the user did is worse than a generic fallback.
    allowed = {g.lower() for g in trained_this_week}
    if stalest_group:
        allowed.add(stalest_group.lower())
    forbidden = {g for g in all_muscle_groups if g.lower() not in allowed}
    for group in forbidden:
        if re.search(rf"\b{re.escape(group)}\b", message, re.IGNORECASE):
            logger.warning(
                "Groq gym coach message mentioned unlisted muscle group %r — using fallback: %r",
                group,
                message,
            )
            return fallback

    # Same idea for numbers: a small/fast model can also invent a streak or
    # workout count even when the facts given are correct. Catches bare
    # digits and digit-ordinals ("5th") — spelled-out numbers ("five") are a
    # known, accepted gap (see deferred-work.md): two attempts at word
    # matching each introduced a worse bug (missed detection, then false
    # positives on compound numbers like "twenty-one"), so this stays
    # digit-only rather than chasing every English number phrasing.
    allowed_numbers = {str(current_streak), str(this_week), str(total_workouts)}
    if stalest_days is not None:
        allowed_numbers.add(str(stalest_days))
    for number in re.findall(r"\b(\d+)(?:st|nd|rd|th)?\b", message):
        if number not in allowed_numbers:
            logger.warning(
                "Groq gym coach message mentioned unmatched number %r — using fallback: %r",
                number,
                message,
            )
            return fallback

    return message


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
