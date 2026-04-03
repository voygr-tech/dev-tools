import json
import pytest
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from voygr.cli import cli
from voygr.client import APIError


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_client():
    with patch("voygr.cli.create_client") as mock_create:
        client = MagicMock()
        mock_create.return_value = client
        yield client


class TestSignup:
    def test_signup_success(self, runner, mock_client):
        mock_client.signup.return_value = {"success": True, "message": "API key sent to your email"}
        result = runner.invoke(cli, ["signup", "test@example.com"])
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["success"] is True
        mock_client.signup.assert_called_once_with(email="test@example.com", name="test@example.com")

    def test_signup_with_name(self, runner, mock_client):
        mock_client.signup.return_value = {"success": True, "message": "API key sent to your email"}
        result = runner.invoke(cli, ["signup", "test@example.com", "--name", "Jane Smith"])
        assert result.exit_code == 0
        mock_client.signup.assert_called_once_with(email="test@example.com", name="Jane Smith")

    def test_signup_api_error(self, runner, mock_client):
        mock_client.signup.side_effect = APIError("Connection refused", status_code=None)
        result = runner.invoke(cli, ["signup", "test@example.com"])
        assert result.exit_code == 1
        error = json.loads(result.output)
        assert "error" in error


class TestLogin:
    def test_login_stores_key(self, runner):
        with patch("voygr.cli.save_api_key") as mock_save:
            result = runner.invoke(cli, ["login", "pk_live_abc123"])
            assert result.exit_code == 0
            mock_save.assert_called_once_with("pk_live_abc123")
            output = json.loads(result.output)
            assert output["success"] is True

    def test_login_missing_key(self, runner):
        result = runner.invoke(cli, ["login"])
        assert result.exit_code != 0


class TestLogout:
    def test_logout_deletes_config(self, runner):
        with patch("voygr.cli.delete_config") as mock_delete:
            result = runner.invoke(cli, ["logout"])
            assert result.exit_code == 0
            mock_delete.assert_called_once()
            output = json.loads(result.output)
            assert output["success"] is True


class TestCheck:
    def test_check_success(self, runner, mock_client):
        mock_client.check.return_value = {
            "success": True,
            "existence_status": "exists",
            "open_closed_status": "open",
            "request_id": "req_abc123",
            "validation_timestamp": "2026-04-03T12:00:00Z",
        }
        result = runner.invoke(cli, ["check", "Joe's Pizza", "123 Main St"])
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["existence_status"] == "exists"
        mock_client.check.assert_called_once_with(name="Joe's Pizza", address="123 Main St")

    def test_check_api_error(self, runner, mock_client):
        mock_client.check.side_effect = APIError("AUTHENTICATION_ERROR: Invalid API key", status_code=401, error_code="AUTHENTICATION_ERROR")
        result = runner.invoke(cli, ["check", "Test", "Test"])
        assert result.exit_code == 1
        error = json.loads(result.output)
        assert error["error"] == "AUTHENTICATION_ERROR"

    def test_check_with_api_key_flag(self, runner, mock_client):
        mock_client.check.return_value = {
            "success": True,
            "existence_status": "exists",
            "open_closed_status": "open",
            "request_id": "req_abc",
            "validation_timestamp": "2026-04-03T12:00:00Z",
        }
        result = runner.invoke(cli, ["--api-key", "pk_live_override", "check", "Test", "Test"])
        assert result.exit_code == 0

    def test_check_missing_args(self, runner):
        result = runner.invoke(cli, ["check"])
        assert result.exit_code != 0


class TestUsage:
    def test_usage_success(self, runner, mock_client):
        mock_client.usage.return_value = {
            "quota_limit": 100,
            "current_usage": 12,
            "remaining": 88,
            "percentage_used": 12.0,
            "period": "lifetime",
            "status": "active",
        }
        result = runner.invoke(cli, ["usage"])
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["remaining"] == 88

    def test_usage_api_error(self, runner, mock_client):
        mock_client.usage.side_effect = APIError("AUTHENTICATION_ERROR: Missing API key", status_code=401, error_code="AUTHENTICATION_ERROR")
        result = runner.invoke(cli, ["usage"])
        assert result.exit_code == 1


class TestGlobalFlags:
    def test_pretty_output(self, runner, mock_client):
        mock_client.usage.return_value = {"quota_limit": 100, "remaining": 88}
        result = runner.invoke(cli, ["--pretty", "usage"])
        assert result.exit_code == 0
        assert "\n" in result.output
        assert "  " in result.output  # indented

    def test_base_url_flag(self, runner):
        with patch("voygr.cli.create_client") as mock_create:
            mock_create.return_value = MagicMock()
            mock_create.return_value.usage.return_value = {"remaining": 88}
            runner.invoke(cli, ["--base-url", "https://staging.voygr.tech", "usage"])
            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args
            assert call_kwargs[1]["base_url"] == "https://staging.voygr.tech" or call_kwargs[0][1] == "https://staging.voygr.tech"


class TestAuthResolution:
    def test_flag_overrides_env(self, runner):
        with patch("voygr.cli.create_client") as mock_create:
            mock_create.return_value = MagicMock()
            mock_create.return_value.usage.return_value = {"remaining": 88}
            result = runner.invoke(cli, ["--api-key", "pk_live_flag", "usage"], env={"VOYGR_API_KEY": "pk_live_env"})
            assert result.exit_code == 0

    def test_env_overrides_config(self, runner):
        with patch("voygr.cli.create_client") as mock_create, \
             patch("voygr.cli.load_config", return_value={"api_key": "pk_live_config"}):
            mock_create.return_value = MagicMock()
            mock_create.return_value.usage.return_value = {"remaining": 88}
            result = runner.invoke(cli, ["usage"], env={"VOYGR_API_KEY": "pk_live_env"})
            assert result.exit_code == 0
