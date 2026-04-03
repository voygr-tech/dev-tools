# Voygr CLI — Design Spec

## Overview

A Python CLI tool for the Voygr Business Validation API (`https://dev.voygr.tech`). Distributed as a public PyPI package (`pip install voygr`), source hosted on GitHub under MIT license.

**Audience:** Developers integrating the API into workflows and scripts.

## Commands

```
voygr signup <email>          # Request API key via email
voygr login <api-key>         # Store API key in ~/.config/voygr/config.json
voygr logout                  # Remove stored credentials
voygr check <name> <address>  # Check business existence and open/closed status
voygr usage                   # Show remaining quota and usage stats
```

All commands output JSON to stdout by default. `--pretty` flag for formatted/colored JSON.

Global flags:
- `--api-key` — override stored/env API key for this call
- `--base-url` — override API base URL (default: `https://dev.voygr.tech`)
- `--pretty` — pretty-print JSON output

Auth resolution order: `--api-key` flag > `VOYGR_API_KEY` env var > config file.

## Output

JSON to stdout by default:

```json
{"existence_status": "exists", "open_closed_status": "open", "request_id": "req_abc123", "validation_timestamp": "2026-04-03T12:00:00Z"}
```

With `--pretty`:

```json
{
  "existence_status": "exists",
  "open_closed_status": "open",
  "request_id": "req_abc123",
  "validation_timestamp": "2026-04-03T12:00:00Z"
}
```

## Error Handling

Errors output JSON to stderr:

```json
{"error": "unauthorized", "message": "Invalid or missing API key. Run 'voygr login <key>' to configure."}
```

Exit codes:
- `0` — success
- `1` — API error (auth, rate limit, server error)
- `2` — user error (missing args, bad config)

## Project Structure

```
voygr/
├── pyproject.toml
├── src/
│   └── voygr/
│       ├── __init__.py     # Version
│       ├── cli.py          # Click commands
│       ├── client.py       # API client (httpx)
│       └── config.py       # Config file read/write
├── tests/
│   ├── conftest.py
│   ├── test_cli.py
│   └── test_client.py
├── LICENSE
└── README.md
```

- `src/` layout for clean PyPI packaging
- `client.py` usable as a standalone library (`from voygr import Client`)
- Config stored at `~/.config/voygr/config.json` (XDG convention)

## Dependencies

**Runtime:**
- `click` — CLI framework
- `httpx` — HTTP client

**Dev:**
- `pytest`
- `pytest-mock`

## Distribution

- **Package name:** `voygr`
- **Entry point:** `voygr` command
- **Python:** 3.10+
- **Version:** `0.1.0` (semver)
- **Source:** public GitHub repo
- **Package:** PyPI (`pip install voygr`)

## Testing

Extensive test coverage across all layers:

- **CLI commands** — every command's happy path, error cases, flag combinations (Click's `CliRunner`)
- **API client** — all endpoints, auth resolution, error responses, timeouts, rate limiting
- **Config** — read/write/delete, missing file, corrupt file, permissions
- **Integration** — end-to-end flows (signup -> login -> check -> usage)

API mocking via `httpx` mock transport — no real network calls in tests.

## Documentation

README serves as the complete reference. Must be self-contained enough for an AI agent or developer to use the tool without external docs.

Contents:
- Install instructions (`pip install voygr`)
- Quick start walkthrough (signup -> login -> check)
- Full command reference with examples for every command and flag combination
- Environment variable reference (`VOYGR_API_KEY`, `VOYGR_BASE_URL`)
- Exit codes and error format
- Python library usage (`from voygr import Client`)
