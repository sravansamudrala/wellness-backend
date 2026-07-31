import uuid
from datetime import date, datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.core.security import decode_token
from app.database.session import SessionLocal
from app.models.gym.exercise import Exercise, MuscleGroup
from app.models.gym.session import SessionExercise, SessionSet, WorkoutSession


def _create_exercise(client, auth_headers, name):
    response = client.post(
        "/api/v1/gym/exercises",
        json={"name": name},
        headers=auth_headers,
    )
    assert response.status_code == 200
    return response.json()["id"]


def _user_id(auth_headers):
    token = auth_headers["Authorization"].split(" ", 1)[1]
    return uuid.UUID(decode_token(token))


def test_create_exercise_is_idempotent_by_name(client, auth_headers):
    first = client.post(
        "/api/v1/gym/exercises",
        json={"name": "Barbell Row"},
        headers=auth_headers,
    )
    second = client.post(
        "/api/v1/gym/exercises",
        json={"name": "Barbell Row"},
        headers=auth_headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


def test_quick_log_merges_same_day_and_dedupes(client, auth_headers):
    exercise_id = _create_exercise(client, auth_headers, "Treadmill")

    first = client.post(
        "/api/v1/gym/sessions/quick-log",
        json={"exercise_ids": [exercise_id]},
        headers=auth_headers,
    )
    assert first.status_code == 200
    assert len(first.json()["exercises"]) == 1
    session_id = first.json()["id"]

    other_exercise_id = _create_exercise(client, auth_headers, "Elliptical")

    # Logging again same day, including the same exercise plus a new one:
    # should merge into the SAME session, and not duplicate the first exercise.
    second = client.post(
        "/api/v1/gym/sessions/quick-log",
        json={"exercise_ids": [exercise_id, other_exercise_id]},
        headers=auth_headers,
    )
    assert second.json()["id"] == session_id
    assert len(second.json()["exercises"]) == 2


def test_next_log_category_advances_past_all_touched_categories(client, auth_headers):
    """Regression test for the exact scenario that shaped this design: a single
    session touching two rotation categories at once (Back + Shoulders) must
    advance past BOTH of them, landing on Legs — not just past Back to Shoulders."""
    # The default rotation order — all 6 must exist as real MuscleGroup rows for
    # get_next_log_category's name lookup to resolve, even though this test only
    # logs exercises for two of them.
    rotation_names = ["Chest", "Biceps", "Back", "Shoulders", "Legs", "Triceps"]
    db = SessionLocal()
    try:
        for name in rotation_names:
            if not db.query(MuscleGroup).filter(MuscleGroup.name == name).first():
                db.add(MuscleGroup(name=name))
        db.commit()
        groups = {
            mg.name: mg.id
            for mg in db.query(MuscleGroup).filter(MuscleGroup.name.in_(rotation_names)).all()
        }
    finally:
        db.close()

    unique = uuid.uuid4()
    back_exercise = client.post(
        "/api/v1/gym/exercises",
        json={"name": f"Back Test {unique}", "muscle_group_id": str(groups["Back"])},
        headers=auth_headers,
    ).json()["id"]
    shoulders_exercise = client.post(
        "/api/v1/gym/exercises",
        json={"name": f"Shoulders Test {unique}", "muscle_group_id": str(groups["Shoulders"])},
        headers=auth_headers,
    ).json()["id"]

    # No session logged yet for this fresh user — default rotation starts at Chest.
    before = client.get("/api/v1/gym/log/next-category", headers=auth_headers)
    assert before.json()["muscle_group"]["name"] == "Chest"

    # Log a combined Back + Shoulders session (Back added first, per order_index).
    client.post(
        "/api/v1/gym/sessions/quick-log",
        json={"exercise_ids": [back_exercise, shoulders_exercise]},
        headers=auth_headers,
    )

    after = client.get("/api/v1/gym/log/next-category", headers=auth_headers)
    assert after.json()["muscle_group"]["name"] == "Legs"


def test_quick_log_merges_session_from_just_after_local_midnight(client, auth_headers, monkeypatch):
    """A session completed at 19:00 UTC (Jan 14) is 00:30 IST on Jan 15 — the
    same-day merge check must bucket it under today's LOCAL day, not the UTC
    calendar day, or quick_log would wrongly create a second session instead
    of merging into it."""
    fixed_local = datetime(2026, 1, 15, 0, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
    monkeypatch.setattr("app.core.timezone.local_now", lambda: fixed_local)
    # quick_log's merge window comes from local_day_bounds_utc(), which reads
    # settings.reminder_timezone directly — patching local_now alone isn't
    # enough, this must match the zone the scenario above is built around, or
    # the test only passes by accident of whatever REMINDER_TIMEZONE happens
    # to be set to in the current environment (it defaults to "UTC" in CI).
    monkeypatch.setattr(settings, "reminder_timezone", "Asia/Kolkata")

    user_id = _user_id(auth_headers)
    naive_utc_completed_at = datetime(2026, 1, 14, 19, 0)  # UTC Jan 14, but local Jan 15

    db = SessionLocal()
    try:
        session = WorkoutSession(
            user_id=user_id,
            name="Workout",
            status="completed",
            started_at=naive_utc_completed_at,
            completed_at=naive_utc_completed_at,
        )
        db.add(session)
        db.commit()
        session_id = session.id
    finally:
        db.close()

    exercise_id = _create_exercise(client, auth_headers, "Rowing Machine")
    response = client.post(
        "/api/v1/gym/sessions/quick-log",
        json={"exercise_ids": [exercise_id]},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(session_id)


def test_this_week_and_trained_this_week_exclude_workout_before_monday(client, auth_headers, monkeypatch):
    """A workout from before the current Monday must be excluded from both
    this_week and trained_this_week — they use the identical calendar-week
    window, not a rolling 7-day lookback."""
    import app.services.gym.insights_service as insights_module

    captured = {}

    def _capture_and_fallback(
        current_streak, this_week, total_workouts, trained_this_week,
        stalest_group, stalest_days, all_muscle_groups, fallback,
    ):
        captured["trained_this_week"] = trained_this_week
        return fallback

    monkeypatch.setattr(insights_module, "generate_gym_coach_message", _capture_and_fallback)

    user_id = _user_id(auth_headers)
    today = date.today()
    before_monday = today - timedelta(days=today.weekday() + 2)  # safely in last week

    db = SessionLocal()
    try:
        mg = db.query(MuscleGroup).filter(MuscleGroup.name == "Back").first()
        if mg is None:
            mg = MuscleGroup(name="Back")
            db.add(mg)
            db.commit()

        exercise = Exercise(
            name=f"Old Back Exercise {uuid.uuid4()}", primary_muscle_group_id=mg.id
        )
        db.add(exercise)
        db.commit()

        old_time = datetime.combine(before_monday, datetime.min.time())
        old_session = WorkoutSession(
            user_id=user_id,
            name="Back",
            status="completed",
            started_at=old_time,
            completed_at=old_time,
        )
        db.add(old_session)
        db.flush()
        se = SessionExercise(session_id=old_session.id, exercise_id=exercise.id, order_index=0)
        db.add(se)
        db.flush()
        db.add(SessionSet(session_exercise_id=se.id, set_number=1, is_completed=True))
        db.commit()
    finally:
        db.close()

    response = client.get("/api/v1/gym/insights/stats", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["this_week"] == 0
    assert captured["trained_this_week"] == []


def test_generate_gym_coach_message_falls_back_on_unmatched_bare_number(monkeypatch):
    from app.services.ai_message_service import generate_gym_coach_message
    import app.services.ai_message_service as ai_module

    monkeypatch.setattr(ai_module, "generate_message", lambda cache_key, prompt, fallback: "🔥 5-day streak, keep it up!")

    result = generate_gym_coach_message(
        current_streak=3, this_week=2, total_workouts=15,
        trained_this_week=["Back"], stalest_group=None, stalest_days=None,
        all_muscle_groups=["Back", "Chest"], fallback="FALLBACK",
    )

    assert result == "FALLBACK"


def test_generate_gym_coach_message_falls_back_on_unmatched_ordinal_number(monkeypatch):
    from app.services.ai_message_service import generate_gym_coach_message
    import app.services.ai_message_service as ai_module

    monkeypatch.setattr(ai_module, "generate_message", lambda cache_key, prompt, fallback: "🔥 your 5th workout milestone!")

    result = generate_gym_coach_message(
        current_streak=3, this_week=2, total_workouts=15,
        trained_this_week=["Back"], stalest_group=None, stalest_days=None,
        all_muscle_groups=["Back", "Chest"], fallback="FALLBACK",
    )

    assert result == "FALLBACK"
