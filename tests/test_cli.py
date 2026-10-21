import json

import click
import httpx
import pytest
from unittest.mock import ANY, patch, MagicMock
from click.testing import CliRunner
from voygr.cli import cli, parse_research, place_fields
from voygr.client import APIError, Client, STANDARD_ATTRIBUTES


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_client():
    with patch("voygr.cli.create_client") as mock_create:
        client = MagicMock()
        mock_create.return_value.__enter__ = MagicMock(return_value=client)
        mock_create.return_value.__exit__ = MagicMock(return_value=False)
        yield client


@pytest.fixture
def mock_create():
    """The patched create_client itself, for tests that check how the client is built."""
    with patch("voygr.cli.create_client") as create:
        client = MagicMock()
        create.return_value.__enter__ = MagicMock(return_value=client)
        create.return_value.__exit__ = MagicMock(return_value=False)
        create.client = client
        yield create


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    """No key or base URL from the developer's shell or config file leaks into a test."""
    monkeypatch.delenv("VOYGR_API_KEY", raising=False)
    monkeypatch.delenv("VOYGR_BASE_URL", raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    with patch("voygr.cli.load_config", return_value={}):
        yield


VALIDATE_RESULT = {
    "success": True,
    "existence_confidence": 0.94,
    "operational_status": {"status": "open", "closure_reason": None, "closure_confidence": None},
    "request_id": "req_abc",
}

USAGE_RESULT = {
    "tier": "free", "quota_limit": 100, "current_usage": 12, "remaining": 88, "available": 88,
    "percentage_used": 12.0, "period": "lifetime", "status": "active", "reset_date": "2099-12-31",
}


class TestSignup:
    def test_signup_success(self, runner, mock_client):
        mock_client.signup.return_value = {"success": True, "message": "API key sent to your email"}
        result = runner.invoke(cli, ["signup", "test@example.com"])
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["success"] is True

    def test_signup_sends_cli_src(self, runner, mock_client):
        mock_client.signup.return_value = {"success": True}
        runner.invoke(cli, ["signup", "test@example.com"])
        mock_client.signup.assert_called_once_with(email="test@example.com", name="test@example.com", src="voygr-cli")

    def test_signup_with_name(self, runner, mock_client):
        mock_client.signup.return_value = {"success": True, "message": "API key sent to your email"}
        result = runner.invoke(cli, ["signup", "test@example.com", "--name", "Jane Smith"])
        assert result.exit_code == 0
        mock_client.signup.assert_called_once_with(email="test@example.com", name="Jane Smith", src="voygr-cli")

    def test_signup_human_output_points_to_recover(self, runner, mock_client):
        mock_client.signup.return_value = {"success": True, "message": "If this is a new email, a key has been sent."}
        result = runner.invoke(cli, ["--human", "signup", "test@example.com"])
        assert result.exit_code == 0
        assert "If this is a new email" in result.output
        assert "voygr recover <email>" in result.output

    def test_signup_api_error(self, runner, mock_client):
        mock_client.signup.side_effect = APIError("Connection refused", status_code=None)
        result = runner.invoke(cli, ["signup", "test@example.com"])
        assert result.exit_code == 1
        error = json.loads(result.stderr)
        assert error["error"] == "CLIENT_ERROR"
        assert result.stdout == ""

    def test_signup_needs_no_key(self, runner, mock_create):
        mock_create.client.signup.return_value = {"success": True}
        runner.invoke(cli, ["--api-key", "pk_live_flag", "signup", "test@example.com"])
        assert mock_create.call_args.kwargs["api_key"] is None


class TestRecover:
    def test_recover_success(self, runner, mock_client):
        mock_client.recover.return_value = {
            "success": True,
            "message": "If an account exists for that email, a recovery link has been sent.",
        }
        result = runner.invoke(cli, ["recover", "test@example.com"])
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["success"] is True
        mock_client.recover.assert_called_once_with(email="test@example.com")

    def test_recover_human_output(self, runner, mock_client):
        mock_client.recover.return_value = {
            "success": True,
            "message": "If an account exists for that email, a recovery link has been sent.",
        }
        result = runner.invoke(cli, ["--human", "recover", "test@example.com"])
        assert result.exit_code == 0
        assert "recovery link" in result.output

    def test_recover_api_error(self, runner, mock_client):
        mock_client.recover.side_effect = APIError(
            "Too many requests", status_code=429, error_code="RATE_LIMIT_ERROR",
        )
        result = runner.invoke(cli, ["recover", "test@example.com"])
        assert result.exit_code == 1
        error = json.loads(result.stderr)
        assert error["error"] == "RATE_LIMIT_ERROR"

    def test_recover_missing_email(self, runner):
        result = runner.invoke(cli, ["recover"])
        assert result.exit_code == 2


class TestLogin:
    def test_login_stores_key(self, runner):
        with patch("voygr.cli.save_api_key") as mock_save:
            result = runner.invoke(cli, ["login", "pk_live_abc123"])
            assert result.exit_code == 0
            mock_save.assert_called_once_with("pk_live_abc123")
            output = json.loads(result.output)
            assert output["success"] is True

    def test_login_human_output(self, runner):
        with patch("voygr.cli.save_api_key"):
            result = runner.invoke(cli, ["--human", "login", "pk_live_abc123"])
        assert result.exit_code == 0
        assert "API key saved" in result.output

    def test_login_missing_key(self, runner):
        result = runner.invoke(cli, ["login"])
        assert result.exit_code == 2


class TestLogout:
    def test_logout_deletes_config(self, runner):
        with patch("voygr.cli.delete_config") as mock_delete:
            result = runner.invoke(cli, ["logout"])
            assert result.exit_code == 0
            mock_delete.assert_called_once()
            output = json.loads(result.output)
            assert output["success"] is True

    def test_logout_human_output(self, runner):
        with patch("voygr.cli.delete_config"):
            result = runner.invoke(cli, ["--human", "logout"])
        assert result.exit_code == 0
        assert "API key removed" in result.output


class TestParseResearch:
    def test_name_only(self):
        assert parse_research("owner_name") == {"name": "owner_name"}

    def test_name_with_description(self):
        assert parse_research("wheelchair_accessible=Step-free entrance?") == {
            "name": "wheelchair_accessible", "description": "Step-free entrance?",
        }

    def test_splits_on_first_equals_only(self):
        assert parse_research("rating=Is it >= 4.5?") == {"name": "rating", "description": "Is it >= 4.5?"}

    def test_strips_both_sides(self):
        assert parse_research("  seating  =  Outdoor seating?  ") == {
            "name": "seating", "description": "Outdoor seating?",
        }

    def test_empty_description_is_dropped(self):
        assert parse_research("seating=") == {"name": "seating"}
        assert parse_research("seating=   ") == {"name": "seating"}

    @pytest.mark.parametrize("value", ["", "   ", "=Outdoor seating?"])
    def test_empty_name_rejected(self, value):
        with pytest.raises(click.BadParameter, match="name"):
            parse_research(value)

    @pytest.mark.parametrize("name", STANDARD_ATTRIBUTES)
    def test_standard_attribute_rejected_with_pointer_to_attr(self, name):
        with pytest.raises(click.BadParameter, match="use --attr"):
            parse_research(name)

    def test_standard_attribute_rejected_even_with_description(self):
        with pytest.raises(click.BadParameter, match="use --attr"):
            parse_research("phone=The number")

    def test_name_length_limit(self):
        assert parse_research("a" * 100) == {"name": "a" * 100}
        with pytest.raises(click.BadParameter, match="100"):
            parse_research("a" * 101)

    def test_description_length_limit(self):
        assert parse_research("a=" + "d" * 500)["description"] == "d" * 500
        with pytest.raises(click.BadParameter, match="500"):
            parse_research("a=" + "d" * 501)

    def test_unicode_kept(self):
        assert parse_research("café=Est-il ouvert ?") == {"name": "café", "description": "Est-il ouvert ?"}


class TestPlaceFields:
    def test_nothing_given(self):
        assert place_fields(None, None, None, None, None) == {}

    def test_all_fields_use_api_names(self):
        assert place_fields("66 Mint St", "us", 37.78, -122.41, "p-1") == {
            "address": "66 Mint St", "country": "US", "latitude": 37.78, "longitude": -122.41, "id": "p-1",
        }

    def test_drops_none_only(self):
        assert place_fields("66 Mint St", None, None, None, None) == {"address": "66 Mint St"}

    def test_zero_coordinates_are_kept(self):
        assert place_fields(None, None, 0.0, 0.0, None) == {"latitude": 0.0, "longitude": 0.0}

    @pytest.mark.parametrize("lat,lng", [(37.78, None), (None, -122.41), (0.0, None)])
    def test_one_coordinate_alone_is_a_usage_error(self, lat, lng):
        with pytest.raises(click.UsageError, match="--lat and --lng go together"):
            place_fields(None, None, lat, lng, None)


class TestValidate:
    def test_validate_calls_client(self, runner, mock_client):
        mock_client.validate.return_value = VALIDATE_RESULT
        result = runner.invoke(cli, ["validate", "Blue Bottle Coffee", "66 Mint St", "--country", "us"])
        assert result.exit_code == 0
        assert json.loads(result.output)["existence_confidence"] == 0.94
        mock_client.validate.assert_called_once_with("Blue Bottle Coffee", address="66 Mint St", country="US")

    def test_validate_name_only(self, runner, mock_client):
        mock_client.validate.return_value = VALIDATE_RESULT
        result = runner.invoke(cli, ["validate", "Blue Bottle Coffee"])
        assert result.exit_code == 0
        mock_client.validate.assert_called_once_with("Blue Bottle Coffee")

    def test_validate_all_place_options(self, runner, mock_client):
        mock_client.validate.return_value = VALIDATE_RESULT
        result = runner.invoke(cli, [
            "validate", "Blue Bottle Coffee", "66 Mint St", "--country", "US",
            "--lat", "37.78", "--lng", "-122.41", "--id", "p-1",
        ])
        assert result.exit_code == 0
        mock_client.validate.assert_called_once_with(
            "Blue Bottle Coffee", address="66 Mint St", country="US", latitude=37.78, longitude=-122.41, id="p-1",
        )

    def test_validate_lat_without_lng(self, runner, mock_client):
        result = runner.invoke(cli, ["validate", "Blue Bottle Coffee", "--lat", "37.78"])
        assert result.exit_code == 2
        assert "--lat and --lng go together" in result.output
        mock_client.validate.assert_not_called()

    def test_validate_lng_without_lat(self, runner, mock_client):
        result = runner.invoke(cli, ["validate", "Blue Bottle Coffee", "--lng", "-122.41"])
        assert result.exit_code == 2
        mock_client.validate.assert_not_called()

    def test_validate_non_numeric_lat(self, runner, mock_client):
        result = runner.invoke(cli, ["validate", "X", "--lat", "north", "--lng", "1"])
        assert result.exit_code == 2
        mock_client.validate.assert_not_called()

    def test_validate_requires_name(self, runner, mock_client):
        result = runner.invoke(cli, ["validate"])
        assert result.exit_code == 2
        mock_client.validate.assert_not_called()

    def test_validate_uses_resolved_key(self, runner, mock_create):
        mock_create.client.validate.return_value = VALIDATE_RESULT
        runner.invoke(cli, ["--api-key", "pk_live_flag", "validate", "X"])
        assert mock_create.call_args.kwargs["api_key"] == "pk_live_flag"

    def test_validate_human_output(self, runner, mock_client):
        mock_client.validate.return_value = VALIDATE_RESULT
        result = runner.invoke(cli, ["--human", "validate", "Blue Bottle Coffee"])
        assert result.exit_code == 0
        assert "0.94" in result.output
        assert "open" in result.output
        with pytest.raises(json.JSONDecodeError):
            json.loads(result.output)

    def test_validate_api_error(self, runner, mock_client):
        mock_client.validate.side_effect = APIError(
            "AUTHENTICATION_ERROR: Invalid API key", status_code=401, error_code="AUTHENTICATION_ERROR",
        )
        result = runner.invoke(cli, ["validate", "Test"])
        assert result.exit_code == 1
        assert json.loads(result.stderr)["error"] == "AUTHENTICATION_ERROR"

    def test_validate_without_key_exits_1(self, runner):
        result = runner.invoke(cli, ["validate", "Test"])
        assert result.exit_code == 1
        assert "No API key configured" in json.loads(result.stderr)["message"]


class TestEnrich:
    def test_max_credits_help_says_it_is_per_place_and_per_row(self, runner):
        result = runner.invoke(cli, ["enrich", "--help"])
        help_text = " ".join(result.output.split())
        assert "The cap is per place; with --file, it is per row." in help_text
        assert "Refuse the request" not in help_text

    def test_enrich_defaults(self, runner, mock_client):
        mock_client.enrich.return_value = {"success": True, "attributes": {}}
        result = runner.invoke(cli, ["enrich", "X"])
        assert result.exit_code == 0
        mock_client.enrich.assert_called_once_with("X", attributes=None)

    def test_enrich_place_options(self, runner, mock_client):
        mock_client.enrich.return_value = {"success": True, "attributes": {}}
        result = runner.invoke(cli, [
            "enrich", "X", "1 Main St", "--country", "gb", "--lat", "51.5", "--lng", "-0.12", "--id", "p-9",
        ])
        assert result.exit_code == 0
        mock_client.enrich.assert_called_once_with(
            "X", attributes=None, address="1 Main St", country="GB", latitude=51.5, longitude=-0.12, id="p-9",
        )

    def test_enrich_attr_repeats(self, runner, mock_client):
        mock_client.enrich.return_value = {"success": True, "attributes": {}}
        result = runner.invoke(cli, ["enrich", "X", "--attr", "phone", "--attr", "website"])
        assert result.exit_code == 0
        mock_client.enrich.assert_called_once_with("X", attributes=["phone", "website"])

    def test_enrich_attr_and_research(self, runner, mock_client):
        mock_client.enrich.return_value = {"success": True, "attributes": {}}
        result = runner.invoke(cli, [
            "enrich", "X", "--attr", "phone", "--research", "wheelchair_accessible=Step-free?",
        ])
        assert result.exit_code == 0
        mock_client.enrich.assert_called_once_with(
            "X", attributes=["phone", {"name": "wheelchair_accessible", "description": "Step-free?"}],
        )

    def test_enrich_research_only(self, runner, mock_client):
        mock_client.enrich.return_value = {"success": True, "attributes": {}}
        runner.invoke(cli, ["enrich", "X", "--research", "outdoor_seating", "--research", "price_band=Price level"])
        mock_client.enrich.assert_called_once_with(
            "X", attributes=[{"name": "outdoor_seating"}, {"name": "price_band", "description": "Price level"}],
        )

    def test_attr_typo_rejected(self, runner, mock_client):
        result = runner.invoke(cli, ["enrich", "X", "--attr", "webiste"])
        assert result.exit_code == 2
        assert "webiste" in result.output
        mock_client.enrich.assert_not_called()

    def test_research_rejects_standard_name(self, runner, mock_client):
        result = runner.invoke(cli, ["enrich", "X", "--research", "phone"])
        assert result.exit_code == 2
        assert "--attr" in result.output
        mock_client.enrich.assert_not_called()

    def test_enrich_estimate_flags(self, runner, mock_client):
        mock_client.enrich.return_value = {"success": True, "attributes": {}}
        result = runner.invoke(cli, ["enrich", "X", "--estimate", "--summary", "--max-credits", "5"])
        assert result.exit_code == 0
        mock_client.enrich.assert_called_once_with(
            "X", attributes=None, estimate_only=True, include_summary=True, max_credits=5,
        )

    def test_max_credits_zero_is_sent(self, runner, mock_client):
        mock_client.enrich.return_value = {"success": True, "attributes": {}}
        runner.invoke(cli, ["enrich", "X", "--max-credits", "0"])
        mock_client.enrich.assert_called_once_with("X", attributes=None, max_credits=0)

    def test_negative_max_credits_rejected(self, runner, mock_client):
        result = runner.invoke(cli, ["enrich", "X", "--max-credits", "-1"])
        assert result.exit_code == 2
        mock_client.enrich.assert_not_called()

    def test_enrich_lat_without_lng(self, runner, mock_client):
        result = runner.invoke(cli, ["enrich", "X", "--lat", "51.5"])
        assert result.exit_code == 2
        mock_client.enrich.assert_not_called()

    def test_enrich_requires_name(self, runner, mock_client):
        result = runner.invoke(cli, ["enrich"])
        assert result.exit_code == 2
        mock_client.enrich.assert_not_called()

    def test_enrich_human_output(self, runner, mock_client):
        mock_client.enrich.return_value = {
            "success": True,
            "attributes": {"phone": {"value": "+14155551234", "confidence": "high"}},
        }
        result = runner.invoke(cli, ["--human", "enrich", "X"])
        assert result.exit_code == 0
        assert "phone: +14155551234 (high)" in result.output

    def test_enrich_human_estimate(self, runner, mock_client):
        mock_client.enrich.return_value = {
            "success": True, "attributes": {},
            "meta": {"stopped_reason": "estimate_only", "estimated_credits": 2},
        }
        result = runner.invoke(cli, ["--human", "enrich", "X", "--estimate"])
        assert "Estimated cost: 2 credits. Nothing was charged." in result.output

    def test_enrich_api_error(self, runner, mock_client):
        mock_client.enrich.side_effect = APIError(
            "QUOTA_EXCEEDED: Not enough credits", status_code=402, error_code="QUOTA_EXCEEDED",
        )
        result = runner.invoke(cli, ["enrich", "X"])
        assert result.exit_code == 1
        assert json.loads(result.stderr)["error"] == "QUOTA_EXCEEDED"


class TestUsage:
    def test_usage_success(self, runner, mock_client):
        mock_client.usage.return_value = USAGE_RESULT
        result = runner.invoke(cli, ["usage"])
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["remaining"] == 88

    def test_usage_api_error(self, runner, mock_client):
        mock_client.usage.side_effect = APIError("AUTHENTICATION_ERROR: Missing API key", status_code=401, error_code="AUTHENTICATION_ERROR")
        result = runner.invoke(cli, ["usage"])
        assert result.exit_code == 1


class TestPricing:
    def test_pricing_without_key(self, runner):
        """No key anywhere: the command still works and sends no key."""
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200, json={"unit": "credits", "rates": []})

        def build(**kwargs):
            return Client(transport=httpx.MockTransport(handler), **kwargs)

        with patch("voygr.cli.create_client", side_effect=build):
            result = runner.invoke(cli, ["pricing"])
        assert result.exit_code == 0
        assert json.loads(result.output) == {"unit": "credits", "rates": []}
        assert requests[0].url.path == "/v1/pricing"
        assert "x-api-key" not in requests[0].headers

    def test_pricing_human_output(self, runner, mock_client):
        mock_client.pricing.return_value = {
            "unit": "credits",
            "rates": [{"key": "validation", "label": "Single-record validation and enrichment",
                       "credits": 1, "per": "request"}],
        }
        result = runner.invoke(cli, ["--human", "pricing"])
        assert result.exit_code == 0
        assert "Single-record validation and enrichment: 1 credit per request" in result.output

    def test_pricing_api_error(self, runner, mock_client):
        mock_client.pricing.side_effect = APIError("Request timed out")
        result = runner.invoke(cli, ["pricing"])
        assert result.exit_code == 1


