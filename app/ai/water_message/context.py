"""Buckets raw water/streak/time data into the context labels the Aiwt
water-message model was trained on. Mirrors wellness-ml's
src/water_message/schema.py - the two repos don't share code, so any change
to the bucket definitions there must be copied here too (see
artifacts/aiwt-v1/metadata.json for the pinned input format this must match).
"""


def bucket_goal_pct(amount_ml: int, goal_ml: int) -> str:
    pct = 0 if goal_ml <= 0 else (amount_ml / goal_ml) * 100
    if pct < 25:
        return "0-25"
    if pct < 50:
        return "25-50"
    if pct < 75:
        return "50-75"
    return "75-99"


def bucket_streak(current_streak: int) -> str:
    if current_streak <= 0:
        return "none"
    if current_streak <= 2:
        return "building"
    if current_streak <= 6:
        return "solid"
    return "strong"


def bucket_time_of_day(hour: int) -> str:
    if 6 <= hour <= 11:
        return "morning"
    if 12 <= hour <= 14:
        return "midday"
    if 15 <= hour <= 17:
        return "afternoon"
    if 18 <= hour <= 21:
        return "evening"
    return "late"


def build_input_text(amount_ml: int, goal_ml: int, current_streak: int, hour: int) -> str:
    goal_bucket = bucket_goal_pct(amount_ml, goal_ml)
    streak_bucket = bucket_streak(current_streak)
    time_bucket = bucket_time_of_day(hour)
    return f"water reminder | goal: {goal_bucket}% | streak: {streak_bucket} | time: {time_bucket}"
