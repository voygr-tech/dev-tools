import httpx

DEFAULT_BASE_URL = "https://dev.voygr.tech"


class APIError(Exception):
    def __init__(self, message: str, status_code: int | None = None, error_code: str | None = None):
        self.status_code = status_code
        self.error_code = error_code
        super().__init__(message)


class Client:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        transport: httpx.BaseTransport | None = None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._http = httpx.Client(transport=transport) if transport else httpx.Client()

    def _require_auth(self) -> str:
        if not self.api_key:
            raise APIError("No API key configured. Run 'voygr login <key>' or set VOYGR_API_KEY.")
        return self.api_key

    def _request(self, method: str, path: str, *, auth: bool = True, **kwargs) -> dict:
        headers = kwargs.pop("headers", {})
        if auth:
            headers["X-API-Key"] = self._require_auth()

        try:
            response = self._http.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)
        except httpx.TimeoutException:
            raise APIError("Request timed out")
        except httpx.HTTPError as e:
            raise APIError(f"Connection refused: {e}")

        data = response.json()
        if response.status_code >= 400:
            error_code = data.get("error_code", "UNKNOWN_ERROR")
            error_msg = data.get("error", response.reason_phrase)
            raise APIError(f"{error_code}: {error_msg}", status_code=response.status_code, error_code=error_code)

        return data

    def signup(self, email: str, name: str) -> dict:
        return self._request("POST", "/signup", auth=False, json={"email": email, "name": name})

    def check(self, name: str, address: str) -> dict:
        return self._request("POST", "/v1/business-status", json={"name": name, "address": address})

    def usage(self) -> dict:
        return self._request("GET", "/v1/usage")
