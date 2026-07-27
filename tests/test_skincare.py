import uuid
from datetime import date, timedelta
from uuid import UUID

from app.core.security import decode_token
from app.database.session import SessionLocal
from app.models.skincare import SkincareEntry, SkincareEntryHabit


def _user_id(auth_headers) -> UUID:
    token = auth_headers["Authorization"].split(" ", 1)[1]
    return UUID(decode_token(token))


def _create_habits(client, auth_headers, names):
    response = client.put(
        "/api/v1/skincare/habits",
        json={
            "habits": [
                {"name": name, "is_active": True, "sort_order": index}
                for index, name in enumerate(names)
            ]
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    return response.json()


def _insert_backdated_entry(db, user_id, day, completions):
    """completions: dict[habit_id (UUID) -> completed (bool)]. Bypasses the
    API since it only ever reads/writes "today" — direct ORM inserts are how
    we get historical data on the board for get_history/get_stats tests."""
    entry = SkincareEntry(user_id=user_id, date=day)
    db.add(entry)
    db.flush()
    for habit_id, completed in completions.items():
        db.add(SkincareEntryHabit(entry_id=entry.id, habit_id=habit_id, completed=completed))
    db.commit()
    return entry


def test_list_habits_starts_empty(client, auth_headers):
    response = client.get("/api/v1/skincare/habits", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == []


def test_upsert_habits_creates_new_habits(client, auth_headers):
    habits = _create_habits(client, auth_headers, ["Face Wash", "Sunscreen"])

    assert {h["name"] for h in habits} == {"Face Wash", "Sunscreen"}
    assert all(h["is_active"] for h in habits)


def test_upsert_habits_updates_by_id_and_leaves_untouched_habits_alone(client, auth_headers):
    habits = _create_habits(client, auth_headers, ["Face Wash", "Sunscreen"])
    face_wash = next(h for h in habits if h["name"] == "Face Wash")
    sunscreen = next(h for h in habits if h["name"] == "Sunscreen")

    response = client.put(
        "/api/v1/skincare/habits",
        json={
            "habits": [
                {"id": face_wash["id"], "name": "Face Wash AM", "is_active": False, "sort_order": 0},
            ]
        },
        headers=auth_headers,
    )
    assert response.status_code == 200

    updated = {h["id"]: h for h in client.get("/api/v1/skincare/habits", headers=auth_headers).json()}

    assert updated[face_wash["id"]]["name"] == "Face Wash AM"
    assert updated[face_wash["id"]]["is_active"] is False

    # Sunscreen was never mentioned in that PUT — must be completely untouched.
    assert updated[sunscreen["id"]]["name"] == "Sunscreen"
    assert updated[sunscreen["id"]]["is_active"] is True


def test_upsert_habits_rejects_duplicate_name_in_payload(client, auth_headers):
    response = client.put(
        "/api/v1/skincare/habits",
        json={
            "habits": [
                {"name": "Face Wash", "is_active": True, "sort_order": 0},
                {"name": "Face Wash", "is_active": True, "sort_order": 1},
            ]
        },
        headers=auth_headers,
    )
    assert response.status_code == 400


def test_upsert_habits_rejects_name_reused_from_disabled_habit(client, auth_headers):
    habits = _create_habits(client, auth_headers, ["Face Wash"])
    face_wash = habits[0]

    disable = client.put(
        "/api/v1/skincare/habits",
        json={"habits": [{"id": face_wash["id"], "name": "Face Wash", "is_active": False, "sort_order": 0}]},
        headers=auth_headers,
    )
    assert disable.status_code == 200

    reuse = client.put(
        "/api/v1/skincare/habits",
        json={"habits": [{"name": "Face Wash", "is_active": True, "sort_order": 1}]},
        headers=auth_headers,
    )
    assert reuse.status_code == 400


def test_get_today_creates_entry_habits_for_every_active_habit(client, auth_headers):
    _create_habits(client, auth_headers, ["Face Wash", "Sunscreen"])

    response = client.get("/api/v1/skincare/today", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert {h["name"] for h in body["habits"]} == {"Face Wash", "Sunscreen"}
    assert all(h["completed"] is False for h in body["habits"])


def test_get_today_adds_habit_created_mid_day_without_disturbing_existing_completions(client, auth_headers):
    habits = _create_habits(client, auth_headers, ["Face Wash"])
    face_wash = habits[0]

    client.get("/api/v1/skincare/today", headers=auth_headers)
    client.put(
        "/api/v1/skincare/today",
        json={"habits": [{"habit_id": face_wash["id"], "completed": True}]},
        headers=auth_headers,
    )

    _create_habits(client, auth_headers, ["Sunscreen"])  # added mid-day

    body = client.get("/api/v1/skincare/today", headers=auth_headers).json()
    by_name = {h["name"]: h["completed"] for h in body["habits"]}

    assert by_name == {"Face Wash": True, "Sunscreen": False}


def test_get_today_hides_habit_disabled_after_its_row_was_created(client, auth_headers):
    habits = _create_habits(client, auth_headers, ["Face Wash", "Sunscreen"])
    face_wash = next(h for h in habits if h["name"] == "Face Wash")
    sunscreen = next(h for h in habits if h["name"] == "Sunscreen")

    client.get("/api/v1/skincare/today", headers=auth_headers)  # syncs both rows in

    client.put(
        "/api/v1/skincare/habits",
        json={"habits": [{"id": face_wash["id"], "name": "Face Wash", "is_active": False, "sort_order": 0}]},
        headers=auth_headers,
    )

    body = client.get("/api/v1/skincare/today", headers=auth_headers).json()
    assert {h["name"] for h in body["habits"]} == {"Sunscreen"}

    # PUT /today must now only require the still-active habit.
    response = client.put(
        "/api/v1/skincare/today",
        json={"habits": [{"habit_id": sunscreen["id"], "completed": True}]},
        headers=auth_headers,
    )
    assert response.status_code == 200


def test_update_today_sets_completion_per_habit(client, auth_headers):
    habits = _create_habits(client, auth_headers, ["Face Wash", "Sunscreen"])
    face_wash = next(h for h in habits if h["name"] == "Face Wash")
    sunscreen = next(h for h in habits if h["name"] == "Sunscreen")

    response = client.put(
        "/api/v1/skincare/today",
        json={
            "habits": [
                {"habit_id": face_wash["id"], "completed": True},
                {"habit_id": sunscreen["id"], "completed": False},
            ]
        },
        headers=auth_headers,
    )

    assert response.status_code == 200
    by_name = {h["name"]: h["completed"] for h in response.json()["habits"]}
    assert by_name == {"Face Wash": True, "Sunscreen": False}


def test_update_today_rejects_incomplete_habit_payload(client, auth_headers):
    habits = _create_habits(client, auth_headers, ["Face Wash", "Sunscreen"])
    face_wash = habits[0]

    response = client.put(
        "/api/v1/skincare/today",
        json={"habits": [{"habit_id": face_wash["id"], "completed": True}]},
        headers=auth_headers,
    )
    assert response.status_code == 400


def test_update_today_rejects_unknown_habit_id(client, auth_headers):
    _create_habits(client, auth_headers, ["Face Wash"])
    client.get("/api/v1/skincare/today", headers=auth_headers)

    response = client.put(
        "/api/v1/skincare/today",
        json={"habits": [{"habit_id": str(uuid.uuid4()), "completed": True}]},
        headers=auth_headers,
    )
    assert response.status_code == 400


def test_get_history_reflects_each_entrys_own_habit_set_over_time(client, auth_headers):
    habits = _create_habits(client, auth_headers, ["Face Wash", "Sunscreen"])
    face_wash_id = UUID(next(h for h in habits if h["name"] == "Face Wash")["id"])
    sunscreen_id = UUID(next(h for h in habits if h["name"] == "Sunscreen")["id"])
    uid = _user_id(auth_headers)

    old_day = date.today() - timedelta(days=2)
    recent_day = date.today() - timedelta(days=1)

    db = SessionLocal()
    try:
        # Older day: only Face Wash existed yet.
        _insert_backdated_entry(db, uid, old_day, {face_wash_id: True})
        # More recent day: both habits exist, one incomplete.
        _insert_backdated_entry(db, uid, recent_day, {face_wash_id: True, sunscreen_id: False})
    finally:
        db.close()

    history = client.get("/api/v1/skincare/history", headers=auth_headers).json()
    by_date = {h["date"]: h for h in history}

    assert by_date[str(old_day)]["total"] == 1
    assert by_date[str(old_day)]["completed"] == 1
    assert by_date[str(old_day)]["progress"] == 100

    assert by_date[str(recent_day)]["total"] == 2
    assert by_date[str(recent_day)]["completed"] == 1
    assert by_date[str(recent_day)]["progress"] == 50


def test_get_stats_zero_habit_day_is_not_a_perfect_day(client, auth_headers):
    uid = _user_id(auth_headers)

    db = SessionLocal()
    try:
        _insert_backdated_entry(db, uid, date.today() - timedelta(days=1), {})
    finally:
        db.close()

    stats = client.get("/api/v1/skincare/stats", headers=auth_headers).json()

    assert stats["total_days"] == 1
    assert stats["current_streak"] == 0
    assert stats["best_streak"] == 0


def test_get_stats_streak_with_dynamic_habits(client, auth_headers):
    habits = _create_habits(client, auth_headers, ["Face Wash"])
    face_wash_id = UUID(habits[0]["id"])
    uid = _user_id(auth_headers)

    db = SessionLocal()
    try:
        _insert_backdated_entry(db, uid, date.today() - timedelta(days=2), {face_wash_id: True})
        _insert_backdated_entry(db, uid, date.today() - timedelta(days=1), {face_wash_id: True})
    finally:
        db.close()

    client.put(
        "/api/v1/skincare/today",
        json={"habits": [{"habit_id": str(face_wash_id), "completed": True}]},
        headers=auth_headers,
    )

    stats = client.get("/api/v1/skincare/stats", headers=auth_headers).json()

    assert stats["current_streak"] == 3
    assert stats["best_streak"] == 3
    assert stats["total_days"] == 3
