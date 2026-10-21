import json
from unittest.mock import patch
import pytest
import httpx
from voygr.client import (
    DEFAULT_BASE_URL,
    STANDARD_ATTRIBUTES,
    _RATE_LIMIT_ONLY,
    _RETRYABLE,
    APIError,
    Client,
)

USAGE = {"quota_limit": 100, "current_usage": 0, "remaining": 100, "percentage_used": 0.0, "period": "lifetime", "status": "active"}
OK = (200, {"ok": True})


def mock_transport(handler):
    """Create an httpx mock transport from a request handler function."""
    return httpx.MockTransport(handler)


def json_response(data, status_code=200):
    return httpx.Response(status_code, json=data)


def scripted(*steps):
    """Handler that plays one step per call (the last repeats) and records requests.

    A step is `(status, json_body)`, `(status, json_body, headers)` or an exception to raise.
    """
    calls = []

    def handler(request):
        calls.append(request)
        step = steps[min(len(calls), len(steps)) - 1]
        if isinstance(step, Exception):
            raise step
        status, data, *rest = step
        return httpx.Response(status, json=data, headers=rest[0] if rest else None)

    handler.calls = calls
    return handler


def make_client(handler, api_key="pk_live_test", **kwargs):
    return Client(api_key=api_key, transport=mock_transport(handler), **kwargs)


def sent_json(request):
    return json.loads(request.content)


def read_timeout(request):
    return request.extensions["timeout"]["read"]


@pytest.fixture
def mock_sleep():
    """Patch the sleep tenacity uses between attempts."""
    with patch("tenacity.nap.time.sleep", return_value=None) as sleep:
        yield sleep


class TestClientAuth:
    def test_uses_provided_api_key(self):
        def handler(request):
            assert request.headers["X-API-Key"] == "pk_live_test"
            return json_response(USAGE)

        client = Client(api_key="pk_live_test", transport=mock_transport(handler))
        client.usage()

    def test_raises_without_api_key(self):
        client = Client(api_key=None, transport=mock_transport(lambda r: json_response({})))
        with pytest.raises(APIError, match="No API key configured"):
            client.usage()

    def test_validate_raises_without_api_key_and_sends_nothing(self):
        handler = scripted(OK)
        client = make_client(handler, api_key=None)
        with pytest.raises(APIError, match="No API key configured"):
            client.validate("X")
        assert handler.calls == []

    def test_enrich_raises_without_api_key_and_sends_nothing(self):
        handler = scripted(OK)
        client = make_client(handler, api_key=None)
        with pytest.raises(APIError, match="No API key configured"):
            client.enrich("X")
        assert handler.calls == []


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


class TestRecover:
    def test_recover_success(self):
        def handler(request):
            body = json.loads(request.content)
            assert body == {"email": "test@example.com"}
            assert request.url.path == "/recover"
            assert request.method == "POST"
            return json_response({
                "success": True,
                "message": "If an account exists for that email, a recovery link has been sent.",
            })

        client = Client(api_key=None, transport=mock_transport(handler))
        result = client.recover(email="test@example.com")
        assert result["success"] is True
        assert "recovery link" in result["message"]

    def test_recover_no_auth_header(self):
        def handler(request):
            assert "X-API-Key" not in request.headers
            return json_response({"success": True, "message": "ok"})

        client = Client(api_key=None, transport=mock_transport(handler))
        client.recover(email="test@example.com")

    def test_recover_does_not_send_existing_key(self):
        def handler(request):
            assert "X-API-Key" not in request.headers
            return json_response({"success": True, "message": "ok"})

        client = Client(api_key="pk_live_existing", transport=mock_transport(handler))
        client.recover(email="test@example.com")

    def test_recover_429_rate_limited(self):
        def handler(request):
            return json_response(
                {"success": False, "error": "Too many requests", "error_code": "RATE_LIMIT_ERROR"},
                status_code=429,
            )

        client = Client(api_key=None, transport=mock_transport(handler))
        with pytest.raises(APIError) as exc_info:
            client.recover(email="test@example.com")
        assert exc_info.value.status_code == 429

    def test_recover_400_validation_error(self):
        def handler(request):
            return json_response(
                {"success": False, "error": "Invalid input provided", "error_code": "VALIDATION_ERROR"},
                status_code=400,
            )

        client = Client(api_key=None, transport=mock_transport(handler))
        with pytest.raises(APIError) as exc_info:
            client.recover(email="not-an-email")
        assert exc_info.value.status_code == 400
        assert exc_info.value.error_code == "VALIDATION_ERROR"

    def test_recover_retries_429(self, mock_sleep):
        handler = scripted((429, {"error": "Slow down", "error_code": "RATE_LIMIT_ERROR"}), OK)
        client = make_client(handler, api_key=None, retries=2)
        assert client.recover("a@b.co") == {"ok": True}
        assert len(handler.calls) == 2

    def test_recover_does_not_retry_500(self, mock_sleep):
        handler = scripted((500, {"error": "Boom", "error_code": "SERVER_ERROR"}), OK)
        client = make_client(handler, api_key=None, retries=3)
        with pytest.raises(APIError) as exc_info:
            client.recover("a@b.co")
        assert exc_info.value.status_code == 500
        assert len(handler.calls) == 1


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

    def test_usage_timeout_is_90(self):
        handler = scripted(OK)
        make_client(handler).usage()
        assert read_timeout(handler.calls[0]) == 90.0


