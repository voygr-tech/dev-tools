import json

import click
import httpx
import pytest
from unittest.mock import patch, MagicMock
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
        from voygr import __version__
        assert __version__ in result.output
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
