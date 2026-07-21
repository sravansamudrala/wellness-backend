def _create_exercise(client, auth_headers, name):
    response = client.post(
        "/api/v1/gym/exercises",
        json={"name": name},
        headers=auth_headers,
    )
    assert response.status_code == 200
    return response.json()["id"]


def _create_plan_with_days(client, auth_headers, day_names):
    """Builds a custom plan with one exercise per day, named from `day_names`."""
    days = []
    for i, day_name in enumerate(day_names):
        exercise_id = _create_exercise(client, auth_headers, f"{day_name} Exercise")
        days.append(
            {
                "name": day_name,
                "order_index": i,
                "exercises": [
                    {"exercise_id": exercise_id, "order_index": 0, "target_reps": "8-12"}
                ],
            }
        )

    response = client.post(
        "/api/v1/gym/plans",
        json={"name": "Test Plan", "days": days},
        headers=auth_headers,
    )
    assert response.status_code == 200
    return response.json()


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


def test_create_plan_with_nested_days_and_exercises(client, auth_headers):
    plan = _create_plan_with_days(client, auth_headers, ["Push", "Pull"])

    assert plan["name"] == "Test Plan"
    assert len(plan["days"]) == 2
    assert plan["days"][0]["name"] == "Push"
    assert plan["days"][0]["exercises"][0]["exercise"]["name"] == "Push Exercise"


def test_activating_plan_queues_first_day(client, auth_headers):
    plan = _create_plan_with_days(client, auth_headers, ["Push", "Pull"])

    activate = client.post(
        f"/api/v1/gym/plans/{plan['id']}/activate",
        headers=auth_headers,
    )
    assert activate.status_code == 200
    assert activate.json()["active_plan_id"] == plan["id"]

    active = client.get("/api/v1/gym/active", headers=auth_headers)
    assert active.json()["next_day"]["name"] == "Push"


def test_completing_sessions_advances_queue_and_wraps(client, auth_headers):
    plan = _create_plan_with_days(client, auth_headers, ["Push", "Pull"])
    client.post(f"/api/v1/gym/plans/{plan['id']}/activate", headers=auth_headers)

    # Start and complete "Push" (the queued first day).
    start_1 = client.post("/api/v1/gym/sessions/start", json={}, headers=auth_headers)
    assert start_1.json()["name"] == "Push"
    session_1_id = start_1.json()["id"]
    client.post(f"/api/v1/gym/sessions/{session_1_id}/complete", headers=auth_headers)

    # Queue should now point at "Pull".
    active = client.get("/api/v1/gym/active", headers=auth_headers)
    assert active.json()["next_day"]["name"] == "Pull"

    # Start and complete "Pull" too — queue should wrap back to "Push".
    start_2 = client.post("/api/v1/gym/sessions/start", json={}, headers=auth_headers)
    assert start_2.json()["name"] == "Pull"
    session_2_id = start_2.json()["id"]
    client.post(f"/api/v1/gym/sessions/{session_2_id}/complete", headers=auth_headers)

    active_again = client.get("/api/v1/gym/active", headers=auth_headers)
    assert active_again.json()["next_day"]["name"] == "Push"


def test_log_sets_replaces_previous_sets(client, auth_headers):
    plan = _create_plan_with_days(client, auth_headers, ["Push"])
    client.post(f"/api/v1/gym/plans/{plan['id']}/activate", headers=auth_headers)

    start = client.post("/api/v1/gym/sessions/start", json={}, headers=auth_headers)
    session = start.json()
    session_exercise_id = session["exercises"][0]["id"]

    first_log = client.put(
        f"/api/v1/gym/sessions/{session['id']}/sets",
        json={
            "exercises": [
                {
                    "session_exercise_id": session_exercise_id,
                    "sets": [
                        {"set_number": 1, "reps": 10, "weight_kg": 40, "is_completed": True}
                    ],
                }
            ]
        },
        headers=auth_headers,
    )
    assert len(first_log.json()["exercises"][0]["sets"]) == 1

    # Logging again for the same exercise REPLACES sets, doesn't append.
    second_log = client.put(
        f"/api/v1/gym/sessions/{session['id']}/sets",
        json={
            "exercises": [
                {
                    "session_exercise_id": session_exercise_id,
                    "sets": [
                        {"set_number": 1, "reps": 10, "weight_kg": 40, "is_completed": True},
                        {"set_number": 2, "reps": 8, "weight_kg": 42.5, "is_completed": True},
                    ],
                }
            ]
        },
        headers=auth_headers,
    )
    assert len(second_log.json()["exercises"][0]["sets"]) == 2


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