PLACES_CSV = "name,address,country\nCafe Roma,1 Main St,us\nBar Uno,,\n"
PLACES = [{"poi_name": "Cafe Roma", "address": "1 Main St", "country": "US"}, {"poi_name": "Bar Uno"}]

SUBMITTED = {
    "batch_id": "b-1", "type": "validate", "status": "queued", "created_at": "2026-10-21T10:00:00Z",
    "total_items": 2, "eta_seconds": 10, "eta_completion_at": "2026-10-21T10:00:10Z",
}
COMPLETED = {
    "batch_id": "b-1", "type": "validate", "status": "completed", "total_items": 2,
    "progress": {"processed": 2, "succeeded": 2, "failed": 0}, "error": None, "error_code": None,
    "results": {"format": "jsonl.gz", "total_items": 2, "files": []},
}
ROWS = [
    {"id": None, "success": True, "existence_confidence": 0.94, "error": None, "error_code": None},
    {"id": None, "success": True, "existence_confidence": 0.31, "error": None, "error_code": None},
]
STOPPED_WAITING = (
    "Stopped waiting. Job b-1 keeps running.\n"
    "  Results: voygr jobs results b-1\n"
    "  Cancel:  voygr jobs cancel b-1\n"
)


STILL_ON_SERVER = "Job b-1 is still on the server. Results: voygr jobs results b-1"


