"""End-to-end flows. The real CLI drives the real Client; only the network is replaced.

`FakeAPI` is an httpx transport that answers every endpoint the CLI calls, plus the presigned result file.
Tests assert on what the command prints and its exit code. They read `api.requests` only for what went on the wire.
"""
import gzip
import hashlib
import json

import httpx
import pytest
from click.testing import CliRunner

from voygr.cli import cli
from voygr.client import Client

API_KEY = "pk_live_abc123"
RESULTS_HOST = "results.example.test"
PLACES_CSV = (
    "name,address,country,id\n"
    "Blue Bottle Coffee,66 Mint St,us,p-1\n"
    "Tartine Bakery,600 Guerrero St,us,p-2\n"
    "Zuni Café,1658 Market St,us,p-3\n"
)


class FakeAPI:
    """The Places API in miniature. A job reports `running` on its first poll and `completed` after."""

    def __init__(self):
        self.requests = []
        self.job = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.url.host == RESULTS_HOST:
            return httpx.Response(200, content=self.job["file"])
        if path == "/signup":
            return httpx.Response(200, json={"success": True, "message": "If this is a new email, a key has been sent."})
        if request.headers.get("X-API-Key") != API_KEY:
            return httpx.Response(401, json={"error": "Invalid API key", "error_code": "AUTHENTICATION_ERROR"})
        body = json.loads(request.content) if request.content else {}
        route = (request.method, path)
        if route == ("POST", "/v1/validate"):
            return httpx.Response(200, json=self.validated(body))
        if route == ("POST", "/v1/enrich"):
            return httpx.Response(200, json={
                "success": True, "id": body.get("id"),
                "attributes": {name: {"value": f"{name} of {body['poi_name']}", "confidence": "high"}
                               for name in body.get("attributes") or ["phone"] if isinstance(name, str)},
                "request_id": "req_enrich",
            })
        if route in (("POST", "/v1/jobs/validate"), ("POST", "/v1/jobs/enrich")):
            return self.submit(path.rsplit("/", 1)[1], body["pois"])
        if route == ("GET", "/v1/jobs/b-1"):
            return httpx.Response(200, json=self.status())
        if route == ("DELETE", "/v1/jobs/b-1"):
            return httpx.Response(200, json={**self.status(), "status": "cancelled"})
        if route == ("GET", "/v1/usage"):
            return httpx.Response(200, json={
                "tier": "free", "quota_limit": 2500, "current_usage": 12, "remaining": 2488, "available": 2488,
                "percentage_used": 0.5, "period": "lifetime", "status": "active", "reset_date": "2099-12-31",
            })
        return httpx.Response(404, json={"error": f"No route {request.method} {path}", "error_code": "NOT_FOUND"})

    @staticmethod
    def validated(place: dict) -> dict:
        return {
            "success": True, "id": place.get("id"), "existence_confidence": 0.94,
            "operational_status": {"status": "open", "closure_reason": None, "closure_confidence": None},
            "request_id": "req_validate",
        }

    def submit(self, kind: str, pois: list[dict]) -> httpx.Response:
        rows = [self.validated(poi) for poi in pois]
        file = gzip.compress(b"".join(json.dumps(row, ensure_ascii=False).encode() + b"\n" for row in rows))
        self.job = {"kind": kind, "total": len(pois), "file": file, "polls": 0}
        return httpx.Response(202, json={
            "batch_id": "b-1", "type": kind, "status": "queued", "total_items": len(pois),
            "created_at": "2026-10-21T10:00:00Z", "eta_seconds": 5, "eta_completion_at": "2026-10-21T10:00:05Z",
        })

    def status(self) -> dict:
        job = self.job
        job["polls"] += 1
        status = {"batch_id": "b-1", "type": job["kind"], "total_items": job["total"], "error": None, "error_code": None}
        if job["polls"] == 1:
            return {**status, "status": "running", "progress": {"processed": 1, "succeeded": 1, "failed": 0}}
        files = [{
            "url": f"https://{RESULTS_HOST}/jobs/b-1/part-0.jsonl.gz?X-Amz-Signature=sig",
            "size_bytes": len(job["file"]), "sha256": hashlib.sha256(job["file"]).hexdigest(),
            "expires_at": "2026-10-21T10:15:00Z",
        }]
        return {
            **status, "status": "completed",
            "progress": {"processed": job["total"], "succeeded": job["total"], "failed": 0},
            "results": {"format": "jsonl.gz", "total_items": job["total"], "files": files},
        }


