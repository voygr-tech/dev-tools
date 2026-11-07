"""Booking preview, confirmation and recovery without making real phone calls."""
import importlib
import json
from pathlib import Path

import httpx
import pytest
from click.testing import CliRunner


BOOKING = ["--phone", "+14155550100", "--restaurant", "Example Bistro", "--name", "Jane Example",
           "--party-size", "2", "--at", "2099-11-08T19:00:00-08:00", "--callback", "+14155550101"]


@pytest.fixture
def booking(monkeypatch):
    assert Path("examples/book_table/main.py").is_file(), "Table booking example is missing"
    module = importlib.import_module("examples.book_table.main")
    for name in ("VOYGR_API_KEY", "PLACECALL_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    return module


@pytest.fixture
def phone_api(booking, monkeypatch):
    real_client = httpx.Client
    class API:
        def __init__(self):
            self.requests = []
            self.body = {"call_id": "call-example", "status": "queued"}
            self.status = 202
            self.error = None

        def __call__(self, request):
            self.requests.append(request)
            if self.error:
                raise self.error
            return httpx.Response(self.status, json=self.body)
    api = API()
    monkeypatch.setattr(booking.httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(api), **kw))
    return api


def test_preview_is_local_without_a_key(booking, phone_api):
    result = CliRunner().invoke(booking.main, BOOKING)
    assert result.exit_code == 0, result.output
    body = json.loads(result.stdout)
    assert body["target_phone"] == "+14155550100"
    assert body["language"] == "en"
    for detail in ("Example Bistro", "Jane Example", "2", "2099-11-08T19:00:00-08:00", "+14155550101"):
        assert detail in body["brief"]
    assert "deposit" in body["brief"]
    assert "read back" in body["brief"].lower()
    assert phone_api.requests == []


@pytest.mark.parametrize("key_name", ["PLACECALL_API_KEY", "VOYGR_API_KEY"])
def test_confirmed_call_submits_once(booking, phone_api, monkeypatch, key_name):
    monkeypatch.setenv(key_name, "test-call-key")
    result = CliRunner().invoke(booking.main, [*BOOKING, "--confirm-call", "--idempotency-key", "booking-001"])
    assert result.exit_code == 0, result.output
    assert len(phone_api.requests) == 1
    request = phone_api.requests[0]
    assert str(request.url) == "https://api.voygr.tech/calls"
    assert request.method == "POST"
    assert request.headers["X-API-Key"] == "test-call-key"
    assert request.headers["Idempotency-Key"] == "booking-001"
    assert request.headers["X-Client-Surface"] == "gh-repo"
    assert json.loads(request.content)["target_phone"] == "+14155550100"
    assert json.loads(result.stdout)["call_id"] == "call-example"
    assert "booking-001" in result.stderr
    assert "call-example" in result.stderr
    assert "test-call-key" not in result.output


@pytest.mark.parametrize("extra", [[], ["--idempotency-key", ""], ["--idempotency-key", "   "]])
def test_confirmation_needs_key_and_retry_identity(booking, phone_api, extra):
    result = CliRunner().invoke(booking.main, [*BOOKING, "--confirm-call", *extra])
    assert result.exit_code != 0
    assert phone_api.requests == []


@pytest.mark.parametrize("option,value", [
    ("--phone", "911"), ("--phone", "+442079460000"), ("--callback", "bad"),
    ("--party-size", "0"), ("--party-size", "-1"), ("--party-size", "two"),
    ("--at", "tomorrow evening"), ("--at", "2099-11-08T19:00:00"), ("--at", "2000-01-01T19:00:00Z"),
    ("--restaurant", "   "), ("--name", ""), ("--restaurant", "x" * 4001),
])
def test_invalid_booking_never_dials(booking, phone_api, monkeypatch, option, value):
    args = BOOKING.copy()
    args[args.index(option) + 1] = value
    monkeypatch.setenv("PLACECALL_API_KEY", "test-call-key")
    result = CliRunner().invoke(booking.main, [*args, "--confirm-call", "--idempotency-key", "booking-001"])
    assert result.exit_code != 0
    assert phone_api.requests == []


def test_missing_booking_detail_is_rejected(booking, phone_api):
    result = CliRunner().invoke(booking.main, BOOKING[:-2])
    assert result.exit_code != 0
    assert phone_api.requests == []


def test_readback_never_posts(booking, phone_api, monkeypatch):
    monkeypatch.setenv("PLACECALL_API_KEY", "test-call-key")
    phone_api.body = {"call_id": "call-example", "status": "completed", "result": None}
    phone_api.status = 200
    result = CliRunner().invoke(booking.main, ["--call-id", "call-example"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["result"] is None
    assert [(r.method, str(r.url)) for r in phone_api.requests] == [
        ("GET", "https://api.voygr.tech/calls/call-example")]


def test_readback_rejects_confirmation_options(booking, phone_api, monkeypatch):
    monkeypatch.setenv("PLACECALL_API_KEY", "test-call-key")
    result = CliRunner().invoke(booking.main, ["--call-id", "call-example", "--confirm-call"])
    assert result.exit_code != 0
    assert phone_api.requests == []


@pytest.mark.parametrize("body", [None, [], {}, {"call_id": ""}, {"call_id": 1}, {"call_id": "x", "status": []}])
def test_bad_response_never_causes_another_post(booking, phone_api, monkeypatch, body):
    monkeypatch.setenv("PLACECALL_API_KEY", "test-call-key")
    phone_api.body = body
    result = CliRunner().invoke(booking.main, [*BOOKING, "--confirm-call", "--idempotency-key", "booking-001"])
    assert result.exit_code != 0
    assert "Error:" in result.stderr
    assert len(phone_api.requests) == 1
    assert "booking-001" in result.stderr


@pytest.mark.parametrize("error", ["http", "timeout"])
def test_uncertain_failure_keeps_retry_key(booking, phone_api, monkeypatch, error):
    monkeypatch.setenv("PLACECALL_API_KEY", "test-call-key")
    if error == "http":
        phone_api.status = 503
    else:
        phone_api.error = httpx.ReadTimeout("test timeout")
    result = CliRunner().invoke(booking.main, [*BOOKING, "--confirm-call", "--idempotency-key", "booking-001"])
    assert result.exit_code == 1
    assert len(phone_api.requests) == 1
    assert "booking-001" in result.stderr
    assert "same" in result.stderr.lower()