def json_lines(text: str) -> list[dict]:
    return [json.loads(line) for line in text.splitlines()]


@pytest.fixture
def places_file(tmp_path):
    path = tmp_path / "places.csv"
    path.write_text(PLACES_CSV, encoding="utf-8")
    return str(path)


@pytest.fixture
def job(mock_create):
    """A client whose job is submitted, completes at once and has two result rows."""
    client = mock_create.client
    client.submit_validate_job.return_value = SUBMITTED
    client.submit_enrich_job.return_value = {**SUBMITTED, "type": "enrich"}
    client.wait_for_job.return_value = COMPLETED
    client.iter_job_results.return_value = ROWS
    client.create = mock_create
    return client


class TestBulk:
    def test_validate_file_submits_job_and_prints_rows(self, runner, job, places_file):
        result = runner.invoke(cli, ["validate", "--file", places_file])
        assert result.exit_code == 0
        assert json_lines(result.stdout) == ROWS
        assert "Submitted job b-1 (2 places)." in result.stderr
        job.submit_validate_job.assert_called_once_with(PLACES, idempotency_key=ANY)
        assert job.wait_for_job.call_args.args == ("b-1",)
        job.iter_job_results.assert_called_once_with("b-1")
        job.validate.assert_not_called()

    def test_enrich_file_applies_flags_to_every_row(self, runner, job, places_file):
        result = runner.invoke(cli, [
            "enrich", "--file", places_file, "--attr", "phone", "--research", "seating=Outdoor seating?",
            "--summary", "--max-credits", "3",
        ])
        assert result.exit_code == 0
        assert json_lines(result.stdout) == ROWS
        pois = job.submit_enrich_job.call_args.args[0]
        extras = {
            "attributes": ["phone", {"name": "seating", "description": "Outdoor seating?"}],
            "include_summary": True,
            "max_credits": 3,
        }
        assert pois == [{**place, **extras} for place in PLACES]
        job.submit_validate_job.assert_not_called()
        job.enrich.assert_not_called()

    def test_enrich_file_without_flags_sends_the_places_alone(self, runner, job, places_file):
        result = runner.invoke(cli, ["enrich", "--file", places_file])
        assert result.exit_code == 0
        job.submit_enrich_job.assert_called_once_with(PLACES, idempotency_key=ANY)

    def test_enrich_file_max_credits_zero_is_sent(self, runner, job, places_file):
        runner.invoke(cli, ["enrich", "--file", places_file, "--max-credits", "0"])
        assert all(poi["max_credits"] == 0 for poi in job.submit_enrich_job.call_args.args[0])

    def test_enrich_file_attr_typo_rejected(self, runner, job, places_file):
        result = runner.invoke(cli, ["enrich", "--file", places_file, "--attr", "webiste"])
        assert result.exit_code == 2
        job.submit_enrich_job.assert_not_called()

    @pytest.mark.parametrize("command", ["validate", "enrich"])
    def test_file_and_name_conflict(self, runner, job, places_file, command):
        result = runner.invoke(cli, [command, "Cafe Roma", "--file", places_file])
        assert result.exit_code == 2
        assert "--file" in result.output
        job.create.assert_not_called()

    @pytest.mark.parametrize("option", [
        ["--country", "US"], ["--lat", "1", "--lng", "2"], ["--id", "p-1"],
    ])
    def test_file_refuses_single_place_options(self, runner, job, places_file, option):
        result = runner.invoke(cli, ["validate", "--file", places_file, *option])
        assert result.exit_code == 2
        assert "CSV" in result.output
        job.create.assert_not_called()

    def test_estimate_with_file_refused(self, runner, job, places_file):
        result = runner.invoke(cli, ["enrich", "--file", places_file, "--estimate"])
        assert result.exit_code == 2
        assert "voygr pricing" in result.output
        job.create.assert_not_called()
        job.submit_enrich_job.assert_not_called()

    @pytest.mark.parametrize("command", ["validate", "enrich"])
    def test_no_wait_without_file_refused(self, runner, mock_client, command):
        result = runner.invoke(cli, [command, "Cafe Roma", "--no-wait"])
        assert result.exit_code == 2
        assert "--file" in result.output
        getattr(mock_client, command).assert_not_called()

    def test_csv_error_exit_2_nothing_submitted(self, runner, job, tmp_path):
        bad = tmp_path / "bad.csv"
        bad.write_text("name,latitude,longitude\nA,1,1\nB,95,1\n", encoding="utf-8")
        result = runner.invoke(cli, ["validate", "--file", str(bad)])
        assert result.exit_code == 2
        assert "line 3:" in result.output
        assert "latitude" in result.output
        job.create.assert_not_called()
        job.submit_validate_job.assert_not_called()

    def test_missing_file_exit_2(self, runner, job, tmp_path):
        result = runner.invoke(cli, ["validate", "--file", str(tmp_path / "nope.csv")])
        assert result.exit_code == 2
        job.create.assert_not_called()

    def test_directory_as_file_exit_2(self, runner, job, tmp_path):
        result = runner.invoke(cli, ["validate", "--file", str(tmp_path)])
        assert result.exit_code == 2
        job.create.assert_not_called()

    def test_no_wait_prints_submit_response(self, runner, job, places_file):
        result = runner.invoke(cli, ["validate", "--file", places_file, "--no-wait"])
        assert result.exit_code == 0
        assert json.loads(result.stdout) == SUBMITTED
        assert "Submitted job b-1 (2 places)." in result.stderr
        job.wait_for_job.assert_not_called()
        job.iter_job_results.assert_not_called()

    def test_one_place_job_message_is_singular(self, runner, job, tmp_path):
        path = tmp_path / "one.csv"
        path.write_text("name\nTartine Bakery\n", encoding="utf-8")
        job.submit_validate_job.return_value = {**SUBMITTED, "total_items": 1}
        result = runner.invoke(cli, ["validate", "--file", str(path), "--no-wait"])
        assert result.exit_code == 0
        assert "Submitted job b-1 (1 place)." in result.stderr

    def test_enrich_no_wait_prints_submit_response(self, runner, job, places_file):
        result = runner.invoke(cli, ["enrich", "--file", places_file, "--no-wait"])
        assert result.exit_code == 0
        assert json.loads(result.stdout)["type"] == "enrich"
        job.wait_for_job.assert_not_called()

    def test_no_wait_human_output_names_the_job(self, runner, job, places_file):
        result = runner.invoke(cli, ["--human", "validate", "--file", places_file, "--no-wait"],
                               env={"NO_COLOR": "1"})
        assert result.exit_code == 0
        assert result.stdout == "Job b-1: queued\n"

    def test_ctrl_c_while_waiting(self, runner, job, places_file):
        job.wait_for_job.side_effect = KeyboardInterrupt
        result = runner.invoke(cli, ["validate", "--file", places_file])
        assert result.exit_code == 130
        assert STOPPED_WAITING in result.stderr
        assert result.stdout == ""
        job.cancel_job.assert_not_called()
        job.iter_job_results.assert_not_called()

    def test_failed_job_prints_rows_then_exit_1(self, runner, job, places_file):
        job.wait_for_job.return_value = {
            **COMPLETED, "status": "failed", "error": "Out of credits", "error_code": "QUOTA_EXCEEDED",
        }
        job.iter_job_results.return_value = ROWS[:1]
        result = runner.invoke(cli, ["validate", "--file", places_file])
        assert result.exit_code == 1
        assert json_lines(result.stdout) == ROWS[:1]
        assert json.loads(result.stderr.splitlines()[-1]) == {
            "error": "QUOTA_EXCEEDED", "message": "Out of credits",
        }

    def test_failed_job_without_details_gets_a_default_error(self, runner, job, places_file):
        job.wait_for_job.return_value = {**COMPLETED, "status": "failed"}
        job.iter_job_results.return_value = []
        result = runner.invoke(cli, ["validate", "--file", places_file])
        assert result.exit_code == 1
        assert result.stdout == ""
        assert json.loads(result.stderr.splitlines()[-1]) == {
            "error": "JOB_FAILED", "message": "Job b-1 failed.",
        }

    def test_cancelled_job_exit_1(self, runner, job, places_file):
        job.wait_for_job.return_value = {**COMPLETED, "status": "cancelled"}
        job.iter_job_results.return_value = ROWS[:1]
        result = runner.invoke(cli, ["validate", "--file", places_file])
        assert result.exit_code == 1
        assert json_lines(result.stdout) == ROWS[:1]
        assert json.loads(result.stderr.splitlines()[-1]) == {
            "error": "JOB_CANCELLED", "message": "Job b-1 was cancelled.",
        }

    def test_failed_job_human_mode(self, runner, job, places_file):
        job.wait_for_job.return_value = {**COMPLETED, "status": "failed", "error": "Out of credits"}
        result = runner.invoke(cli, ["--human", "validate", "--file", places_file], env={"NO_COLOR": "1"})
        assert result.exit_code == 1
        assert json_lines(result.stdout) == ROWS
        assert result.stderr.endswith("Error: Out of credits\n")

    def test_completed_with_failed_rows_exit_0(self, runner, job, places_file):
        failed_row = {"id": None, "success": False, "error": "Could not resolve", "error_code": "NOT_FOUND"}
        job.wait_for_job.return_value = {**COMPLETED, "progress": {"processed": 2, "succeeded": 1, "failed": 1}}
        job.iter_job_results.return_value = [ROWS[0], failed_row]
        result = runner.invoke(cli, ["validate", "--file", places_file])
        assert result.exit_code == 0
        assert json_lines(result.stdout) == [ROWS[0], failed_row]
        assert result.stderr == "Submitted job b-1 (2 places).\n"

    def test_rows_are_json_lines_in_human_mode_too(self, runner, job, places_file):
        result = runner.invoke(cli, ["--human", "validate", "--file", places_file])
        assert result.exit_code == 0
        assert json_lines(result.stdout) == ROWS

    def test_rows_keep_unicode(self, runner, job, places_file):
        job.iter_job_results.return_value = [{"id": "Café Zürich"}]
        result = runner.invoke(cli, ["validate", "--file", places_file])
        assert result.stdout == '{"id": "Café Zürich"}\n'

    def test_submit_api_error_exit_1(self, runner, job, places_file):
        job.submit_validate_job.side_effect = APIError(
            "INSUFFICIENT_CREDITS: Not enough credits", status_code=402, error_code="INSUFFICIENT_CREDITS",
        )
        result = runner.invoke(cli, ["validate", "--file", places_file])
        assert result.exit_code == 1
        assert json.loads(result.stderr)["error"] == "INSUFFICIENT_CREDITS"
        assert result.stdout == ""
        job.wait_for_job.assert_not_called()

    def test_polling_error_exit_1_names_the_job_still_on_the_server(self, runner, job, places_file):
        job.wait_for_job.side_effect = APIError("Request timed out")
        result = runner.invoke(cli, ["validate", "--file", places_file])
        assert result.exit_code == 1
        assert result.stdout == ""
        error, hint = result.stderr.splitlines()[-2:]
        assert json.loads(error) == {"error": "CLIENT_ERROR", "message": "Request timed out"}
        assert hint == STILL_ON_SERVER
        job.cancel_job.assert_not_called()
        job.iter_job_results.assert_not_called()

    def test_polling_error_in_human_mode(self, runner, job, places_file):
        job.wait_for_job.side_effect = APIError("Request timed out")
        result = runner.invoke(cli, ["--human", "validate", "--file", places_file], env={"NO_COLOR": "1"})
        assert result.exit_code == 1
        assert result.stderr.endswith("Error: Request timed out\n" + STILL_ON_SERVER + "\n")

    def test_polling_error_ends_the_progress_line_first(self, runner, job, places_file):
        def wait(batch_id, on_progress):
            on_progress({"total_items": 2, "progress": {"processed": 1}})
            raise APIError("Request timed out")

        job.wait_for_job.side_effect = wait
        with patch("voygr.cli.sys") as fake_sys:
            fake_sys.stderr.isatty.return_value = True
            result = runner.invoke(cli, ["validate", "--file", places_file])
        assert result.exit_code == 1
        assert "\r1/2\n{" in result.stderr
        assert result.stderr.endswith(STILL_ON_SERVER + "\n")

    def test_download_error_exit_1_after_earlier_rows(self, runner, job, places_file):
        def rows():
            yield ROWS[0]
            raise APIError("Result download link expired. Poll the job again for a fresh link.")

        job.iter_job_results.return_value = rows()
        result = runner.invoke(cli, ["validate", "--file", places_file])
        assert result.exit_code == 1
        assert json_lines(result.stdout) == ROWS[:1]
        error, hint = result.stderr.splitlines()[-2:]
        assert json.loads(error)["message"] == "Result download link expired. Poll the job again for a fresh link."
        assert hint == STILL_ON_SERVER
        job.cancel_job.assert_not_called()

    def test_download_error_before_any_row_still_names_the_job(self, runner, job, places_file):
        job.iter_job_results.side_effect = APIError("Request failed: boom")
        result = runner.invoke(cli, ["validate", "--file", places_file])
        assert result.exit_code == 1
        assert result.stdout == ""
        assert result.stderr.endswith(STILL_ON_SERVER + "\n")

    def test_no_progress_line_when_stderr_is_not_a_terminal(self, runner, job, places_file):
        result = runner.invoke(cli, ["validate", "--file", places_file])
        assert job.wait_for_job.call_args.kwargs["on_progress"] is None
        assert "\r" not in result.stderr

    def test_progress_line_on_a_terminal(self, runner, job, places_file):
        def wait(batch_id, on_progress):
            for processed in (0, 1, 2):
                on_progress({"total_items": 2, "progress": {"processed": processed}})
            return COMPLETED

        job.wait_for_job.side_effect = wait
        with patch("voygr.cli.sys") as fake_sys:
            fake_sys.stderr.isatty.return_value = True
            result = runner.invoke(cli, ["validate", "--file", places_file])
        assert result.exit_code == 0
        assert result.stderr == "Submitted job b-1 (2 places).\n\r0/2\r1/2\r2/2\n"

    def test_progress_line_is_ended_before_the_ctrl_c_message(self, runner, job, places_file):
        def wait(batch_id, on_progress):
            on_progress({"total_items": 2, "progress": {"processed": 1}})
            raise KeyboardInterrupt

        job.wait_for_job.side_effect = wait
        with patch("voygr.cli.sys") as fake_sys:
            fake_sys.stderr.isatty.return_value = True
            result = runner.invoke(cli, ["validate", "--file", places_file])
        assert result.exit_code == 130
        assert result.stderr.endswith("\r1/2\n" + STOPPED_WAITING)

    def test_progress_line_before_the_first_count(self, runner, job, places_file):
        def wait(batch_id, on_progress):
            on_progress({"status": "queued"})
            return COMPLETED

        job.wait_for_job.side_effect = wait
        with patch("voygr.cli.sys") as fake_sys:
            fake_sys.stderr.isatty.return_value = True
            result = runner.invoke(cli, ["validate", "--file", places_file])
        assert "\r0/?" in result.stderr

    def test_file_mode_uses_resolved_key(self, runner, job, places_file):
        runner.invoke(cli, ["--api-key", "pk_live_flag", "validate", "--file", places_file])
        assert job.create.call_args.kwargs["api_key"] == "pk_live_flag"


