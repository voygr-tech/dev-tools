# Voygr

CLI and Python client for the Business Validation API.

## Install

```bash
pip install voygr
```

Requires Python 3.10+.

## Quick Start

### 1. Sign up for an API key

```bash
voygr signup you@example.com --name "Your Name"
```

```json
{"success": true, "message": "API key sent to your email"}
```

### 2. Save your API key

```bash
voygr login pk_live_abc123
```

```json
{"success": true, "message": "API key saved"}
```

### 3. Check a business

```bash
voygr check "Starbucks" "1390 Market St, San Francisco, CA 94102"
```

```json
{"success":true,"existence_status":"exists","open_closed_status":"open","request_id":"abc123","validation_timestamp":"2026-03-13T12:00:00Z"}
```

Default output is compact JSON. Add `--human` for a readable format:

```bash
voygr --human check "Starbucks" "1390 Market St, San Francisco, CA 94102"
```

```
existence_status: exists
open_closed_status: open
request_id: abc123
validation_timestamp: 2026-03-13T12:00:00Z
```

## Recovering a lost API key

If you lose access to your API key, request a recovery link:

```bash
voygr recover you@example.com
```

A link is sent to the email if an account exists. Clicking it **rotates** your key — the existing one stops working immediately, and a new one is sent to the same address. Remaining quota and plan tier carry over.