class TestErrorHandling:
    def test_401_raises_api_error(self):
        def handler(request):
            return json_response({"success": False, "error": "Missing API key", "error_code": "AUTHENTICATION_ERROR", "request_id": "req_err"}, status_code=401)

        client = Client(api_key="pk_live_bad", transport=mock_transport(handler))
        with pytest.raises(APIError) as exc_info:
            client.validate("Test")
        assert exc_info.value.status_code == 401
        assert "AUTHENTICATION_ERROR" in str(exc_info.value)

    def test_402_quota_exceeded(self):
        def handler(request):
            return json_response(
                {"detail": {"error": "quota_exceeded", "needed_credits": 12, "checkout_url": "/checkout/buy"}},
                status_code=402,
            )

        client = Client(api_key="pk_live_test", transport=mock_transport(handler))
        with pytest.raises(APIError) as exc_info:
            client.validate("Test")
        assert exc_info.value.status_code == 402
        assert exc_info.value.error_code == "QUOTA_EXCEEDED"
        assert "12 credits needed" in str(exc_info.value)

    def test_429_rate_limit(self):
        def handler(request):
            return json_response({"success": False, "error": "Too many requests", "error_code": "RATE_LIMIT_ERROR", "request_id": "req_err"}, status_code=429)

        client = Client(api_key="pk_live_test", transport=mock_transport(handler))
        with pytest.raises(APIError) as exc_info:
            client.validate("Test")
        assert exc_info.value.status_code == 429

    def test_400_validation_error(self):
        def handler(request):
            return json_response({"success": False, "error": "Invalid request body", "error_code": "VALIDATION_ERROR", "request_id": "req_err"}, status_code=400)

        client = Client(api_key="pk_live_test", transport=mock_transport(handler))
        with pytest.raises(APIError) as exc_info:
            client.enrich("")
        assert exc_info.value.status_code == 400

    def test_network_error_raises_api_error(self):
        def handler(request):
            raise httpx.ConnectError("Connection refused")

        client = Client(api_key="pk_live_test", transport=mock_transport(handler))
        with pytest.raises(APIError, match="Request failed"):
            client.validate("Test")

    def test_timeout_raises_api_error(self):
        def handler(request):
            raise httpx.ReadTimeout("Read timed out")

        client = Client(api_key="pk_live_test", transport=mock_transport(handler))
        with pytest.raises(APIError, match="timed out"):
            client.validate("Test")

    def test_non_json_error_response(self):
        def handler(request):
            return httpx.Response(502, text="<html>Bad Gateway</html>")

        client = Client(api_key="pk_live_test", transport=mock_transport(handler))
        with pytest.raises(APIError) as exc_info:
            client.validate("Test")
        assert exc_info.value.status_code == 502

    def test_non_json_error_uses_reason_phrase(self):
        client = make_client(lambda r: httpx.Response(502, text="<html>Bad Gateway</html>"))
        with pytest.raises(APIError) as exc_info:
            client.usage()
        assert exc_info.value.error_code == "UNKNOWN_ERROR"
        assert "Bad Gateway" in str(exc_info.value)

    def test_non_json_error_is_retried_when_status_is_retryable(self, mock_sleep):
        calls = []

        def handler(request):
            calls.append(request)
            if len(calls) == 1:
                return httpx.Response(502, text="<html>Bad Gateway</html>")
            return json_response({"ok": True})

        assert make_client(handler, retries=1).usage() == {"ok": True}
        assert len(calls) == 2

    def test_invalid_json_on_success_raises(self):
        client = make_client(lambda r: httpx.Response(200, text="not json"))
        with pytest.raises(APIError, match="Invalid JSON"):
            client.usage()

    def test_context_manager(self):
        def handler(request):
            return json_response(USAGE)

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

    def test_debug_prints_on_timeout(self, capsys):
        client = make_client(scripted(httpx.ReadTimeout("slow")), debug=True)
        with pytest.raises(APIError):
            client.usage()
        err = capsys.readouterr().err
        assert "DEBUG GET" in err and "ERR" in err

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
            return json_response(USAGE)

        client = Client(api_key="pk_live_test", base_url="https://staging.voygr.tech", transport=mock_transport(handler))
        client.usage()

    def test_trailing_slash_is_stripped(self):
        handler = scripted(OK)
        make_client(handler, base_url="https://staging.voygr.tech/").usage()
        assert str(handler.calls[0].url) == "https://staging.voygr.tech/v1/usage"