class TestJobsCommands:
    def test_jobs_status_cancel_results(self, runner, mock_client):
        mock_client.get_job.return_value = COMPLETED
        mock_client.cancel_job.return_value = {**COMPLETED, "status": "cancelled"}
        mock_client.wait_for_job.return_value = COMPLETED
        mock_client.iter_job_results.return_value = ROWS

        status = runner.invoke(cli, ["jobs", "status", "b-1"])
        assert status.exit_code == 0
        assert json.loads(status.stdout) == COMPLETED
        mock_client.get_job.assert_called_once_with("b-1")

        cancel = runner.invoke(cli, ["jobs", "cancel", "b-1"])
        assert cancel.exit_code == 0
        assert json.loads(cancel.stdout)["status"] == "cancelled"
        mock_client.cancel_job.assert_called_once_with("b-1")

        results = runner.invoke(cli, ["jobs", "results", "b-1"])
        assert results.exit_code == 0
        assert json_lines(results.stdout) == ROWS
        assert mock_client.wait_for_job.call_args.args == ("b-1",)
        mock_client.iter_job_results.assert_called_once_with("b-1")

    def test_jobs_status_does_not_wait_or_download(self, runner, mock_client):
        mock_client.get_job.return_value = {**COMPLETED, "status": "running"}
        runner.invoke(cli, ["jobs", "status", "b-1"])
        mock_client.wait_for_job.assert_not_called()
        mock_client.iter_job_results.assert_not_called()

    def test_jobs_status_human(self, runner, mock_client):
        mock_client.get_job.return_value = COMPLETED
        result = runner.invoke(cli, ["--human", "jobs", "status", "b-1"], env={"NO_COLOR": "1"})
        assert result.exit_code == 0
        assert "Job b-1: completed" in result.stdout
        assert "Progress: 2/2, 0 failed" in result.stdout

    def test_jobs_cancel_human(self, runner, mock_client):
        mock_client.cancel_job.return_value = {**COMPLETED, "status": "cancelled"}
        result = runner.invoke(cli, ["--human", "jobs", "cancel", "b-1"], env={"NO_COLOR": "1"})
        assert result.exit_code == 0
        assert "Job b-1: cancelled" in result.stdout
        assert "Rows already processed stay billed and downloadable." in result.stdout

    def test_jobs_results_waits_for_a_running_job(self, runner, mock_client):
        mock_client.wait_for_job.return_value = COMPLETED
        mock_client.iter_job_results.return_value = ROWS
        result = runner.invoke(cli, ["jobs", "results", "b-1"])
        assert result.exit_code == 0
        assert result.stderr == ""
        assert mock_client.wait_for_job.call_args.kwargs["on_progress"] is None

    def test_jobs_results_ctrl_c(self, runner, mock_client):
        mock_client.wait_for_job.side_effect = KeyboardInterrupt
        result = runner.invoke(cli, ["jobs", "results", "b-1"])
        assert result.exit_code == 130
        assert STOPPED_WAITING in result.stderr
        mock_client.cancel_job.assert_not_called()

    def test_jobs_results_of_a_failed_job_prints_rows_then_exit_1(self, runner, mock_client):
        mock_client.wait_for_job.return_value = {
            **COMPLETED, "status": "failed", "error": "Out of credits", "error_code": "QUOTA_EXCEEDED",
        }
        mock_client.iter_job_results.return_value = ROWS[:1]
        result = runner.invoke(cli, ["jobs", "results", "b-1"])
        assert result.exit_code == 1
        assert json_lines(result.stdout) == ROWS[:1]
        assert json.loads(result.stderr) == {"error": "QUOTA_EXCEEDED", "message": "Out of credits"}

    def test_jobs_results_of_a_cancelled_job_exit_1(self, runner, mock_client):
        mock_client.wait_for_job.return_value = {**COMPLETED, "status": "cancelled"}
        mock_client.iter_job_results.return_value = []
        result = runner.invoke(cli, ["jobs", "results", "b-1"])
        assert result.exit_code == 1
        assert json.loads(result.stderr)["error"] == "JOB_CANCELLED"

    @pytest.mark.parametrize("subcommand,method", [("status", "get_job"), ("cancel", "cancel_job")])
    def test_api_error_exit_1(self, runner, mock_client, subcommand, method):
        getattr(mock_client, method).side_effect = APIError(
            "NOT_FOUND: No such job", status_code=404, error_code="NOT_FOUND",
        )
        result = runner.invoke(cli, ["jobs", subcommand, "b-9"])
        assert result.exit_code == 1
        assert json.loads(result.stderr) == {"error": "NOT_FOUND", "message": "NOT_FOUND: No such job"}
        assert result.stdout == ""

    def test_results_api_error_exit_1(self, runner, mock_client):
        mock_client.wait_for_job.side_effect = APIError(
            "NOT_FOUND: No such job", status_code=404, error_code="NOT_FOUND",
        )
        result = runner.invoke(cli, ["jobs", "results", "b-9"])
        assert result.exit_code == 1
        assert json.loads(result.stderr)["error"] == "NOT_FOUND"

    def test_results_of_an_unknown_job_does_not_claim_it_is_on_the_server(self, runner, mock_client):
        mock_client.wait_for_job.side_effect = APIError(
            "NOT_FOUND: No such job", status_code=404, error_code="NOT_FOUND",
        )
        result = runner.invoke(cli, ["jobs", "results", "b-9"])
        assert "still on the server" not in result.stderr

    def test_results_polling_error_names_the_job_still_on_the_server(self, runner, mock_client):
        mock_client.wait_for_job.side_effect = APIError("Request timed out")
        result = runner.invoke(cli, ["jobs", "results", "b-1"])
        assert result.exit_code == 1
        assert result.stdout == ""
        error, hint = result.stderr.splitlines()
        assert json.loads(error) == {"error": "CLIENT_ERROR", "message": "Request timed out"}
        assert hint == STILL_ON_SERVER
        mock_client.cancel_job.assert_not_called()

    def test_results_download_error_prints_earlier_rows_then_the_hint(self, runner, mock_client):
        def rows():
            yield ROWS[0]
            raise APIError("Result file failed its checksum. Poll the job again for a fresh link.")

        mock_client.wait_for_job.return_value = COMPLETED
        mock_client.iter_job_results.return_value = rows()
        result = runner.invoke(cli, ["jobs", "results", "b-1"])
        assert result.exit_code == 1
        assert json_lines(result.stdout) == ROWS[:1]
        assert result.stderr.splitlines()[-1] == STILL_ON_SERVER
        assert "Run the command again" not in result.stderr

    @pytest.mark.parametrize("subcommand", ["status", "results", "cancel"])
    def test_batch_id_required(self, runner, mock_client, subcommand):
        result = runner.invoke(cli, ["jobs", subcommand])
        assert result.exit_code == 2

    @pytest.mark.parametrize("subcommand", ["status", "results", "cancel"])
    def test_without_key_exit_1(self, runner, subcommand):
        result = runner.invoke(cli, ["jobs", subcommand, "b-1"])
        assert result.exit_code == 1
        assert "No API key configured" in json.loads(result.stderr.splitlines()[0])["message"]

    def test_jobs_help_lists_subcommands(self, runner):
        result = runner.invoke(cli, ["jobs", "--help"])
        assert result.exit_code == 0
        for name in ("status", "results", "cancel"):
            assert name in result.output


