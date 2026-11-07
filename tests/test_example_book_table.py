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
def booking(monkeypatch, tmp_path):
    assert Path("examples/book_table/main.py").is_file(), "Table booking example is missing"
    module = importlib.import_module("examples.book_table.main")
    monkeypatch.chdir(tmp_path)
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


@pytest.fixture
def booking_clock(booking, monkeypatch):
    from datetime import datetime, timezone
    current = [datetime(2099, 11, 9, 2, tzinfo=timezone.utc)]  # One hour before the booking.
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return current[0].astimezone(tz)
    monkeypatch.setattr(booking, "datetime", Clock)
    return current


def test_recovery_after_booking_time_replays_saved_request(booking, phone_api, booking_clock, monkeypatch, tmp_path):
    from datetime import timedelta
    monkeypatch.setenv("PLACECALL_API_KEY", "test-call-key")
    phone_api.error = httpx.ReadTimeout("uncertain submission")
    first = CliRunner().invoke(booking.main, [*BOOKING, "--confirm-call", "--idempotency-key", "booking-001"])
    assert first.exit_code == 1
    receipts = list((tmp_path / ".voygr-calls").glob("*.json"))
    assert len(receipts) == 1
    record = json.loads(receipts[0].read_text())
    assert record["body"] == json.loads(phone_api.requests[0].content)
    assert record["idempotency_key"] == "booking-001"
    assert "test-call-key" not in receipts[0].read_text()
    assert receipts[0].stat().st_mode & 0o777 == 0o600

    booking_clock[0] += timedelta(hours=2)
    phone_api.error = None
    new_call = CliRunner().invoke(booking.main, [*BOOKING, "--confirm-call", "--idempotency-key", "new-key"])
    assert new_call.exit_code != 0
    assert len(phone_api.requests) == 1  # New calls still require a future booking.
    replay = CliRunner().invoke(booking.main, ["--retry-request", str(receipts[0]), "--confirm-call"])
    assert replay.exit_code == 0, replay.output
    assert len(phone_api.requests) == 2
    assert phone_api.requests[1].content == phone_api.requests[0].content
    assert phone_api.requests[1].headers["Idempotency-Key"] == "booking-001"


def test_expired_recovery_never_posts(booking, phone_api, booking_clock, monkeypatch, tmp_path):
    from datetime import timedelta
    monkeypatch.setenv("PLACECALL_API_KEY", "test-call-key")
    assert CliRunner().invoke(booking.main, [*BOOKING, "--confirm-call", "--idempotency-key", "booking-001"]).exit_code == 0
    receipt = next((tmp_path / ".voygr-calls").glob("*.json"))
    booking_clock[0] += timedelta(hours=24)
    result = CliRunner().invoke(booking.main, ["--retry-request", str(receipt), "--confirm-call"])
    assert result.exit_code == 1
    assert "24" in result.stderr
    assert len(phone_api.requests) == 1


def test_saved_retry_previews_without_a_key(booking, phone_api, booking_clock, monkeypatch, tmp_path):
    monkeypatch.setenv("PLACECALL_API_KEY", "test-call-key")
    assert CliRunner().invoke(booking.main, [*BOOKING, "--confirm-call", "--idempotency-key", "booking-001"]).exit_code == 0
    receipt = next((tmp_path / ".voygr-calls").glob("*.json"))
    monkeypatch.delenv("PLACECALL_API_KEY")
    preview = CliRunner().invoke(booking.main, ["--retry-request", str(receipt)])
    assert preview.exit_code == 0, preview.output
    assert json.loads(preview.stdout) == json.loads(phone_api.requests[0].content)
    assert len(phone_api.requests) == 1


@pytest.mark.parametrize("extra", [["--phone", "+14155550101"], ["--idempotency-key", "new-key"], ["--call-id", "call-example"]])
def test_retry_cannot_override_saved_request(booking, phone_api, booking_clock, monkeypatch, tmp_path, extra):
    monkeypatch.setenv("PLACECALL_API_KEY", "test-call-key")
    assert CliRunner().invoke(booking.main, [*BOOKING, "--confirm-call", "--idempotency-key", "booking-001"]).exit_code == 0
    receipt = next((tmp_path / ".voygr-calls").glob("*.json"))
    result = CliRunner().invoke(booking.main, ["--retry-request", str(receipt), "--confirm-call", *extra])
    assert result.exit_code != 0
    assert len(phone_api.requests) == 1


def test_cannot_reuse_key_with_changed_booking(booking, phone_api, booking_clock, monkeypatch):
    monkeypatch.setenv("PLACECALL_API_KEY", "test-call-key")
    assert CliRunner().invoke(booking.main, [*BOOKING, "--confirm-call", "--idempotency-key", "booking-001"]).exit_code == 0
    changed = BOOKING.copy()
    changed[changed.index("--name") + 1] = "Different Person"
    result = CliRunner().invoke(booking.main, [*changed, "--confirm-call", "--idempotency-key", "booking-001"])
    assert result.exit_code == 1
    assert len(phone_api.requests) == 1


def test_unwritable_recovery_file_prevents_submission(booking, phone_api, monkeypatch):
    monkeypatch.setenv("PLACECALL_API_KEY", "test-call-key")
    original = booking.os.open
    def denied(path, *args, **kwargs):
        if ".voygr-calls" in str(path):
            raise PermissionError("Cannot save recovery request")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(booking.os, "open", denied)
    result = CliRunner().invoke(booking.main, [*BOOKING, "--confirm-call", "--idempotency-key", "booking-001"])
    assert result.exit_code == 1
    assert phone_api.requests == []


@pytest.mark.parametrize("record", [None, {}, {"version": 1, "body": []}, "not-json"])
def test_malformed_recovery_never_posts(booking, phone_api, monkeypatch, tmp_path, record):
    monkeypatch.setenv("PLACECALL_API_KEY", "test-call-key")
    receipt = tmp_path / "bad.json"
    receipt.write_text(json.dumps(record) if record != "not-json" else "{broken", encoding="utf-8")
    result = CliRunner().invoke(booking.main, ["--retry-request", str(receipt), "--confirm-call"])
    assert result.exit_code == 1
    assert phone_api.requests == []
