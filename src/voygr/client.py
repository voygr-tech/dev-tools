import sys
import time

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential_jitter, retry_if_exception_type

DEFAULT_BASE_URL = "https://api.voygr.tech"

# Any other attribute name is a paid research field.
STANDARD_ATTRIBUTES = (
    "opening_hours", "phone", "website", "facebook", "instagram",
    "tiktok", "x", "email", "existence", "open_closed",
)

# Per-call retry policy: single lookups retry on 429 only, reads and job calls on transient 5xx too.
_RATE_LIMIT_ONLY = frozenset({429})
_RETRYABLE = frozenset({429, 500, 502, 503, 504})

_DEFAULT_TIMEOUT = 90.0
_RESEARCH_TIMEOUT = 3700.0
_MAX_RETRY_AFTER = 60.0

_backoff = wait_exponential_jitter(initial=1, max=10, jitter=2)

# Codes for gateway errors whose body names no code of its own.
_STATUS_CODES = {401: "AUTHENTICATION_ERROR", 402: "QUOTA_EXCEEDED", 403: "FORBIDDEN", 429: "RATE_LIMIT_ERROR"}


def _is_code_like(text: str) -> bool:
    """True for snake_case such as `quota_exceeded`: ^[a-z][a-z0-9_]*$."""
    return text.isascii() and text.isidentifier() and text.islower() and text[0] != "_"


class APIError(Exception):
    def __init__(self, message: str, status_code: int | None = None, error_code: str | None = None):
        self.status_code = status_code
        self.error_code = error_code
        super().__init__(message)


class _RetryableError(APIError):
    """Marks an error as retryable for the current call; carries the server's Retry-After."""

    def __init__(self, message: str, status_code: int | None = None, error_code: str | None = None,
                 retry_after: float | None = None):
        super().__init__(message, status_code=status_code, error_code=error_code)
        self.retry_after = retry_after


def _wait(retry_state) -> float:
    retry_after = getattr(retry_state.outcome.exception(), "retry_after", None)
    return retry_after if retry_after is not None else _backoff(retry_state)


def _retry_after(response: httpx.Response) -> float | None:
    """Seconds from a numeric Retry-After header, capped at 60. Dates and junk give None."""
    try:
        seconds = float(response.headers.get("Retry-After", ""))
    except ValueError:
        return None
    return min(seconds, _MAX_RETRY_AFTER) if seconds >= 0 else None


def _error_code_and_message(response: httpx.Response) -> tuple[str, str]:
    try:
        data = response.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        data = {}
    detail = data.get("detail")
    fallback = response.reason_phrase or f"HTTP {response.status_code}"
    if "error" in data or "error_code" in data:
        code = data.get("error_code") or "UNKNOWN_ERROR"
        message = data.get("error")
    elif isinstance(detail, list) and detail:
        code = "VALIDATION_ERROR"
        message = "; ".join(_detail_entry(entry) for entry in detail)
    elif isinstance(detail, str):
        code, message = "UNKNOWN_ERROR", detail
    elif isinstance(detail, dict):
        # The gateway nests auth, quota, entitlement and rate-limit errors under `detail`.
        error = detail.get("error") if isinstance(detail.get("error"), str) else None
        if detail.get("error_code"):
            code = detail["error_code"]
        elif error and _is_code_like(error):
            code = error.upper()
        else:
            code = _STATUS_CODES.get(response.status_code, "UNKNOWN_ERROR")
        message = detail.get("message") or error
        needed = detail.get("needed_credits")
        if needed is not None:
            message = f"{message or fallback} ({needed} {'credit' if needed == 1 else 'credits'} needed)"
    else:
        code, message = "UNKNOWN_ERROR", None
    return code, message or fallback


def _detail_entry(entry) -> str:
    if not isinstance(entry, dict):
        return str(entry)
    loc = ".".join(str(part) for part in entry.get("loc") or [])
    msg = entry.get("msg", "")
    return f"{loc}: {msg}" if loc else str(msg)


def _without_none(fields: dict) -> dict:
    return {key: value for key, value in fields.items() if value is not None}