class TestRetry:
    def test_retry_on_429(self, mock_sleep):
        call_count = 0
        def handler(request):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return json_response({"success": False, "error": "Rate limited", "error_code": "RATE_LIMIT_ERROR"}, status_code=429)
            return json_response({"quota_limit": 100, "remaining": 88})
        client = Client(api_key="pk_live_test", retries=3, transport=mock_transport(handler))
        result = client.usage()
        assert result["remaining"] == 88
        assert call_count == 3

    def test_retry_on_500(self, mock_sleep):
        call_count = 0
        def handler(request):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                return json_response({"success": False, "error": "Server error", "error_code": "SERVER_ERROR"}, status_code=500)
            return json_response({"quota_limit": 100, "remaining": 88})
        client = Client(api_key="pk_live_test", retries=3, transport=mock_transport(handler))
        result = client.usage()
        assert result["remaining"] == 88
        assert call_count == 2

    def test_no_retry_on_400(self):
        call_count = 0
        def handler(request):
            nonlocal call_count
            call_count += 1
            return json_response({"success": False, "error": "Bad request", "error_code": "VALIDATION_ERROR"}, status_code=400)
        client = Client(api_key="pk_live_test", retries=3, transport=mock_transport(handler))
        with pytest.raises(APIError) as exc_info:
            client.validate("X")
        assert exc_info.value.status_code == 400
        assert call_count == 1

    def test_no_retry_on_401(self):
        call_count = 0
        def handler(request):
            nonlocal call_count
            call_count += 1
            return json_response({"success": False, "error": "Unauthorized", "error_code": "AUTHENTICATION_ERROR"}, status_code=401)
        client = Client(api_key="pk_live_bad", retries=3, transport=mock_transport(handler))
        with pytest.raises(APIError) as exc_info:
            client.usage()
        assert exc_info.value.status_code == 401
        assert call_count == 1

    def test_retries_exhausted(self, mock_sleep):
        call_count = 0
        def handler(request):
            nonlocal call_count
            call_count += 1
            return json_response({"success": False, "error": "Rate limited", "error_code": "RATE_LIMIT_ERROR"}, status_code=429)
        client = Client(api_key="pk_live_test", retries=3, transport=mock_transport(handler))
        with pytest.raises(APIError) as exc_info:
            client.usage()
        assert exc_info.value.status_code == 429
        assert call_count == 4  # 1 initial + 3 retries

    def test_no_retry_by_default(self):
        call_count = 0
        def handler(request):
            nonlocal call_count
            call_count += 1
            return json_response({"success": False, "error": "Rate limited", "error_code": "RATE_LIMIT_ERROR"}, status_code=429)
        client = Client(api_key="pk_live_test", transport=mock_transport(handler))
        with pytest.raises(APIError):
            client.usage()
        assert call_count == 1

    def test_connection_error_not_retried(self, mock_sleep):
        handler = scripted(httpx.ConnectError("Connection refused"))
        client = make_client(handler, retries=3)
        with pytest.raises(APIError, match="Request failed"):
            client.usage()
        assert len(handler.calls) == 1
        mock_sleep.assert_not_called()

    def test_retry_sets(self):
        assert _RATE_LIMIT_ONLY == frozenset({429})
        assert _RETRYABLE == frozenset({429, 500, 502, 503, 504})

    def test_request_honours_retry_on_and_timeout(self, mock_sleep):
        handler = scripted((503, {"error": "Down", "error_code": "UNAVAILABLE"}), OK)
        client = make_client(handler, retries=1)
        result = client._request("GET", "/v1/jobs/b1", retry_on=_RETRYABLE, timeout=12.5)
        assert result == {"ok": True}
        assert len(handler.calls) == 2
        assert read_timeout(handler.calls[0]) == 12.5

    def test_request_retry_on_can_exclude_status(self, mock_sleep):
        handler = scripted((503, {"error": "Down", "error_code": "UNAVAILABLE"}), OK)
        client = make_client(handler, retries=3)
        with pytest.raises(APIError) as exc_info:
            client._request("GET", "/v1/jobs/b1", retry_on=_RATE_LIMIT_ONLY, timeout=5.0)
        assert exc_info.value.status_code == 503
        assert len(handler.calls) == 1

    def test_request_passes_httpx_kwargs_and_merges_headers(self):
        handler = scripted(OK)
        client = make_client(handler)
        client._request(
            "POST", "/v1/jobs/validate", retry_on=_RETRYABLE, timeout=5.0,
            headers={"Idempotency-Key": "k-1"}, params={"a": "1"}, json={"rows": []},
        )
        request = handler.calls[0]
        assert request.headers["X-API-Key"] == "pk_live_test"
        assert request.headers["Idempotency-Key"] == "k-1"
        assert request.url.params["a"] == "1"
        assert sent_json(request) == {"rows": []}

    def test_request_without_auth_sends_no_key(self):
        handler = scripted(OK)
        make_client(handler)._request("GET", "/v1/pricing", auth=False, retry_on=_RETRYABLE, timeout=5.0)
        assert "X-API-Key" not in handler.calls[0].headers


