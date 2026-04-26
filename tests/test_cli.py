import csv
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
        mock_create.return_value.__enter__ = MagicMock(return_value=client)
        mock_create.return_value.__exit__ = MagicMock(return_value=False)
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
        error = json.loads(result.output)
        assert error["error"] == "RATE_LIMIT_ERROR"

    def test_recover_missing_email(self, runner):
        result = runner.invoke(cli, ["recover"])
        assert result.exit_code != 0


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
    def test_base_url_flag(self, runner):
        with patch("voygr.cli.create_client") as mock_create:
            client = MagicMock()
            client.usage.return_value = {"remaining": 88}
            mock_create.return_value.__enter__ = MagicMock(return_value=client)
            mock_create.return_value.__exit__ = MagicMock(return_value=False)
            runner.invoke(cli, ["--base-url", "https://staging.voygr.tech", "usage"])
            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args
            assert call_kwargs[1]["base_url"] == "https://staging.voygr.tech" or call_kwargs[0][1] == "https://staging.voygr.tech"


class TestOutputFormat:
    def test_default_is_json(self, runner, mock_client):
        mock_client.usage.return_value = {"quota_limit": 100, "remaining": 88}
        result = runner.invoke(cli, ["usage"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["remaining"] == 88

    def test_human_flag(self, runner, mock_client):
        mock_client.check.return_value = {
            "success": True,
            "existence_status": "exists",
            "open_closed_status": "open",
            "request_id": "req_abc",
            "validation_timestamp": "2026-04-03T12:00:00Z",
        }
        result = runner.invoke(cli, ["--human", "check", "Starbucks", "123 Main St"])
        assert result.exit_code == 0
        assert "exists" in result.output.lower()
        assert "open" in result.output.lower()
        with pytest.raises(json.JSONDecodeError):
            json.loads(result.output)

    def test_human_usage_output(self, runner, mock_client):
        mock_client.usage.return_value = {
            "quota_limit": 100,
            "current_usage": 12,
            "remaining": 88,
            "percentage_used": 12.0,
            "period": "lifetime",
            "status": "active",
        }
        result = runner.invoke(cli, ["--human", "usage"])
        assert result.exit_code == 0
        assert "88" in result.output
        assert "100" in result.output

    def test_human_error_output(self, runner, mock_client):
        mock_client.check.side_effect = APIError("Invalid API key", status_code=401, error_code="AUTHENTICATION_ERROR")
        result = runner.invoke(cli, ["--human", "check", "Test", "Test"])
        assert result.exit_code == 1
        assert "Invalid API key" in result.output

    def test_no_color_env(self, runner, mock_client):
        mock_client.usage.return_value = {"quota_limit": 100, "remaining": 88}
        result = runner.invoke(cli, ["--human", "usage"], env={"NO_COLOR": "1"})
        assert result.exit_code == 0
        assert "\033[" not in result.output


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


class TestAuthResolution:
    def test_flag_overrides_env(self, runner):
        with patch("voygr.cli.create_client") as mock_create:
            client = MagicMock()
            client.usage.return_value = {"remaining": 88}
            mock_create.return_value.__enter__ = MagicMock(return_value=client)
            mock_create.return_value.__exit__ = MagicMock(return_value=False)
            result = runner.invoke(cli, ["--api-key", "pk_live_flag", "usage"], env={"VOYGR_API_KEY": "pk_live_env"})
            assert result.exit_code == 0

    def test_env_overrides_config(self, runner):
        with patch("voygr.cli.create_client") as mock_create, \
             patch("voygr.cli.load_config", return_value={"api_key": "pk_live_config"}):
            client = MagicMock()
            client.usage.return_value = {"remaining": 88}
            mock_create.return_value.__enter__ = MagicMock(return_value=client)
            mock_create.return_value.__exit__ = MagicMock(return_value=False)
            result = runner.invoke(cli, ["usage"], env={"VOYGR_API_KEY": "pk_live_env"})
            assert result.exit_code == 0


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


class TestBatchCheck:
    def _write_csv(self, tmp_path, rows):
        path = tmp_path / "businesses.csv"
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["name", "address"])
            writer.writeheader()
            writer.writerows(rows)
        return str(path)

    def test_batch_check_from_csv(self, runner, mock_client, tmp_path):
        mock_client.check.return_value = {
            "success": True, "existence_status": "exists",
            "open_closed_status": "open", "request_id": "req_1",
            "validation_timestamp": "2026-04-03T12:00:00Z",
        }
        path = self._write_csv(tmp_path, [
            {"name": "Biz A", "address": "123 Main St"},
            {"name": "Biz B", "address": "456 Oak Ave"},
        ])
        result = runner.invoke(cli, ["check", "--file", path])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert len(lines) == 2
        for line in lines:
            data = json.loads(line)
            assert data["existence_status"] == "exists"

    def test_batch_check_with_errors(self, runner, mock_client, tmp_path):
        call_count = 0
        def side_effect(name, address):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise APIError("Quota exceeded", status_code=402, error_code="QUOTA_EXCEEDED")
            return {"success": True, "existence_status": "exists",
                    "open_closed_status": "open", "request_id": "req_1",
                    "validation_timestamp": "2026-04-03T12:00:00Z"}
        mock_client.check.side_effect = side_effect
        path = self._write_csv(tmp_path, [
            {"name": "Biz A", "address": "123 Main St"},
            {"name": "Biz B", "address": "456 Oak Ave"},
            {"name": "Biz C", "address": "789 Pine Rd"},
        ])
        result = runner.invoke(cli, ["check", "--file", path])
        lines = result.output.strip().split("\n")
        assert len(lines) == 3
        error_line = json.loads(lines[1])
        assert error_line["error"] == "QUOTA_EXCEEDED"
        assert error_line["input_name"] == "Biz B"

    def test_batch_check_empty_csv(self, runner, tmp_path):
        path = tmp_path / "empty.csv"
        path.write_text("name,address\n")
        result = runner.invoke(cli, ["check", "--file", str(path)])
        assert result.exit_code != 0

    def test_batch_check_missing_columns(self, runner, tmp_path):
        path = tmp_path / "bad.csv"
        path.write_text("foo,bar\na,b\n")
        result = runner.invoke(cli, ["check", "--file", str(path)])
        assert result.exit_code != 0

    def test_batch_check_mutex_with_args(self, runner, tmp_path):
        path = tmp_path / "test.csv"
        path.write_text("name,address\nA,B\n")
        result = runner.invoke(cli, ["check", "--file", str(path), "Name", "Addr"])
        assert result.exit_code != 0

    def test_batch_check_no_args_no_file(self, runner):
        result = runner.invoke(cli, ["check"])
        assert result.exit_code != 0