See [`voygr recover`](#voygr-recover-email) for full details.

## Command Reference

### `voygr signup <email> [--name NAME]`

Request an API key. The key is sent to the provided email address.

- `email` (required) -- email address to receive the key
- `--name` -- your name; defaults to the email if omitted

```bash
voygr signup jane@example.com --name "Jane Smith"
```

```json
{"success": true, "message": "API key sent to your email"}
```

No authentication required. If the email already has an account, the response directs you to `voygr recover` instead of resending the key.

### `voygr recover <email>`

Request a recovery link for a forgotten or lost API key. The link is sent to the provided email if an account exists.

```bash
voygr recover jane@example.com
```

```json
{"success": true, "message": "If an account exists for that email, a recovery link has been sent."}
```

Clicking the link rotates your API key — the existing key stops working at that moment, and the new one is sent to the same email. Remaining quota and plan tier carry over to the new key.

The response is uniform whether or not the email is registered, so it cannot be used to enumerate accounts. Rate-limited per email and per source IP.

### `voygr login <api-key>`

Store your API key locally at `~/.config/voygr/config.json`.

```bash
voygr login pk_live_abc123
```

```json
{"success": true, "message": "API key saved"}
```

### `voygr logout`

Remove the stored API key.

```bash
voygr logout
```

```json
{"success": true, "message": "API key removed"}
```

### `voygr check <name> <address>`

Check whether a business exists at the given address and whether it's open or closed. Requires authentication.

- `name` (required) -- business name
- `address` (required) -- full street address

```bash
voygr check "Blue Bottle Coffee" "66 Mint St, San Francisco, CA 94103"
```

```json
{"success":true,"existence_status":"exists","open_closed_status":"open","request_id":"req_7f2a","validation_timestamp":"2026-04-03T15:30:00Z"}
```

**`existence_status`** values: `exists`, `not_exists`, `uncertain`

**`open_closed_status`** values: `open`, `closed`, `uncertain`

### `voygr check --file <csv>`

Batch mode. Reads a CSV file with `name` and `address` columns and checks each row. Output is JSONL (one JSON object per line).

Exits with code 1 if any check in the batch fails.

See the [Batch Mode](#batch-mode) section for details.

### `voygr usage`

Check your remaining validation quota. Requires authentication.

```bash
voygr usage
```

```json
{"quota_limit":100,"current_usage":12,"remaining":88,"percentage_used":12.0,"period":"lifetime","status":"active"}
```

### `voygr completions [bash|zsh|fish]`

Print shell completion setup instructions for the given shell. See [Shell Completions](#shell-completions).

## Batch Mode

Use `--file` to check multiple businesses from a CSV file:

```bash
voygr check --file businesses.csv
```

The CSV must have a header row with `name` and `address` columns:

```csv
name,address
Starbucks,"1390 Market St, San Francisco, CA 94102"
Blue Bottle Coffee,"66 Mint St, San Francisco, CA 94103"
```

Output is JSONL -- one JSON object per line, making it easy to pipe into `jq` or other tools:

```jsonl
{"success":true,"existence_status":"exists","open_closed_status":"open","request_id":"req_a1","validation_timestamp":"2026-04-03T15:30:00Z"}
{"success":true,"existence_status":"exists","open_closed_status":"open","request_id":"req_a2","validation_timestamp":"2026-04-03T15:30:01Z"}
```

If a row fails, the error record includes `input_name` and `input_address` so you can trace it back:

```json
{"success":false,"error":"RATE_LIMIT_ERROR","message":"Too many requests","input_name":"Starbucks","input_address":"1390 Market St, San Francisco, CA 94102"}
```

The command exits with code 1 if any check in the batch fails, even if others succeeded.

## Global Flags

These flags apply to every command:

| Flag | Description |
|------|-------------|
| `--api-key KEY` | API key for this request. Overrides env var and config file. |
| `--base-url URL` | API base URL. Defaults to `https://dev.voygr.tech`. |
| `--human` | Human-readable output. Default is JSON. |
| `--debug` | Print HTTP request details to stderr. |
| `--version` | Show version and exit. |

```bash
voygr --api-key pk_live_abc123 --human check "Whole Foods" "399 4th St, SF, CA"
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `VOYGR_API_KEY` | API key. Used when no `--api-key` flag is passed. |
| `VOYGR_BASE_URL` | Base URL. Used when no `--base-url` flag is passed. |

```bash
export VOYGR_API_KEY=pk_live_abc123
voygr check "Whole Foods" "399 4th St, San Francisco, CA 94107"
```

## Authentication

The API key is resolved in this order:

1. `--api-key` flag
2. `VOYGR_API_KEY` environment variable
3. Config file at `~/.config/voygr/config.json`

If none of these are set, commands that require authentication (`check`, `usage`) will exit with an error.

## Retry Behavior

The CLI automatically retries requests that fail with 429 (rate limit) or 5xx (server error) responses. Retries use exponential backoff, up to 3 attempts.

No configuration needed for CLI usage -- retries are always on.

For library users, pass `retries` to the constructor:

```python
client = Client(api_key="pk_live_abc123", retries=3)
```

Set `retries=0` to disable (the default for the library).

## Shell Completions

Generate completion setup instructions for your shell:

```bash
# Bash
voygr completions bash

# Zsh
voygr completions zsh

# Fish
voygr completions fish
```

Each command prints the snippet you need to add to your shell config (`.bashrc`, `.zshrc`, or `~/.config/fish/config.fish`). Follow the printed instructions to enable tab completion for all commands and flags.

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | API error (bad request, auth failure, quota exceeded, network error) |
| `2` | User error (missing argument, invalid flag) |

## Error Format

All errors are written to stderr as JSON:

```json
{"error": "AUTHENTICATION_ERROR", "message": "AUTHENTICATION_ERROR: Invalid or revoked API key"}
```

Common error codes:

| Error Code | Meaning |
|------------|---------|
| `VALIDATION_ERROR` | Invalid request (missing fields, bad format) |
| `AUTHENTICATION_ERROR` | Missing or invalid API key |
| `QUOTA_EXCEEDED` | No validations remaining |
| `RATE_LIMIT_ERROR` | Too many requests (retry after a moment) |

## Python Library Usage

```python
from voygr import Client

client = Client(api_key="pk_live_abc123")

# Check a business
result = client.check(
    name="Starbucks",
    address="1390 Market St, San Francisco, CA 94102",
)
print(result["existence_status"])  # "exists"
print(result["open_closed_status"])  # "open"

# Check remaining quota
usage = client.usage()
print(f"{usage['remaining']} validations left")

# Sign up (no API key needed)
client = Client()
client.signup(email="you@example.com", name="Your Name")
```

The `Client` constructor accepts:

- `api_key` -- your API key (required for `check` and `usage`)
- `base_url` -- defaults to `https://dev.voygr.tech`
- `retries` -- number of retries on 429/5xx errors (default `0`)

All methods return a `dict` parsed from the JSON response. On HTTP errors, they raise `APIError` with `status_code`, `error_code`, and a message.

```python
from voygr import Client, APIError

client = Client(api_key="pk_live_abc123")
try:
    result = client.check(name="Test", address="123 Main St")
except APIError as e:
    print(e.status_code)  # 402
    print(e.error_code)   # "QUOTA_EXCEEDED"
```

## API Reference

**Base URL:** `https://dev.voygr.tech`

### POST /signup

Get an API key sent to your email. No authentication required.

**Request:**

```json
{"name": "Jane Smith", "email": "jane@example.com"}
```

**Response (200):**

```json
{"success": true, "message": "API key sent to your email"}
```

### POST /v1/business-status

Check business existence and open/closed status. Requires `X-API-Key` header.

**Request:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Business name |
| `address` | string | yes | Full street address |

```json
{"name": "Blue Bottle Coffee", "address": "66 Mint St, San Francisco, CA 94103"}
```

**Response (200):**

```json
{
  "success": true,
  "existence_status": "exists",
  "open_closed_status": "open",
  "request_id": "abc123",
  "validation_timestamp": "2026-03-13T12:00:00Z"
}
```

| Field | Type | Values |
|-------|------|--------|
| `existence_status` | string | `exists`, `not_exists`, `uncertain` |
| `open_closed_status` | string | `open`, `closed`, `uncertain` |
| `request_id` | string | Unique request identifier |
| `validation_timestamp` | string | ISO 8601 UTC timestamp |

### GET /v1/usage

Check remaining validation quota. Requires `X-API-Key` header.

**Response (200):**

```json
{
  "quota_limit": 100,
  "current_usage": 12,
  "remaining": 88,
  "percentage_used": 12.0,
  "period": "lifetime",
  "status": "active"
}
```

### Error Responses

All endpoints return errors in a consistent format:

```json
{
  "success": false,
  "error": "Description of the error",
  "error_code": "ERROR_TYPE",
  "request_id": "abc123"
}
```

| HTTP Status | Error Code | Meaning |
|-------------|------------|---------|
| 400 | `VALIDATION_ERROR` | Invalid request body |
| 401 | `AUTHENTICATION_ERROR` | Missing API key |
| 402 | `QUOTA_EXCEEDED` | No validations remaining |
| 403 | `AUTHENTICATION_ERROR` | Invalid or revoked API key |
| 429 | `RATE_LIMIT_ERROR` | Too many requests |

## License

MIT
