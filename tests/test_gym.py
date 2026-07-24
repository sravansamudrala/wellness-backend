import uuid

from app.database.session import SessionLocal
from app.models.gym.exercise import MuscleGroup


def _create_exercise(client, auth_headers, name):
    response = client.post(
        "/api/v1/gym/exercises",
        json={"name": name},
        headers=auth_headers,
    )
    assert response.status_code == 200
    return response.json()["id"]


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
