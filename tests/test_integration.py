import json
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from voygr.cli import cli
from voygr.client import Client


class TestSignupToCheckFlow:
    """Test the full user journey: signup -> login -> check -> usage."""

    def test_full_flow(self, tmp_path):
        runner = CliRunner()
        config_dir = tmp_path / "voygr"

        # Step 1: Signup
        with patch("voygr.cli.create_client") as mock_create:
            client = MagicMock()
            client.signup.return_value = {"success": True, "message": "API key sent to your email"}
            mock_create.return_value.__enter__ = MagicMock(return_value=client)
            mock_create.return_value.__exit__ = MagicMock(return_value=False)
            result = runner.invoke(cli, ["signup", "test@example.com", "--name", "Test User"])
            assert result.exit_code == 0
            assert json.loads(result.output)["success"] is True

        # Step 2: Login
        with patch("voygr.cli.save_api_key") as mock_save:
            result = runner.invoke(cli, ["login", "pk_live_abc123"])
            assert result.exit_code == 0
            mock_save.assert_called_once_with("pk_live_abc123")

        # Step 3: Check a business
        with patch("voygr.cli.create_client") as mock_create, \
             patch("voygr.cli.resolve_api_key", return_value="pk_live_abc123"):
            client = MagicMock()
            client.check.return_value = {
                "success": True,
                "existence_status": "exists",
                "open_closed_status": "open",
                "request_id": "req_abc",
                "validation_timestamp": "2026-04-03T12:00:00Z",
            }
            mock_create.return_value.__enter__ = MagicMock(return_value=client)
            mock_create.return_value.__exit__ = MagicMock(return_value=False)
            result = runner.invoke(cli, ["check", "Joe's Pizza", "123 Main St"])
            assert result.exit_code == 0
            output = json.loads(result.output)
            assert output["existence_status"] == "exists"

        # Step 4: Check usage
        with patch("voygr.cli.create_client") as mock_create, \
             patch("voygr.cli.resolve_api_key", return_value="pk_live_abc123"):
            client = MagicMock()
            client.usage.return_value = {
                "quota_limit": 100,
                "current_usage": 1,
                "remaining": 99,
                "percentage_used": 1.0,
                "period": "lifetime",
                "status": "active",
            }
            mock_create.return_value.__enter__ = MagicMock(return_value=client)
            mock_create.return_value.__exit__ = MagicMock(return_value=False)
            result = runner.invoke(cli, ["usage"])
            assert result.exit_code == 0
            output = json.loads(result.output)
            assert output["remaining"] == 99


class TestLogoutFlow:
    def test_logout_then_check_fails(self, tmp_path):
        runner = CliRunner()

        # Logout
        with patch("voygr.cli.delete_config"):
            result = runner.invoke(cli, ["logout"])
            assert result.exit_code == 0

        # Check without auth should fail
        with patch("voygr.cli.create_client") as mock_create, \
             patch("voygr.cli.resolve_api_key", return_value=None):
            from voygr.client import APIError
            client = MagicMock()
            client.check.side_effect = APIError("No API key configured", error_code="client_error")
            mock_create.return_value.__enter__ = MagicMock(return_value=client)
            mock_create.return_value.__exit__ = MagicMock(return_value=False)
            result = runner.invoke(cli, ["check", "Test", "Test"])
            assert result.exit_code == 1


class TestErrorJsonFormat:
    """Verify error output is always valid JSON."""

    def test_api_error_is_json(self):
        runner = CliRunner()
        with patch("voygr.cli.create_client") as mock_create, \
             patch("voygr.cli.resolve_api_key", return_value="pk_live_test"):
            from voygr.client import APIError
            client = MagicMock()
            client.check.side_effect = APIError("QUOTA_EXCEEDED: No validations remaining", status_code=402, error_code="QUOTA_EXCEEDED")
            mock_create.return_value.__enter__ = MagicMock(return_value=client)
            mock_create.return_value.__exit__ = MagicMock(return_value=False)
            result = runner.invoke(cli, ["check", "Test", "Test"])
            error = json.loads(result.output)
            assert "error" in error
            assert "message" in error