# New behaviour on the Places API


def test_standard_attributes_are_the_ten_names_in_order():
    assert STANDARD_ATTRIBUTES == (
        "opening_hours", "phone", "website", "facebook", "instagram",
        "tiktok", "x", "email", "existence", "open_closed",
    )


def test_default_base_url():
    handler = scripted(OK)
    Client(api_key="pk_live_test", transport=mock_transport(handler)).usage()
    assert DEFAULT_BASE_URL == "https://api.voygr.tech"
    assert str(handler.calls[0].url) == "https://api.voygr.tech/v1/usage"


def test_validate_sends_body():
    handler = scripted(OK)
    make_client(handler).validate("Blue Bottle Coffee", address="66 Mint St", country="US")
    request = handler.calls[0]
    assert request.method == "POST"
    assert request.url.path == "/v1/validate"
    assert request.headers["X-API-Key"] == "pk_live_test"
    assert sent_json(request) == {"poi_name": "Blue Bottle Coffee", "address": "66 Mint St", "country": "US"}


def test_validate_drops_none_fields():
    handler = scripted(OK)
    make_client(handler).validate("X", address=None)
    assert sent_json(handler.calls[0]) == {"poi_name": "X"}


def test_validate_keeps_falsy_values_that_are_not_none():
    handler = scripted(OK)
    make_client(handler).validate("X", latitude=0, longitude=0.0, street="")
    assert sent_json(handler.calls[0]) == {"poi_name": "X", "latitude": 0, "longitude": 0.0, "street": ""}


def test_validate_returns_response_body():
    handler = scripted((200, {"existence": {"status": "exists"}}))
    assert make_client(handler).validate("X") == {"existence": {"status": "exists"}}


