import sys
import time

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential_jitter, retry_if_exception_type

DEFAULT_BASE_URL = "https://dev.voygr.tech"


class APIError(Exception):
    def __init__(self, message: str, status_code: int | None = None, error_code: str | None = None):
        self.status_code = status_code
        self.error_code = error_code
        super().__init__(message)


class _RetryableError(APIError):
    """Marks an error as retryable (429, 5xx)."""
    pass


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

    def _request(self, method: str, path: str, *, auth: bool = True, **kwargs) -> dict:
        headers = kwargs.pop("headers", {})
        if auth:
            headers["X-API-Key"] = self._require_auth()

        url = f"{self.base_url}{path}"

        _RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

        def do_request() -> dict:
            start = time.monotonic()
            try:
                response = self._http.request(method, url, headers=headers, **kwargs)
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

            try:
                data = response.json()
            except ValueError:
                if response.status_code >= 400:
                    raise APIError(f"HTTP {response.status_code}", status_code=response.status_code)
                raise APIError(f"Invalid JSON response from server")

            if response.status_code >= 400:
                error_code = data.get("error_code", "UNKNOWN_ERROR")
                error_msg = data.get("error", response.reason_phrase)
                if response.status_code in _RETRYABLE_STATUS_CODES:
                    raise _RetryableError(f"{error_code}: {error_msg}", status_code=response.status_code, error_code=error_code)
                raise APIError(f"{error_code}: {error_msg}", status_code=response.status_code, error_code=error_code)

            return data

        if self._retries > 0:
            retrying = retry(
                stop=stop_after_attempt(self._retries + 1),
                wait=wait_exponential_jitter(initial=1, max=10, jitter=2),
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

    def signup(self, email: str, name: str) -> dict:
        return self._request("POST", "/signup", auth=False, json={"email": email, "name": name})

    def check(self, name: str, address: str) -> dict:
        return self._request("POST", "/v1/business-status", json={"name": name, "address": address})

    def usage(self) -> dict:
        return self._request("GET", "/v1/usage")
