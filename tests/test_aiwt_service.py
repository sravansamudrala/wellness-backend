from unittest.mock import patch

import pytest
import requests

from app.core.config import settings
from app.services import aiwt_service


@pytest.fixture(autouse=True)
def _fake_service_url(monkeypatch):
    monkeypatch.setattr(settings, "aiwt_service_url", "http://fake-aiwt-service")


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    monkeypatch.setattr(aiwt_service.time, "sleep", lambda _seconds: None)


def _response(status_code, json_body=None):
    resp = requests.Response()
    resp.status_code = status_code
    if json_body is not None:
        import json as _json

        resp._content = _json.dumps(json_body).encode()
    return resp


def test_no_service_url_short_circuits(monkeypatch):
    monkeypatch.setattr(settings, "aiwt_service_url", "")
    with patch.object(aiwt_service.requests, "post") as post:
        result = aiwt_service.generate_water_message(amount_ml=0, goal_ml=2000, current_streak=0, hour=11)
    assert result is None
    post.assert_not_called()


def test_success_on_first_attempt():
    with patch.object(aiwt_service.requests, "post", return_value=_response(200, {"message": "Drink up — stay on track."})) as post:
        result = aiwt_service.generate_water_message(amount_ml=0, goal_ml=2000, current_streak=0, hour=11)
    assert result == "Drink up — stay on track."
    assert post.call_count == 1


def test_retries_on_429_then_succeeds():
    responses = [_response(429), _response(200, {"message": "Almost there — keep going."})]
    with patch.object(aiwt_service.requests, "post", side_effect=responses) as post:
        result = aiwt_service.generate_water_message(amount_ml=0, goal_ml=2000, current_streak=0, hour=11)
    assert result == "Almost there — keep going."
    assert post.call_count == 2


def test_exhausts_retries_on_persistent_429():
    with patch.object(aiwt_service.requests, "post", return_value=_response(429)) as post:
        result = aiwt_service.generate_water_message(amount_ml=0, goal_ml=2000, current_streak=0, hour=11)
    assert result is None
    assert post.call_count == aiwt_service.MAX_ATTEMPTS


def test_non_429_http_error_falls_back_immediately():
    with patch.object(aiwt_service.requests, "post", return_value=_response(500)) as post:
        result = aiwt_service.generate_water_message(amount_ml=0, goal_ml=2000, current_streak=0, hour=11)
    assert result is None
    assert post.call_count == 1


def test_connection_error_falls_back_immediately():
    with patch.object(aiwt_service.requests, "post", side_effect=requests.ConnectionError) as post:
        result = aiwt_service.generate_water_message(amount_ml=0, goal_ml=2000, current_streak=0, hour=11)
    assert result is None
    assert post.call_count == 1


def test_missing_message_key_falls_back():
    with patch.object(aiwt_service.requests, "post", return_value=_response(200, {})):
        result = aiwt_service.generate_water_message(amount_ml=0, goal_ml=2000, current_streak=0, hour=11)
    assert result is None