def test_enrich_sends_to_enrich_endpoint():
    handler = scripted(OK)
    make_client(handler).enrich("X")
    request = handler.calls[0]
    assert request.method == "POST"
    assert request.url.path == "/v1/enrich"
    assert request.headers["X-API-Key"] == "pk_live_test"
    assert sent_json(request) == {"poi_name": "X"}


def test_enrich_default_attributes_omitted():
    handler = scripted(OK)
    make_client(handler).enrich("X")
    assert "attributes" not in sent_json(handler.calls[0])


def test_enrich_sends_attributes_and_specs():
    attributes = ["phone", {"name": "wheelchair_accessible", "description": "Step-free?"}]
    handler = scripted(OK)
    make_client(handler).enrich("X", attributes=attributes)
    assert sent_json(handler.calls[0])["attributes"] == attributes


def test_enrich_passthrough_fields():
    handler = scripted(OK)
    make_client(handler).enrich("X", verify_name=True, sample=None)
    body = sent_json(handler.calls[0])
    assert body["verify_name"] is True
    assert "sample" not in body


@pytest.mark.parametrize("attributes", [
    None,
    ["phone"],
    ["x", "email"],
    list(STANDARD_ATTRIBUTES),
])
def test_enrich_timeout_standard_is_90(attributes):
    handler = scripted(OK)
    make_client(handler).enrich("X", attributes=attributes)
    assert read_timeout(handler.calls[0]) == 90.0


@pytest.mark.parametrize("attributes", [
    ["phone", "owners"],
    [{"name": "x1"}],
    ["wheelchair_accessible"],
    ["phone", {"name": "parking", "description": "Is there parking?"}],
])
def test_enrich_timeout_research_is_3700(attributes):
    handler = scripted(OK)
    make_client(handler).enrich("X", attributes=attributes)
    assert read_timeout(handler.calls[0]) == 3700.0


def test_validate_timeout_is_90():
    handler = scripted(OK)
    make_client(handler).validate("X")
    assert read_timeout(handler.calls[0]) == 90.0


def test_signup_sends_src_when_given():
    handler = scripted(OK)
    make_client(handler, api_key=None).signup("a@b.co", "A", src="voygr-cli")
    request = handler.calls[0]
    assert request.url.path == "/signup"
    assert "X-API-Key" not in request.headers
    assert sent_json(request) == {"email": "a@b.co", "name": "A", "src": "voygr-cli"}


def test_signup_omits_src_by_default():
    handler = scripted(OK)
    make_client(handler, api_key=None).signup("a@b.co", "A")
    assert sent_json(handler.calls[0]) == {"email": "a@b.co", "name": "A"}


def test_signup_timeout_is_90():
    handler = scripted(OK)
    make_client(handler, api_key=None).signup("a@b.co", "A")
    assert read_timeout(handler.calls[0]) == 90.0


def test_pricing_needs_no_key():
    handler = scripted((200, {"validate": {"credits": 1}}))
    result = Client(api_key=None, transport=mock_transport(handler)).pricing()
    request = handler.calls[0]
    assert result == {"validate": {"credits": 1}}
    assert request.method == "GET"
    assert request.url.path == "/v1/pricing"
    assert "X-API-Key" not in request.headers
    assert read_timeout(request) == 90.0


def test_pricing_does_not_send_existing_key():
    handler = scripted(OK)
    make_client(handler).pricing()
    assert "X-API-Key" not in handler.calls[0].headers


def test_validate_retries_429(mock_sleep):
    handler = scripted((429, {"error": "Slow down", "error_code": "RATE_LIMIT_ERROR"}), OK)
    result = make_client(handler, retries=2).validate("X")
    assert result == {"ok": True}
    assert len(handler.calls) == 2


def test_validate_gives_up_after_retries_on_429(mock_sleep):
    handler = scripted((429, {"error": "Slow down", "error_code": "RATE_LIMIT_ERROR"}))
    with pytest.raises(APIError) as exc_info:
        make_client(handler, retries=2).validate("X")
    assert exc_info.value.status_code == 429
    assert len(handler.calls) == 3


def test_validate_does_not_retry_500(mock_sleep):
    handler = scripted((500, {"error": "Boom", "error_code": "SERVER_ERROR"}), OK)
    with pytest.raises(APIError) as exc_info:
        make_client(handler, retries=3).validate("X")
    assert exc_info.value.status_code == 500
    assert len(handler.calls) == 1
    mock_sleep.assert_not_called()