@pytest.fixture
def api(monkeypatch, tmp_path):
    """The fake API behind `create_client`, with an empty home directory and no key in the environment."""
    api = FakeAPI()
    for name in ("VOYGR_API_KEY", "VOYGR_BASE_URL", "NO_COLOR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr("voygr.client.time.sleep", lambda seconds: None)
    monkeypatch.setattr(
        "voygr.cli.create_client", lambda **kwargs: Client(transport=httpx.MockTransport(api), retries=3, **kwargs)
    )
    return api


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def logged_in(runner, api):
    assert runner.invoke(cli, ["login", API_KEY]).exit_code == 0


@pytest.fixture
def places_file(tmp_path):
    path = tmp_path / "places.csv"
    path.write_text(PLACES_CSV, encoding="utf-8")
    return str(path)


def json_lines(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines()]


class TestFlows:
    def test_signup(self, runner, api):
        result = runner.invoke(cli, ["signup", "test@example.com", "--name", "Test User"])
        assert result.exit_code == 0
        assert json.loads(result.stdout)["success"] is True
        sent = json.loads(api.requests[0].content)
        assert sent == {"email": "test@example.com", "name": "Test User", "src": "voygr-cli"}
        assert "x-api-key" not in api.requests[0].headers

    def test_login_stores_the_key_for_later_commands(self, runner, api):
        before = runner.invoke(cli, ["usage"])
        assert before.exit_code == 1
        assert json.loads(before.stderr)["error"] == "CLIENT_ERROR"

        login = runner.invoke(cli, ["login", API_KEY])
        assert login.exit_code == 0
        assert json.loads(login.stdout) == {"success": True, "message": "API key saved"}

        after = runner.invoke(cli, ["usage"])
        assert after.exit_code == 0
        assert json.loads(after.stdout)["remaining"] == 2488

    def test_validate(self, runner, api, logged_in):
        result = runner.invoke(cli, ["validate", "Blue Bottle Coffee", "66 Mint St", "--country", "us", "--id", "p-1"])
        assert result.exit_code == 0
        output = json.loads(result.stdout)
        assert output["id"] == "p-1"
        assert output["operational_status"]["status"] == "open"
        assert json.loads(api.requests[-1].content) == {
            "poi_name": "Blue Bottle Coffee", "address": "66 Mint St", "country": "US", "id": "p-1",
        }

    def test_enrich(self, runner, api, logged_in):
        result = runner.invoke(cli, ["enrich", "Blue Bottle Coffee", "--attr", "phone", "--attr", "website"])
        assert result.exit_code == 0
        attributes = json.loads(result.stdout)["attributes"]
        assert attributes["phone"] == {"value": "phone of Blue Bottle Coffee", "confidence": "high"}
        assert set(attributes) == {"phone", "website"}

    def test_validate_file_prints_one_row_per_place_in_order(self, runner, api, logged_in, places_file):
        result = runner.invoke(cli, ["validate", "--file", places_file])
        assert result.exit_code == 0
        assert [row["id"] for row in json_lines(result.stdout)] == ["p-1", "p-2", "p-3"]
        assert result.stderr == "Submitted job b-1 (3 places).\n"

        submit = next(r for r in api.requests if r.url.path == "/v1/jobs/validate")
        assert json.loads(submit.content)["pois"][2] == {
            "poi_name": "Zuni Café", "address": "1658 Market St", "country": "US", "id": "p-3",
        }
        assert submit.headers["Idempotency-Key"]
        download = api.requests[-1]
        assert download.url.host == RESULTS_HOST
        assert "x-api-key" not in download.headers

    def test_enrich_file_sends_the_options_with_every_row(self, runner, api, logged_in, places_file):
        result = runner.invoke(cli, ["enrich", "--file", places_file, "--attr", "phone", "--summary"])
        assert result.exit_code == 0
        assert len(json_lines(result.stdout)) == 3
        submit = next(r for r in api.requests if r.url.path == "/v1/jobs/enrich")
        assert all(
            poi["attributes"] == ["phone"] and poi["include_summary"] is True
            for poi in json.loads(submit.content)["pois"]
        )

    def test_no_wait_then_jobs_status_results_and_cancel(self, runner, api, logged_in, places_file):
        submitted = runner.invoke(cli, ["validate", "--file", places_file, "--no-wait"])
        assert submitted.exit_code == 0
        assert json.loads(submitted.stdout)["batch_id"] == "b-1"
        assert not any(r.url.path == "/v1/jobs/b-1" for r in api.requests)

        status = runner.invoke(cli, ["jobs", "status", "b-1"])
        assert status.exit_code == 0
        assert json.loads(status.stdout)["status"] == "running"

        results = runner.invoke(cli, ["jobs", "results", "b-1"])
        assert results.exit_code == 0
        assert [row["id"] for row in json_lines(results.stdout)] == ["p-1", "p-2", "p-3"]

        cancel = runner.invoke(cli, ["jobs", "cancel", "b-1"])
        assert cancel.exit_code == 0
        assert json.loads(cancel.stdout)["status"] == "cancelled"

    def test_usage(self, runner, api, logged_in):
        result = runner.invoke(cli, ["usage"])
        assert result.exit_code == 0
        assert json.loads(result.stdout)["tier"] == "free"
        assert api.requests[-1].headers["X-API-Key"] == API_KEY

    def test_usage_human(self, runner, api, logged_in):
        result = runner.invoke(cli, ["--human", "usage"], env={"NO_COLOR": "1"})
        assert result.exit_code == 0
        assert "Available: 2488 credits" in result.stdout

    def test_whole_journey(self, runner, api, places_file):
        """Sign up, log in, validate, enrich, validate a CSV, check usage: each step feeds the next."""
        assert runner.invoke(cli, ["signup", "test@example.com"]).exit_code == 0
        assert runner.invoke(cli, ["login", API_KEY]).exit_code == 0

        validated = runner.invoke(cli, ["validate", "Blue Bottle Coffee", "66 Mint St"])
        assert validated.exit_code == 0
        assert json.loads(validated.stdout)["success"] is True

        enriched = runner.invoke(cli, ["enrich", "Blue Bottle Coffee"])
        assert enriched.exit_code == 0
        assert "phone" in json.loads(enriched.stdout)["attributes"]

        bulk = runner.invoke(cli, ["validate", "--file", places_file])
        assert bulk.exit_code == 0
        assert len(json_lines(bulk.stdout)) == 3

        usage = runner.invoke(cli, ["usage"])
        assert usage.exit_code == 0
        assert json.loads(usage.stdout)["remaining"] == 2488


class TestLogoutFlow:
    def test_logout_then_validate_fails_without_a_request(self, runner, api, logged_in):
        assert runner.invoke(cli, ["logout"]).exit_code == 0
        before = len(api.requests)

        result = runner.invoke(cli, ["validate", "Test"])
        assert result.exit_code == 1
        assert result.stdout == ""
        assert "No API key configured" in json.loads(result.stderr)["message"]
        assert len(api.requests) == before


class TestErrorJsonFormat:
    def test_rejected_key_is_json_on_stderr(self, runner, api):
        result = runner.invoke(cli, ["--api-key", "pk_live_wrong", "validate", "Test"])
        assert result.exit_code == 1
        assert result.stdout == ""
        assert json.loads(result.stderr) == {
            "error": "AUTHENTICATION_ERROR", "message": "AUTHENTICATION_ERROR: Invalid API key",
        }

    def test_rejected_key_on_a_bulk_run_submits_nothing(self, runner, api, places_file):
        result = runner.invoke(cli, ["--api-key", "pk_live_wrong", "validate", "--file", places_file])
        assert result.exit_code == 1
        assert result.stdout == ""
        assert json.loads(result.stderr)["error"] == "AUTHENTICATION_ERROR"
        assert api.job is None

    def test_bad_csv_exit_2_sends_nothing(self, runner, api, logged_in, tmp_path):
        bad = tmp_path / "bad.csv"
        bad.write_text("name,latitude,longitude\nA,1,1\nB,95,1\n", encoding="utf-8")
        before = len(api.requests)
        result = runner.invoke(cli, ["validate", "--file", str(bad)])
        assert result.exit_code == 2
        assert "line 3:" in result.output
        assert len(api.requests) == before