def _is_research(attributes: list[str | dict] | None) -> bool:
    return any(isinstance(item, dict) or item not in STANDARD_ATTRIBUTES for item in attributes or [])


class Client:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        debug: bool = False,
        transport: httpx.BaseTransport | None = None,
        retries: int = 0,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._debug = debug
        self._retries = retries
        self._http = httpx.Client(transport=transport, timeout=60.0) if transport else httpx.Client(timeout=60.0)

    def _require_auth(self) -> str:
        if not self.api_key:
            raise APIError("No API key configured. Run 'voygr login <key>' or set VOYGR_API_KEY.")
        return self.api_key

    def _request(
        self, method: str, path: str, *, auth: bool = True, retry_on: frozenset[int], timeout: float, **httpx_kwargs
    ) -> dict:
        headers = dict(httpx_kwargs.pop("headers", {}))
        if auth:
            headers["X-API-Key"] = self._require_auth()

        url = f"{self.base_url}{path}"

        def do_request() -> dict:
            start = time.monotonic()
            try:
                response = self._http.request(method, url, headers=headers, timeout=timeout, **httpx_kwargs)
            except httpx.TimeoutException:
                if self._debug:
                    elapsed = time.monotonic() - start
                    print(f"DEBUG {method} {url} -> ERR ({elapsed:.3f}s)", file=sys.stderr)
                raise APIError("Request timed out")
            except httpx.HTTPError as e:
                if self._debug:
                    elapsed = time.monotonic() - start
                    print(f"DEBUG {method} {url} -> ERR ({elapsed:.3f}s)", file=sys.stderr)
                raise APIError(f"Request failed: {e}")

            if self._debug:
                elapsed = time.monotonic() - start
                print(f"DEBUG {method} {url} -> {response.status_code} ({elapsed:.3f}s)", file=sys.stderr)

            if response.status_code >= 400:
                code, message = _error_code_and_message(response)
                text = f"{code}: {message}"
                if response.status_code in retry_on:
                    raise _RetryableError(
                        text, status_code=response.status_code, error_code=code, retry_after=_retry_after(response)
                    )
                raise APIError(text, status_code=response.status_code, error_code=code)

            try:
                return response.json()
            except ValueError:
                raise APIError("Invalid JSON response from server")

        if self._retries > 0:
            retrying = retry(
                stop=stop_after_attempt(self._retries + 1),
                wait=_wait,
                retry=retry_if_exception_type(_RetryableError),
                reraise=True,
            )(do_request)
            return retrying()
        else:
            return do_request()

    def close(self) -> None:
        self._http.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def signup(self, email: str, name: str, *, src: str | None = None) -> dict:
        return self._request(
            "POST", "/signup", auth=False, retry_on=_RATE_LIMIT_ONLY, timeout=_DEFAULT_TIMEOUT,
            json=_without_none({"email": email, "name": name, "src": src}),
        )

    def recover(self, email: str) -> dict:
        return self._request(
            "POST", "/recover", auth=False, retry_on=_RATE_LIMIT_ONLY, timeout=_DEFAULT_TIMEOUT,
            json={"email": email},
        )

    def validate(self, poi_name: str, **fields) -> dict:
        return self._request(
            "POST", "/v1/validate", retry_on=_RATE_LIMIT_ONLY, timeout=_DEFAULT_TIMEOUT,
            json=_without_none({"poi_name": poi_name, **fields}),
        )

    def enrich(self, poi_name: str, *, attributes: list[str | dict] | None = None, **fields) -> dict:
        return self._request(
            "POST", "/v1/enrich", retry_on=_RATE_LIMIT_ONLY,
            timeout=_RESEARCH_TIMEOUT if _is_research(attributes) else _DEFAULT_TIMEOUT,
            json=_without_none({"poi_name": poi_name, "attributes": attributes, **fields}),
        )

    def usage(self) -> dict:
        return self._request("GET", "/v1/usage", retry_on=_RETRYABLE, timeout=_DEFAULT_TIMEOUT)

    def pricing(self) -> dict:
        return self._request("GET", "/v1/pricing", auth=False, retry_on=_RETRYABLE, timeout=_DEFAULT_TIMEOUT)