def test_enrich_retries_429(mock_sleep):
    handler = scripted((429, {"error": "Slow down", "error_code": "RATE_LIMIT_ERROR"}), OK)
    assert make_client(handler, retries=1).enrich("X") == {"ok": True}
    assert len(handler.calls) == 2


def test_enrich_does_not_retry_503(mock_sleep):
    handler = scripted((503, {"error": "Down", "error_code": "UNAVAILABLE"}), OK)
    with pytest.raises(APIError) as exc_info:
        make_client(handler, retries=3).enrich("X", attributes=["phone"])
    assert exc_info.value.status_code == 503
    assert len(handler.calls) == 1


def test_signup_retries_429(mock_sleep):
    handler = scripted((429, {"error": "Slow down", "error_code": "RATE_LIMIT_ERROR"}), OK)
    assert make_client(handler, api_key=None, retries=1).signup("a@b.co", "A") == {"ok": True}
    assert len(handler.calls) == 2


def test_signup_does_not_retry_500(mock_sleep):
    handler = scripted((500, {"error": "Boom", "error_code": "SERVER_ERROR"}), OK)
    with pytest.raises(APIError) as exc_info:
        make_client(handler, api_key=None, retries=3).signup("a@b.co", "A")
    assert exc_info.value.status_code == 500
    assert len(handler.calls) == 1


def test_usage_retries_500(mock_sleep):
    handler = scripted(
        (500, {"error": "Boom", "error_code": "SERVER_ERROR"}),
        (502, {"error": "Bad gateway", "error_code": "SERVER_ERROR"}),
        OK,
    )
    assert make_client(handler, retries=3).usage() == {"ok": True}
    assert len(handler.calls) == 3


def test_pricing_retries_503(mock_sleep):
    handler = scripted((503, {"error": "Down", "error_code": "UNAVAILABLE"}), OK)
    assert make_client(handler, api_key=None, retries=1).pricing() == {"ok": True}
    assert len(handler.calls) == 2


def test_retry_after_honoured(mock_sleep):
    handler = scripted((429, {"error": "Slow down", "error_code": "RATE_LIMIT_ERROR"}, {"Retry-After": "7"}), OK)
    make_client(handler, retries=1).validate("X")
    mock_sleep.assert_called_once_with(7)


def test_retry_after_capped_at_60(mock_sleep):
    handler = scripted((429, {"error": "Slow down", "error_code": "RATE_LIMIT_ERROR"}, {"Retry-After": "600"}), OK)
    make_client(handler, retries=1).validate("X")
    mock_sleep.assert_called_once_with(60)


def test_retry_after_zero_is_honoured(mock_sleep):
    handler = scripted((429, {"error": "Slow down", "error_code": "RATE_LIMIT_ERROR"}, {"Retry-After": "0"}), OK)
    make_client(handler, retries=1).validate("X")
    mock_sleep.assert_called_once_with(0)


def test_retry_after_honoured_on_retryable_5xx(mock_sleep):
    handler = scripted((503, {"error": "Down", "error_code": "UNAVAILABLE"}, {"Retry-After": "3"}), OK)
    make_client(handler, retries=1).usage()
    mock_sleep.assert_called_once_with(3)


@pytest.mark.parametrize("header", ["Wed, 21 Oct 2026 07:28:00 GMT", "soon", "-5", "nan", ""])
def test_unusable_retry_after_falls_back_to_backoff(mock_sleep, header):
    handler = scripted((429, {"error": "Slow down", "error_code": "RATE_LIMIT_ERROR"}, {"Retry-After": header}), OK)
    make_client(handler, retries=1).validate("X")
    (delay,), _ = mock_sleep.call_args
    assert 1 <= delay <= 3  # first backoff: initial 1 s plus up to 2 s jitter


def test_missing_retry_after_falls_back_to_backoff(mock_sleep):
    handler = scripted((429, {"error": "Slow down", "error_code": "RATE_LIMIT_ERROR"}), OK)
    make_client(handler, retries=1).validate("X")
    (delay,), _ = mock_sleep.call_args
    assert 1 <= delay <= 3