class TestRemovedCommands:
    def test_check_command_removed(self, runner):
        result = runner.invoke(cli, ["check", "Test", "123 Main St"])
        assert result.exit_code == 2
        assert "No such command" in result.output


class TestGlobalFlags:
    def test_base_url_flag(self, runner, mock_create):
        mock_create.client.usage.return_value = {"remaining": 88}
        runner.invoke(cli, ["--base-url", "https://staging.voygr.tech", "usage"])
        mock_create.assert_called_once()
        assert mock_create.call_args.kwargs["base_url"] == "https://staging.voygr.tech"

    def test_default_base_url_is_api(self, runner, mock_create):
        mock_create.client.usage.return_value = {"remaining": 88}
        runner.invoke(cli, ["usage"])
        assert mock_create.call_args.kwargs["base_url"] == "https://api.voygr.tech"

    def test_base_url_env(self, runner, mock_create):
        mock_create.client.usage.return_value = {"remaining": 88}
        runner.invoke(cli, ["usage"], env={"VOYGR_BASE_URL": "https://staging.voygr.tech"})
        assert mock_create.call_args.kwargs["base_url"] == "https://staging.voygr.tech"

    def test_base_url_flag_beats_env(self, runner, mock_create):
        mock_create.client.usage.return_value = {"remaining": 88}
        runner.invoke(
            cli, ["--base-url", "https://flag.voygr.tech", "usage"],
            env={"VOYGR_BASE_URL": "https://env.voygr.tech"},
        )
        assert mock_create.call_args.kwargs["base_url"] == "https://flag.voygr.tech"

    def test_empty_base_url_env_falls_back_to_default(self, runner, mock_create):
        mock_create.client.usage.return_value = {"remaining": 88}
        runner.invoke(cli, ["usage"], env={"VOYGR_BASE_URL": ""})
        assert mock_create.call_args.kwargs["base_url"] == "https://api.voygr.tech"


