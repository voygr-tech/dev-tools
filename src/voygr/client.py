import gzip
import hashlib
import json
import sys
import time
import uuid
import zlib
from collections.abc import Callable, Iterator
from urllib.parse import quote

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

MAX_JOB_ROWS = 10_000
TERMINAL_JOB_STATUSES = frozenset({"completed", "failed", "cancelled"})

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


class _ExpiredLink(APIError):
    """A presigned result URL answered 403: the link has expired."""

    def __init__(self):
        super().__init__("Result download link expired. Poll the job again for a fresh link.", status_code=403)


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


def _result_files(status: dict) -> list[dict]:
    return (status.get("results") or {}).get("files") or []


def _decode_result_file(data: bytes, sha256: str) -> list[dict]:
    if hashlib.sha256(data).hexdigest() != sha256.lower():
        raise APIError("Result file failed its checksum. Poll the job again for a fresh link.")
    try:
        # ponytail: whole file in memory; stream with gzip.GzipFile if result files grow past ~100 MB
        return [json.loads(line) for line in gzip.decompress(data).splitlines() if line.strip()]
    except (OSError, EOFError, zlib.error, ValueError) as e:
        raise APIError(f"Result file could not be read: {e}")


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

    def _send(
        self, method: str, url: str, *, headers: dict, retry_on: frozenset[int], timeout: float,
        presigned: bool = False, retry_transport_errors: bool = False, **httpx_kwargs
    ) -> httpx.Response:
        """One HTTP call with the per-call retry policy. Returns the response or raises APIError.

        With `presigned`, a 403 raises _ExpiredLink before the body is read: storage answers it with XML.
        With `retry_transport_errors`, a timeout or connection error is retried too, for calls that are safe to replay.
        """
        shown = url.partition("?")[0]  # a presigned query is a credential; keep it out of debug output
        transport_error = _RetryableError if retry_transport_errors else APIError

        def do_request() -> httpx.Response:
            start = time.monotonic()
            try:
                response = self._http.request(method, url, headers=headers, timeout=timeout, **httpx_kwargs)
            except httpx.TimeoutException:
                if self._debug:
                    elapsed = time.monotonic() - start
                    print(f"DEBUG {method} {shown} -> ERR ({elapsed:.3f}s)", file=sys.stderr)
                raise transport_error("Request timed out")
            except httpx.HTTPError as e:
                if self._debug:
                    elapsed = time.monotonic() - start
                    print(f"DEBUG {method} {shown} -> ERR ({elapsed:.3f}s)", file=sys.stderr)
                raise transport_error(f"Request failed: {e}")

            if self._debug:
                elapsed = time.monotonic() - start
                print(f"DEBUG {method} {shown} -> {response.status_code} ({elapsed:.3f}s)", file=sys.stderr)

            if presigned and response.status_code == 403:
                raise _ExpiredLink()
            if response.status_code >= 400:
                code, message = _error_code_and_message(response)
                text = f"{code}: {message}"
                if response.status_code in retry_on:
                    raise _RetryableError(
                        text, status_code=response.status_code, error_code=code, retry_after=_retry_after(response)
                    )
                raise APIError(text, status_code=response.status_code, error_code=code)
            return response

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

    def _request(
        self, method: str, path: str, *, auth: bool = True, retry_on: frozenset[int], timeout: float,
        retry_transport_errors: bool = False, **httpx_kwargs
    ) -> dict:
        headers = dict(httpx_kwargs.pop("headers", {}))
        if auth:
            headers["X-API-Key"] = self._require_auth()
        response = self._send(
            method, f"{self.base_url}{path}", headers=headers, retry_on=retry_on, timeout=timeout,
            retry_transport_errors=retry_transport_errors, **httpx_kwargs
        )
        try:
            return response.json()
        except ValueError:
            raise APIError("Invalid JSON response from server")

    def _download(self, url: str) -> bytes:
        """Fetch a presigned result URL. It carries its own credentials, so no API key goes along."""
        response = self._send("GET", url, headers={}, retry_on=_RETRYABLE, timeout=_DEFAULT_TIMEOUT, presigned=True)
        return response.content

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

    def _submit_job(self, path: str, pois: list[dict], idempotency_key: str | None) -> dict:
        if not 1 <= len(pois) <= MAX_JOB_ROWS:
            raise ValueError(f"A job takes 1 to {MAX_JOB_ROWS:,} rows, got {len(pois):,}")
        # Built once, so a retried submit replays as the same job instead of creating a second one.
        # That makes a timeout safe to retry too: the first attempt may have created the job.
        headers = {"Idempotency-Key": idempotency_key or str(uuid.uuid4())}
        return self._request(
            "POST", path, retry_on=_RETRYABLE, timeout=_DEFAULT_TIMEOUT, headers=headers, json={"pois": pois},
            retry_transport_errors=True,
        )

    def submit_validate_job(self, pois: list[dict], *, idempotency_key: str | None = None) -> dict:
        return self._submit_job("/v1/jobs/validate", pois, idempotency_key)

    def submit_enrich_job(self, pois: list[dict], *, idempotency_key: str | None = None) -> dict:
        return self._submit_job("/v1/jobs/enrich", pois, idempotency_key)

    def get_job(self, batch_id: str) -> dict:
        return self._request(
            "GET", f"/v1/jobs/{quote(batch_id, safe='')}", retry_on=_RETRYABLE, timeout=_DEFAULT_TIMEOUT
        )

    def cancel_job(self, batch_id: str) -> dict:
        return self._request(
            "DELETE", f"/v1/jobs/{quote(batch_id, safe='')}", retry_on=_RETRYABLE, timeout=_DEFAULT_TIMEOUT
        )

    def wait_for_job(
        self,
        batch_id: str,
        *,
        poll_interval: float = 5.0,
        timeout: float | None = None,
        on_progress: Callable[[dict], None] | None = None,
    ) -> dict:
        """Poll until the job reaches a terminal status and return that status.

        Raises TimeoutError once `timeout` seconds have passed; the job keeps running on the server. Sleeps and
        poll requests are cut to the time left, and no poll starts after the deadline.
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        request_timeout = min(_DEFAULT_TIMEOUT, timeout) if timeout else _DEFAULT_TIMEOUT  # timeout=0 still polls once
        while True:
            status = self._request(
                "GET", f"/v1/jobs/{quote(batch_id, safe='')}", retry_on=_RETRYABLE, timeout=request_timeout
            )
            if on_progress:
                on_progress(status)
            if status.get("status") in TERMINAL_JOB_STATUSES:
                return status
            pause = poll_interval
            if deadline is not None:
                pause = min(poll_interval, max(deadline - time.monotonic(), 0.0))
            time.sleep(pause)
            if deadline is not None:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise TimeoutError(f"Job {batch_id} did not finish within {timeout:g} seconds")
                request_timeout = min(_DEFAULT_TIMEOUT, left)

    def iter_job_results(self, batch_id: str) -> Iterator[dict]:
        """Yield every result row of a job, file by file, in input order."""
        files = _result_files(self.get_job(batch_id))
        for index, file in enumerate(files):
            try:
                data = self._download(file["url"])
            except _ExpiredLink:
                # Presigned links last about 15 minutes; poll once for fresh ones. A second 403 propagates.
                refreshed = _result_files(self.get_job(batch_id))
                if index >= len(refreshed):
                    raise
                file = refreshed[index]
                data = self._download(file["url"])
            yield from _decode_result_file(data, file["sha256"])