def test_backoff_never_exceeds_10_seconds(mock_sleep):
    handler = scripted((429, {"error": "Slow down", "error_code": "RATE_LIMIT_ERROR"}))
    with pytest.raises(APIError):
        make_client(handler, retries=8).validate("X")
    delays = [call.args[0] for call in mock_sleep.call_args_list]
    assert len(delays) == 8
    assert max(delays) <= 10


def test_timeout_not_retried(mock_sleep):
    handler = scripted(httpx.ReadTimeout("Read timed out"))
    with pytest.raises(APIError, match="Request timed out"):
        make_client(handler, retries=3).usage()
    assert len(handler.calls) == 1
    mock_sleep.assert_not_called()


def test_422_detail_list_message():
    handler = scripted((422, {"detail": [{"loc": ["body", "poi_name"], "msg": "Field required", "type": "missing"}]}))
    with pytest.raises(APIError) as exc_info:
        make_client(handler).validate("X")
    assert exc_info.value.status_code == 422
    assert exc_info.value.error_code == "VALIDATION_ERROR"
    assert "body.poi_name: Field required" in str(exc_info.value)


def test_422_detail_list_joins_several_entries():
    handler = scripted((422, {"detail": [
        {"loc": ["body", "poi_name"], "msg": "Field required"},
        {"loc": ["body", "latitude"], "msg": "Input should be less than or equal to 90"},
    ]}))
    with pytest.raises(APIError) as exc_info:
        make_client(handler).validate("X")
    assert "body.poi_name: Field required; body.latitude: Input should be less than or equal to 90" in str(exc_info.value)


def test_422_detail_entry_without_loc_keeps_message():
    handler = scripted((422, {"detail": [{"msg": "Value error"}]}))
    with pytest.raises(APIError) as exc_info:
        make_client(handler).validate("X")
    assert exc_info.value.error_code == "VALIDATION_ERROR"
    assert "Value error" in str(exc_info.value)


def test_detail_string_message():
    handler = scripted((403, {"detail": "Key lacks the enrich entitlement"}))
    with pytest.raises(APIError) as exc_info:
        make_client(handler).enrich("X")
    assert exc_info.value.status_code == 403
    assert exc_info.value.error_code == "UNKNOWN_ERROR"
    assert "Key lacks the enrich entitlement" in str(exc_info.value)


def fail_with(status, body, call=lambda client: client.validate("X")):
    """The APIError a scripted error response raises."""
    with pytest.raises(APIError) as exc_info:
        call(make_client(scripted((status, body))))
    return exc_info.value


@pytest.mark.parametrize("message", [
    "invalid API key",
    "Authorization: Bearer <session> or X-API-Key required",
])
def test_401_nested_detail_is_an_authentication_error(message):
    error = fail_with(401, {"detail": {"error": message}})
    assert error.status_code == 401
    assert error.error_code == "AUTHENTICATION_ERROR"
    assert str(error) == f"AUTHENTICATION_ERROR: {message}"


def test_402_nested_detail_is_quota_exceeded_with_the_credits_needed():
    error = fail_with(402, {"detail": {"error": "quota_exceeded", "needed_credits": 12, "checkout_url": "/checkout/buy"}})
    assert error.status_code == 402
    assert error.error_code == "QUOTA_EXCEEDED"
    assert str(error) == "QUOTA_EXCEEDED: quota_exceeded (12 credits needed)"


def test_402_one_credit_needed_is_singular():
    error = fail_with(402, {"detail": {"error": "quota_exceeded", "needed_credits": 1}})
    assert str(error).endswith("(1 credit needed)")


def test_402_zero_credits_needed_is_still_shown():
    error = fail_with(402, {"detail": {"error": "quota_exceeded", "needed_credits": 0}})
    assert str(error).endswith("(0 credits needed)")


@pytest.mark.parametrize("status,code", [(403, "FORBIDDEN"), (429, "RATE_LIMIT_ERROR")])
def test_nested_detail_with_a_sentence_takes_its_code_from_the_status(status, code):
    error = fail_with(status, {"detail": {"error": "Key lacks the enrich entitlement"}})
    assert error.status_code == status
    assert error.error_code == code
    assert "Key lacks the enrich entitlement" in str(error)