class TestOutputFormat:
    def test_default_is_json(self, runner, mock_client):
        mock_client.usage.return_value = {"quota_limit": 100, "remaining": 88}
        result = runner.invoke(cli, ["usage"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["remaining"] == 88

    def test_output_keeps_unicode(self, runner, mock_client):
        mock_client.validate.return_value = {"poi_name": "Café Zürich"}
        result = runner.invoke(cli, ["validate", "Café Zürich"])
        assert result.exit_code == 0
        assert "Café Zürich" in result.stdout
        assert "\\u" not in result.stdout

    def test_error_output_keeps_unicode(self, runner, mock_client):
        mock_client.validate.side_effect = APIError("Pas de résultat pour Zürich", error_code="NOT_FOUND")
        result = runner.invoke(cli, ["validate", "X"])
        assert "Pas de résultat pour Zürich" in result.stderr

    def test_api_error_exit_1_json_stderr(self, runner, mock_client):
        mock_client.enrich.side_effect = APIError(
            "QUOTA_EXCEEDED: Not enough credits", status_code=402, error_code="QUOTA_EXCEEDED",
        )
        result = runner.invoke(cli, ["enrich", "X"])
        assert result.exit_code == 1
        assert json.loads(result.stderr) == {
            "error": "QUOTA_EXCEEDED", "message": "QUOTA_EXCEEDED: Not enough credits",
        }
        assert result.stdout == ""

    def test_human_usage_output(self, runner, mock_client):
        mock_client.usage.return_value = USAGE_RESULT
        result = runner.invoke(cli, ["--human", "usage"])
        assert result.exit_code == 0
        assert "88" in result.output
        assert "100" in result.output
        assert "free" in result.output

    def test_human_error_output(self, runner, mock_client):
        mock_client.validate.side_effect = APIError("Invalid API key", status_code=401, error_code="AUTHENTICATION_ERROR")
        result = runner.invoke(cli, ["--human", "validate", "Test"])
        assert result.exit_code == 1
        assert "Invalid API key" in result.stderr
        assert result.stdout == ""

    def test_no_color_env(self, runner, mock_client):
        mock_client.usage.return_value = {"quota_limit": 100, "remaining": 88}
        result = runner.invoke(cli, ["--human", "usage"], env={"NO_COLOR": "1"})
        assert result.exit_code == 0
        assert "\033[" not in result.output

    def test_no_color_env_reaches_formatter(self, runner, mock_client):
        mock_client.validate.return_value = VALIDATE_RESULT
        with patch("voygr.cli.format_human", return_value="ok") as formatter:
            runner.invoke(cli, ["--human", "validate", "X"], env={"NO_COLOR": "1"})
            runner.invoke(cli, ["--human", "validate", "X"])
        assert [call.kwargs["color"] for call in formatter.call_args_list] == [False, True]


class TestSuccessFalse:
    """A 200 body with success:false is a failed request: nothing on stdout, the error on stderr, exit 1."""

    FAILED = {"success": False, "error": "Backend timed out", "error_code": "BACKEND_TIMEOUT"}

    def test_validate_success_false_exits_1(self, runner, mock_client):
        mock_client.validate.return_value = self.FAILED
        result = runner.invoke(cli, ["validate", "X"])
        assert result.exit_code == 1
        assert result.stdout == ""
        assert json.loads(result.stderr) == {"error": "BACKEND_TIMEOUT", "message": "Backend timed out"}

    def test_enrich_success_false_exits_1(self, runner, mock_client):
        mock_client.enrich.return_value = {
            "success": False, "error": "Could not resolve", "error_code": "VALIDATION_ERROR",
        }
        result = runner.invoke(cli, ["enrich", "X"])
        assert result.exit_code == 1
        assert result.stdout == ""
        assert json.loads(result.stderr) == {"error": "VALIDATION_ERROR", "message": "Could not resolve"}

    def test_success_false_human_mode(self, runner, mock_client):
        mock_client.validate.return_value = self.FAILED
        result = runner.invoke(cli, ["--human", "validate", "X"], env={"NO_COLOR": "1"})
        assert result.exit_code == 1
        assert result.stdout == ""
        assert result.stderr == "Error: Backend timed out\n"

    def test_success_false_human_mode_is_red_without_no_color(self, runner, mock_client):
        mock_client.enrich.return_value = self.FAILED
        result = runner.invoke(cli, ["--human", "enrich", "X"], color=True)
        assert result.exit_code == 1
        assert result.stdout == ""
        assert result.stderr.startswith("\033[31m")
        assert "Backend timed out" in result.stderr

    @pytest.mark.parametrize("command", ["validate", "enrich"])
    def test_success_false_without_error_code_uses_api_error(self, runner, mock_client, command):
        getattr(mock_client, command).return_value = {"success": False, "error": "Something broke"}
        result = runner.invoke(cli, [command, "X"])
        assert result.exit_code == 1
        assert json.loads(result.stderr) == {"error": "API_ERROR", "message": "Something broke"}

    @pytest.mark.parametrize("command", ["validate", "enrich"])
    def test_success_false_without_message_uses_default(self, runner, mock_client, command):
        getattr(mock_client, command).return_value = {"success": False}
        result = runner.invoke(cli, [command, "X"])
        assert result.exit_code == 1
        assert json.loads(result.stderr) == {"error": "API_ERROR", "message": "Request failed."}

    @pytest.mark.parametrize("command", ["validate", "enrich"])
    def test_success_true_or_absent_still_prints_and_exits_0(self, runner, mock_client, command):
        for body in ({"success": True, "request_id": "r1"}, {"request_id": "r2"}):
            getattr(mock_client, command).return_value = body
            result = runner.invoke(cli, [command, "X"])
            assert result.exit_code == 0
            assert json.loads(result.stdout) == body
            assert result.stderr == ""


class TestVersion:
    def test_version_flag(self, runner):
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.4.0" in result.output
        assert "voygr" in result.output.lower()


class TestDebugFlag:
    def test_debug_flag_accepted(self, runner, mock_client):
        mock_client.usage.return_value = {"remaining": 88}
        result = runner.invoke(cli, ["--debug", "usage"])
        assert result.exit_code == 0

    def test_debug_flag_reaches_client(self, runner, mock_create):
        mock_create.client.usage.return_value = {"remaining": 88}
        runner.invoke(cli, ["--debug", "usage"])
        assert mock_create.call_args.kwargs["debug"] is True


class TestAuthResolution:
    def test_flag_overrides_env(self, runner, mock_create):
        mock_create.client.usage.return_value = {"remaining": 88}
        result = runner.invoke(cli, ["--api-key", "pk_live_flag", "usage"], env={"VOYGR_API_KEY": "pk_live_env"})
        assert result.exit_code == 0
        assert mock_create.call_args.kwargs["api_key"] == "pk_live_flag"

    def test_env_overrides_config(self, runner, mock_create):
        mock_create.client.usage.return_value = {"remaining": 88}
        with patch("voygr.cli.load_config", return_value={"api_key": "pk_live_config"}):
            result = runner.invoke(cli, ["usage"], env={"VOYGR_API_KEY": "pk_live_env"})
        assert result.exit_code == 0
        assert mock_create.call_args.kwargs["api_key"] == "pk_live_env"

    def test_config_used_when_nothing_else(self, runner, mock_create):
        mock_create.client.usage.return_value = {"remaining": 88}
        with patch("voygr.cli.load_config", return_value={"api_key": "pk_live_config"}):
            result = runner.invoke(cli, ["usage"])
        assert result.exit_code == 0
        assert mock_create.call_args.kwargs["api_key"] == "pk_live_config"


class TestCompletions:
    def test_completions_bash(self, runner):
        result = runner.invoke(cli, ["completions", "bash"])
        assert result.exit_code == 0
        assert "bash_source" in result.output

    def test_completions_zsh(self, runner):
        result = runner.invoke(cli, ["completions", "zsh"])
        assert result.exit_code == 0
        assert "zsh_source" in result.output

    def test_completions_fish(self, runner):
        result = runner.invoke(cli, ["completions", "fish"])
        assert result.exit_code == 0
        assert "fish_source" in result.output

    def test_completions_auto_detect_zsh(self, runner):
        result = runner.invoke(cli, ["completions"], env={"SHELL": "/bin/zsh"})
        assert result.exit_code == 0
        assert "zsh_source" in result.output

    def test_completions_auto_detect_defaults_to_bash(self, runner):
        result = runner.invoke(cli, ["completions"], env={"SHELL": "/bin/sh"})
        assert result.exit_code == 0
        assert "bash_source" in result.output


class TestIdempotencyKey:
    def test_file_submit_sends_a_generated_key(self, runner, job, places_file):
        runner.invoke(cli, ["validate", "--file", places_file])
        key = job.submit_validate_job.call_args.kwargs["idempotency_key"]
        assert len(key) == 36 and key.count("-") == 4

    def test_given_key_is_sent(self, runner, job, places_file):
        result = runner.invoke(cli, ["enrich", "--file", places_file, "--idempotency-key", "k-1"])
        assert result.exit_code == 0
        assert job.submit_enrich_job.call_args.kwargs["idempotency_key"] == "k-1"

    @pytest.mark.parametrize("error", [
        APIError("Request timed out"),
        APIError("UNKNOWN_ERROR: Bad Gateway", status_code=502, error_code="UNKNOWN_ERROR"),
    ])
    def test_uncertain_submit_prints_the_key_to_retry_with(self, runner, job, places_file, error):
        job.submit_validate_job.side_effect = error
        result = runner.invoke(cli, ["validate", "--file", places_file, "--idempotency-key", "k-9"])
        assert result.exit_code == 1
        assert result.stdout == ""
        assert result.stderr.splitlines()[-1] == (
            "The job may have been created. To retry without creating a second one, "
            "run the same command with --idempotency-key k-9"
        )
        job.wait_for_job.assert_not_called()

    def test_uncertain_submit_hint_names_the_generated_key(self, runner, job, places_file):
        job.submit_validate_job.side_effect = APIError("Request timed out")
        result = runner.invoke(cli, ["validate", "--file", places_file])
        key = job.submit_validate_job.call_args.kwargs["idempotency_key"]
        assert result.stderr.splitlines()[-1].endswith(f"--idempotency-key {key}")

    def test_rejected_submit_prints_no_retry_hint(self, runner, job, places_file):
        job.submit_validate_job.side_effect = APIError(
            "QUOTA_EXCEEDED: quota_exceeded (4 credits needed)", status_code=402, error_code="QUOTA_EXCEEDED",
        )
        result = runner.invoke(cli, ["validate", "--file", places_file])
        assert result.exit_code == 1
        assert "--idempotency-key" not in result.stderr

    @pytest.mark.parametrize("command", ["validate", "enrich"])
    def test_key_without_file_is_a_usage_error(self, runner, job, command):
        result = runner.invoke(cli, [command, "Cafe", "--idempotency-key", "k-1"])
        assert result.exit_code == 2
        assert "--idempotency-key only applies with --file" in result.output
        job.validate.assert_not_called()
        job.enrich.assert_not_called()
