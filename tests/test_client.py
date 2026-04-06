import json
import pytest
import httpx
from voygr.client import Client, APIError


def mock_transport(handler):
    """Create an httpx mock transport from a request handler function."""
    return httpx.MockTransport(handler)


def json_response(data, status_code=200):
    return httpx.Response(status_code, json=data)


class TestClientAuth:
    def test_uses_provided_api_key(self):
        def handler(request):
            assert request.headers["X-API-Key"] == "pk_live_test"
            return json_response({"quota_limit": 100, "current_usage": 0, "remaining": 100, "percentage_used": 0.0, "period": "lifetime", "status": "active"})

        client = Client(api_key="pk_live_test", transport=mock_transport(handler))
        client.usage()

    def test_raises_without_api_key(self):
        client = Client(api_key=None, transport=mock_transport(lambda r: json_response({})))
        with pytest.raises(APIError, match="No API key configured"):
            client.usage()


class TestSignup:
    def test_signup_success(self):
        def handler(request):
            body = json.loads(request.content)
            assert body["email"] == "test@example.com"
            assert body["name"] == "Test User"
            assert request.url.path == "/signup"
            return json_response({"success": True, "message": "API key sent to your email"})

        client = Client(api_key=None, transport=mock_transport(handler))
        result = client.signup(email="test@example.com", name="Test User")
        assert result["success"] is True

    def test_signup_no_auth_header(self):
        def handler(request):
            assert "X-API-Key" not in request.headers
            return json_response({"success": True, "message": "API key sent to your email"})

        client = Client(api_key=None, transport=mock_transport(handler))
        client.signup(email="test@example.com", name="Test User")


class TestCheckBusiness:
    def test_check_success(self):
        def handler(request):
            body = json.loads(request.content)
            assert body["name"] == "Joe's Pizza"
            assert body["address"] == "123 Main St"
            assert request.url.path == "/v1/business-status"
            return json_response({
                "success": True,
                "existence_status": "exists",
                "open_closed_status": "open",
                "request_id": "req_abc123",
                "validation_timestamp": "2026-04-03T12:00:00Z",
            })

        client = Client(api_key="pk_live_test", transport=mock_transport(handler))
        result = client.check(name="Joe's Pizza", address="123 Main St")
        assert result["existence_status"] == "exists"
        assert result["open_closed_status"] == "open"

    def test_check_not_exists(self):
        def handler(request):
            return json_response({
                "success": True,
                "existence_status": "not_exists",
                "open_closed_status": "uncertain",
                "request_id": "req_def456",
                "validation_timestamp": "2026-04-03T12:00:00Z",
            })

        client = Client(api_key="pk_live_test", transport=mock_transport(handler))
        result = client.check(name="Fake Biz", address="000 Nowhere")
        assert result["existence_status"] == "not_exists"


class TestUsage:
    def test_usage_success(self):
        def handler(request):
            assert request.url.path == "/v1/usage"
            assert request.method == "GET"
            return json_response({
                "quota_limit": 100,
                "current_usage": 12,
                "remaining": 88,
                "percentage_used": 12.0,
                "period": "lifetime",
                "status": "active",
            })

        client = Client(api_key="pk_live_test", transport=mock_transport(handler))
        result = client.usage()
        assert result["remaining"] == 88


class TestErrorHandling:
    def test_401_raises_api_error(self):
        def handler(request):
            return json_response({"success": False, "error": "Missing API key", "error_code": "AUTHENTICATION_ERROR", "request_id": "req_err"}, status_code=401)

        client = Client(api_key="pk_live_bad", transport=mock_transport(handler))
        with pytest.raises(APIError) as exc_info:
            client.check(name="Test", address="Test")
        assert exc_info.value.status_code == 401
        assert "AUTHENTICATION_ERROR" in str(exc_info.value)

    def test_402_quota_exceeded(self):
        def handler(request):
            return json_response({"success": False, "error": "No validations remaining", "error_code": "QUOTA_EXCEEDED", "request_id": "req_err"}, status_code=402)

        client = Client(api_key="pk_live_test", transport=mock_transport(handler))
        with pytest.raises(APIError) as exc_info:
            client.check(name="Test", address="Test")
        assert exc_info.value.status_code == 402

    def test_429_rate_limit(self):
        def handler(request):
            return json_response({"success": False, "error": "Too many requests", "error_code": "RATE_LIMIT_ERROR", "request_id": "req_err"}, status_code=429)

        client = Client(api_key="pk_live_test", transport=mock_transport(handler))
        with pytest.raises(APIError) as exc_info:
            client.check(name="Test", address="Test")
        assert exc_info.value.status_code == 429

    def test_400_validation_error(self):
        def handler(request):
            return json_response({"success": False, "error": "Invalid request body", "error_code": "VALIDATION_ERROR", "request_id": "req_err"}, status_code=400)

        client = Client(api_key="pk_live_test", transport=mock_transport(handler))
        with pytest.raises(APIError) as exc_info:
            client.check(name="", address="")
        assert exc_info.value.status_code == 400

    def test_network_error_raises_api_error(self):
        def handler(request):
            raise httpx.ConnectError("Connection refused")

        client = Client(api_key="pk_live_test", transport=mock_transport(handler))
        with pytest.raises(APIError, match="Request failed"):
            client.check(name="Test", address="Test")

    def test_timeout_raises_api_error(self):
        def handler(request):
            raise httpx.ReadTimeout("Read timed out")

        client = Client(api_key="pk_live_test", transport=mock_transport(handler))
        with pytest.raises(APIError, match="timed out"):
            client.check(name="Test", address="Test")


    def test_non_json_error_response(self):
        def handler(request):
            return httpx.Response(502, text="<html>Bad Gateway</html>")

        client = Client(api_key="pk_live_test", transport=mock_transport(handler))
        with pytest.raises(APIError) as exc_info:
            client.check(name="Test", address="Test")
        assert exc_info.value.status_code == 502

    def test_context_manager(self):
        def handler(request):
            return json_response({"quota_limit": 100, "current_usage": 0, "remaining": 100, "percentage_used": 0.0, "period": "lifetime", "status": "active"})

        with Client(api_key="pk_live_test", transport=mock_transport(handler)) as client:
            result = client.usage()
            assert result["remaining"] == 100


class TestDebugOutput:
    def test_debug_prints_to_stderr(self, capsys):
        def handler(request):
            return json_response({"quota_limit": 100, "remaining": 88})

        client = Client(api_key="pk_live_test", debug=True, transport=mock_transport(handler))
        client.usage()
        captured = capsys.readouterr()
        assert "DEBUG" in captured.err
        assert "GET" in captured.err
        assert "/v1/usage" in captured.err

    def test_no_debug_by_default(self, capsys):
        def handler(request):
            return json_response({"quota_limit": 100, "remaining": 88})

        client = Client(api_key="pk_live_test", transport=mock_transport(handler))
        client.usage()
        captured = capsys.readouterr()
        assert captured.err == ""


class TestBaseUrl:
    def test_custom_base_url(self):
        def handler(request):
            assert str(request.url).startswith("https://staging.voygr.tech/")
            return json_response({"quota_limit": 100, "current_usage": 0, "remaining": 100, "percentage_used": 0.0, "period": "lifetime", "status": "active"})

        client = Client(api_key="pk_live_test", base_url="https://staging.voygr.tech", transport=mock_transport(handler))
        client.usage()