def test_nested_detail_snake_case_error_becomes_the_code():
    error = fail_with(403, {"detail": {"error": "entitlement_required"}})
    assert error.error_code == "ENTITLEMENT_REQUIRED"


@pytest.mark.parametrize("error", ["Quota_Exceeded", "_quota", "1quota", "quota-exceeded", "quota exceeded", "quota_exceédéd"])
def test_nested_detail_error_that_is_not_snake_case_takes_its_code_from_the_status(error):
    err = fail_with(403, {"detail": {"error": error}})
    assert err.error_code == "FORBIDDEN"
    assert str(err) == f"FORBIDDEN: {error}"


@pytest.mark.parametrize("error", ["a", "a1", "ab_c2", "a_"])
def test_nested_detail_short_snake_case_errors_are_codes(error):
    assert fail_with(418, {"detail": {"error": error}}).error_code == error.upper()


def test_nested_detail_error_code_wins_over_error():
    error = fail_with(402, {"detail": {"error": "quota_exceeded", "error_code": "CUSTOM_CODE", "message": "Top up"}})
    assert error.error_code == "CUSTOM_CODE"
    assert str(error) == "CUSTOM_CODE: Top up"


def test_nested_detail_message_wins_over_error():
    error = fail_with(429, {"detail": {"error": "rate_limited", "message": "Slow down"}})
    assert error.error_code == "RATE_LIMITED"
    assert str(error) == "RATE_LIMITED: Slow down"


@pytest.mark.parametrize("status", [400, 404, 409, 500])
def test_nested_detail_on_an_unmapped_status_is_unknown_error(status):
    error = fail_with(status, {"detail": {"error": "Something odd happened"}})
    assert error.status_code == status
    assert error.error_code == "UNKNOWN_ERROR"
    assert "Something odd happened" in str(error)


def test_nested_detail_without_error_or_message_uses_the_reason_phrase():
    error = fail_with(401, {"detail": {}})
    assert error.error_code == "AUTHENTICATION_ERROR"
    assert str(error) == "AUTHENTICATION_ERROR: Unauthorized"


def test_nested_detail_credits_needed_without_a_message_keeps_the_reason_phrase():
    error = fail_with(402, {"detail": {"needed_credits": 3}})
    assert error.error_code == "QUOTA_EXCEEDED"
    assert str(error) == "QUOTA_EXCEEDED: Payment Required (3 credits needed)"


def test_nested_detail_error_that_is_not_text_is_not_printed_raw():
    error = fail_with(401, {"detail": {"error": {"nested": True}}})
    assert error.error_code == "AUTHENTICATION_ERROR"
    assert str(error) == "AUTHENTICATION_ERROR: Unauthorized"


def test_nested_429_detail_is_still_retried(mock_sleep):
    handler = scripted((429, {"detail": {"error": "rate limit exceeded"}}), OK)
    assert make_client(handler, retries=1).validate("X") == {"ok": True}
    assert len(handler.calls) == 2


def test_error_body_without_known_fields_uses_reason_phrase():
    handler = scripted((418, {"unexpected": True}))
    with pytest.raises(APIError) as exc_info:
        make_client(handler).validate("X")
    assert exc_info.value.status_code == 418
    assert exc_info.value.error_code == "UNKNOWN_ERROR"
    assert "I'm a teapot" in str(exc_info.value)


def test_error_body_that_is_not_an_object_uses_reason_phrase():
    handler = scripted((500, ["not", "an", "object"]))
    with pytest.raises(APIError) as exc_info:
        make_client(handler).validate("X")
    assert exc_info.value.status_code == 500
    assert exc_info.value.error_code == "UNKNOWN_ERROR"


def test_error_code_and_message_from_body():
    handler = scripted((402, {"error": "Not enough credits", "error_code": "QUOTA_EXCEEDED"}))
    with pytest.raises(APIError) as exc_info:
        make_client(handler).enrich("X", attributes=["phone"])
    assert exc_info.value.status_code == 402
    assert exc_info.value.error_code == "QUOTA_EXCEEDED"
    assert "Not enough credits" in str(exc_info.value)
