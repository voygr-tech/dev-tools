# Public examples implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Publish three runnable examples that check closed stores, enrich leads and request table bookings.

**Architecture:** Keep examples outside the shipped SDK. Share CSV validation, bulk-job submission and result matching; each use case owns its formatter and README. Use the existing HTTP client dependency for PlaceCall submission and readback.

**Tech Stack:** Python >=3.10, voygr, click, httpx, pytest.

**Spec:** `docs/superpowers/specs/2026-11-07-public-examples-design.md`

## Global constraints

- Use Python >=3.10, the existing `voygr` SDK, `click` and `httpx`; add no dependencies.
- Preserve original CSV columns and values in output, including customer IDs.
- Default phone booking to a local preview. Require `--confirm-call` and an explicit idempotency key before sending `POST /calls`.
- Do not commit generated datasets, caches, exports or secrets.
- Do not change SDK behavior, product APIs, account access, pricing or production data.
- No real paid API jobs or phone calls during verification.

## Review focus

- CSV columns with duplicate/case-varied names or malformed widths: reject before a job submission.
- Reordered/duplicate/missing API result IDs: match by internal ID or fail without output.
- Failed/unknown response data: retain row errors and distinguish unknown from open/closed; malformed schema fails loudly.
- Existing output, missing parent or credentials: fail before spending and preserve input/output files.
- Ambiguous call submissions: one POST using the supplied key; readback never starts another call.

### Task 1: Closed-store CSV example and shared job orchestration

**Files:**
- Create: `examples/csv_jobs.py`, `examples/check_closed_stores/main.py`, `examples/check_closed_stores/README.md`
- Create: `tests/test_example_csv_jobs.py`, `tests/test_example_closed_stores.py`
- Modify: `.gitignore` to ignore Python caches and local example exports.

**Interfaces:**
- Consumes: `voygr.csv_input.read_places(path)`, `Client.submit_validate_job`, `wait_for_job`, `iter_job_results`.
- Produces: `run_job(input_path: Path, output_path: Path, idempotency_key: str, fields: list[str], render: Callable[[dict], dict], *, attributes: list[str | dict] | None = None, timeout: float = 3600) -> None`; Click command `examples.check_closed_stores.main.main`.
- A render function handles successful API rows. The common helper adds `voygr_error`, internal IDs and all original columns. Failed rows skip the renderer, leave derived values blank and retain structured error JSON; output is written before exiting 1.

- [x] Write failing tests for a real SDK job over MockTransport: shuffled results preserve original row order/IDs/unknown columns; explicit submit key; API auth absent from presigned downloads; success false produces error output and exit 1. Assert literal statuses `open`, `closed`, `unknown`, `not_exists`.
- [x] Add preflight failures for empty/duplicate headers, malformed rows, reserved columns, existing output, missing parent/key and blank idempotency key. Add response failures for missing/duplicate/extra IDs, malformed success/operational status, failed/cancelled jobs and API errors. Assert no HTTP for preflight errors and no output for job/schema errors.
- [x] Run `../.venv/bin/python -m pytest tests/test_example_csv_jobs.py tests/test_example_closed_stores.py -q`; expect missing-example failures.
- [x] Implement shared orchestration and closed-store formatter/command. Add README with inline sample input, one-line install, real command, fields, recovery and source links.
- [x] Run the same command; expect all tests pass. Run the full suite; expect baseline and added tests pass.
- [x] Commit as `feat: add closed-store CSV example with safe bulk jobs`.

### Task 2: Lead enrichment CSV example

**Files:**
- Create: `examples/enrich_leads/main.py`, `examples/enrich_leads/README.md`, `tests/test_example_enrich_leads.py`.

**Interfaces:**
- Consumes: Task 1 `run_job` with `attributes=["phone", "email", "website", {"name":"owners","include":["phone","email"]}]` (engineering ruling after reading the owner contract).
- Produces: Click command `examples.enrich_leads.main.main`; JSON-valued cells for each attribute object, including confidence and nullable values.

- [x] Write failing tests asserting enrichment payload includes all four attributes; output preserves customer columns and full phone/owner objects; omitted/null attributes remain null. Reject malformed attribute containers and per-attribute objects. Reuse preflight and ID tests through the common helper.
- [x] Run `../.venv/bin/python -m pytest tests/test_example_enrich_leads.py -q`; expect missing-example failures.
- [x] Implement command/formatter using the shared helper and SDK enrich jobs. Add README covering owner research charges, missing data and Prospecting MCP alternative.
- [x] Run the same command then full suite; expect all pass.
- [x] Commit as `feat: add lead enrichment CSV example`.

### Task 3: Table booking example and collection index

**Files:**
- Create: `examples/book_table/main.py`, `examples/book_table/README.md`, `examples/README.md`, `tests/test_example_book_table.py`.
- Modify: `README.md` with links to the three examples.

**Interfaces:**
- Consumes: `httpx.Client` for fixed-origin POST `/calls` and GET `/calls/{id}`.
- Produces: Click command `examples.book_table.main.main`. Booking mode accepts phone, restaurant, name, party size, ISO datetime with offset and callback. Preview requires no HTTP/key. Confirmation requires a key and explicit idempotency key. Read mode `--call-id` takes no booking arguments, rejects confirmation options and prints structured result.

- [x] Write failing tests for preview without credentials/network, complete booking brief, one confirmed POST with supplied idempotency/auth headers, key fallback, missing key/key blank, invalid phone/time/party/blank or oversized brief values, malformed/missing call ID, HTTP/network errors and readback without POST.
- [x] Run `../.venv/bin/python -m pytest tests/test_example_book_table.py -q`; expect missing-example failures.
- [x] Implement the command. Never automatically retry POST; print recovery key before the request and call ID after it. Reject schema drift. Add README instructions for inspecting results, reusing the exact key/body within the documented 24-hour window and the maintained MCP agent route.
- [x] Edit all README prose with loaded stop-slop and humanizer. Use inline sample CSV creation, not committed data. Add root/collection navigation with buyer questions and links.
- [x] Run `../.venv/bin/python -m pytest -q`, `../.venv/bin/python -m compileall -q examples`, `git diff --check`, the three `--help` commands and a booking preview using fictional phone numbers and a future offset datetime. Expect all pass and no network from preview.
- [x] Commit as `feat: add table booking preview and public examples guide`.

## Completion

Create a whole-branch review package and obtain an independent code review.
Assess feedback, test fixes RED to GREEN and run the full suite. Preserve execution
and review records in `docs/superpowers/reviews/2026-11-07-public-examples.md`.
Open one review-ready public PR, inspect actual CI/Greptile state, and use the
prescribed wakeup loop for pending external checks. Merge only with exact-head
Greptile 5/5 and green CI. No website deployment or package release is required.
