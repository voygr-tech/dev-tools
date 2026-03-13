# Business Validation API

Verify whether a business exists at a given address and check if it's currently open or closed.

**Base URL:** `https://dev.voygr.tech`

## Getting Started

### 1. Get an API Key

```bash
curl -X POST https://dev.voygr.tech/signup \
  -H "Content-Type: application/json" \
  -d '{"name": "Your Name", "email": "you@example.com"}'
```

Your API key will be sent to your email. No credit card required — you get **100 free validations**.

### 2. Validate a Business

```bash
curl -X POST https://dev.voygr.tech/v1/business-status \
  -H "Content-Type: application/json" \
  -H "X-API-Key: YOUR_API_KEY" \
  -d '{"name": "Starbucks", "address": "1390 Market St, San Francisco, CA 94102"}'
```

**Response:**

```json
{
  "success": true,
  "existence_status": "exists",
  "open_closed_status": "open",
  "request_id": "abc123",
  "validation_timestamp": "2026-03-13T12:00:00Z"
}
```

## Authentication

Include your API key in every request as the `X-API-Key` header:

```
X-API-Key: pk_live_your_key_here
```

## Endpoints

### POST /signup

Get an API key sent to your email.

**Request:**

```json
{
  "name": "Jane Smith",
  "email": "jane@example.com"
}
```

**Response:**

```json
{
  "success": true,
  "message": "API key sent to your email"
}
```

If you've already signed up, submitting the same email will re-send your existing key.

---

### POST /v1/business-status

Validate a business — check if it exists and whether it's open or closed.

**Request:**

| Field     | Type   | Required | Description              |
|-----------|--------|----------|--------------------------|
| `name`    | string | yes      | Business name            |
| `address` | string | yes      | Full address string      |

```json
{
  "name": "Blue Bottle Coffee",
  "address": "66 Mint St, San Francisco, CA 94103"
}
```

**Response:**

| Field               | Type   | Values                                  |
|---------------------|--------|-----------------------------------------|
| `success`           | bool   | `true` if validation completed          |
| `existence_status`  | string | `exists`, `not_exists`, `uncertain`     |
| `open_closed_status`| string | `open`, `closed`, `uncertain`           |
| `request_id`        | string | Unique ID for this request              |
| `validation_timestamp` | string | ISO 8601 UTC timestamp              |

**Status values:**

- **`exists`** — the business was found at the given address
- **`not_exists`** — no evidence the business is at that address
- **`uncertain`** — not enough information to determine
- **`open`** — the business appears to be currently operating
- **`closed`** — the business appears to be permanently closed
- **`uncertain`** — not enough information to determine open/closed status

---

### GET /v1/usage

Check your remaining quota.

**Headers:** `X-API-Key: YOUR_API_KEY`

**Response:**

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

## Buying More Validations

Visit [dev.voygr.tech/checkout](https://dev.voygr.tech/checkout) to purchase additional validations with your existing API key.

## Rate Limits

- **Free tier:** 10 requests per minute
- **Paid tier:** 60 requests per minute

If you exceed the rate limit, you'll receive a `429` response. Wait and retry.

## Errors

All errors follow a consistent format:

```json
{
  "success": false,
  "error": "Description of the error",
  "error_code": "ERROR_TYPE",
  "request_id": "abc123"
}
```

| HTTP Status | Error Code            | Meaning                        |
|-------------|----------------------|--------------------------------|
| 400         | `VALIDATION_ERROR`   | Invalid request body           |
| 401         | `AUTHENTICATION_ERROR` | Missing API key              |
| 402         | `QUOTA_EXCEEDED`     | No validations remaining       |
| 403         | `AUTHENTICATION_ERROR` | Invalid or revoked API key   |
| 429         | `RATE_LIMIT_ERROR`   | Too many requests              |

## Example: Python

```python
import requests

response = requests.post(
    "https://dev.voygr.tech/v1/business-status",
    headers={"X-API-Key": "pk_live_your_key_here"},
    json={"name": "Whole Foods", "address": "399 4th St, San Francisco, CA 94107"},
)

data = response.json()
print(f"Exists: {data['existence_status']}")
print(f"Status: {data['open_closed_status']}")
```

## Example: JavaScript

```javascript
const response = await fetch("https://dev.voygr.tech/v1/business-status", {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "X-API-Key": "pk_live_your_key_here",
  },
  body: JSON.stringify({
    name: "Whole Foods",
    address: "399 4th St, San Francisco, CA 94107",
  }),
});

const data = await response.json();
console.log(`Exists: ${data.existence_status}`);
console.log(`Status: ${data.open_closed_status}`);
```
