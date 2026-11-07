# Public examples design

## Intent and authorization

Help developers and assistants find VOYGR through runnable examples for checking
closed stores, enriching business leads, and booking a table by phone.
Yarik Markov approved the examples direction on VOYG-503, comment
`01a1b6f3-4a9f-72cb-82a8-23959d63ef3d` (2026-11-07). VOYG-550 assigns
these three examples. The workspace's standing human-decisions policy authorizes
technical design and implementation without separate design/plan approvals.
This document records engineering decisions; Yarik has not reviewed it.

## Goals and constraints

- Publish three small Python examples in a public `voygr-tech` repository.
- Use Python >=3.10, the existing `voygr` SDK, `click` and `httpx`; add no dependencies.
- Use environment variables for keys. Link to https://api.voygr.tech/checkout,
  https://voygr.tech and the public API documentation in each README.
- Give each example its own buyer-question README, runnable command and one-line install.
- Preserve original CSV columns and values in output, including customer IDs.
  Validate the entire input and output destination before submitting billable work.
- Use explicit idempotency keys for job/call submissions. Print recovery identifiers
  to stderr before waiting. Never retry a call under a new key after an ambiguous response.
- Show unknown/not-existing status as distinct from open/closed. Keep row errors visible.
- Default phone booking to a local preview. Require `--confirm-call` and an explicit
  idempotency key before sending `POST /calls`. Place no real calls during development.
- Keep API facts grounded in public docs and READMEs. Edit README prose using the
  loaded stop-slop and humanizer skills. Do not promise a particular credit balance.
- Do not change SDK behavior, product APIs, account access, pricing or production data.
- Do not commit generated datasets, caches, exports or secrets. Include small sample
  input inline in READMEs instead of committing CSV data files.

## Approaches

1. Three new public repositories give each example a repository title but duplicate
   setup, test configuration and maintenance. They also require repository provisioning.
2. A new examples repository shares those costs but needs initial default-branch
   provisioning and configuration before a normal PR can exist.
3. Add an examples collection to existing public `voygr-tech/dev-tools`, with one
   directory and README per use case. It already owns the maintained Python client,
   MIT license and CI. Choose this approach as an engineering decision: direct links
   remain public and runnable, and contributors can review everything in one PR.

## Design

### CSV examples

Put shared CSV/job orchestration in `examples/csv_jobs.py`. Capture one immutable
input snapshot and validate a private temporary copy with
`voygr.csv_input.read_places`. Read preserved CSV records from the same snapshot;
reject duplicate/empty headers, malformed rows and
pre-existing reserved output columns. Use internal unique row IDs in job payloads;
join results by those IDs, preserving original IDs and row order even when results
arrive out of order. Refuse missing/duplicate/unknown result IDs or schema drift.
Customer IDs remain output metadata; API validation sees generated row IDs, so
the API's ID length limit does not constrain the preserved customer IDs.

`examples/check_closed_stores/main.py` submits a validate job. Add columns
`voygr_status`, `voygr_closure_reason`, `voygr_error`.
`examples/enrich_leads/main.py` submits an enrich job requesting standard phone,
email, website and the documented `owners` research field with direct phone/email
included. Preserve attribute
objects as JSON cells in `voygr_phone`, `voygr_email`, `voygr_website`,
`voygr_owners` so confidence, sources and missing values survive.

Both commands accept INPUT OUTPUT `--idempotency-key KEY`, require
`VOYGR_API_KEY`, wait with a finite timeout, and print the batch ID. Use the same
key and identical input to retry an interrupted submission. Reject an existing
output path rather than overwriting it. Reserve the exact output path with
exclusive creation before submitting billable work. Serialize results before
writing the reserved file. Remove only the file this invocation reserved on
failure; never remove a replacement file. A terminal failed/cancelled job removes
the reservation and reports the batch ID; SDK job commands retrieve partial rows.
For completed jobs with failed rows, write all rows with errors and exit nonzero.

### Table booking

`examples/book_table/main.py` uses `httpx` against the public PlaceCall API because
the Places SDK does not implement calling. Inputs: destination phone, restaurant
name, reservation name, party size, local date/time with timezone, callback number.
Validate phone syntax, positive party size and an explicit future date/time with
UTC offset before any new booking. Build a brief containing every booking detail,
no substitution without permission, no payment/deposit commitments and a request
to read back the confirmed details. Do not claim the reservation succeeded merely
because the API accepted the call.

Without `--confirm-call`, print the JSON body and exit without credentials or HTTP.
For an authorized call use `PLACECALL_API_KEY` (or `VOYGR_API_KEY` fallback),
fixed API origin, `Idempotency-Key` and `X-Client-Surface: gh-repo`. Submit once,
print `call_id`, and return. A separate `--call-id ID` mode reads the current result
without placing another call; show the full structured response, including a null
result. This keeps the runnable example small and allows safe later reads. The
README provides the MCP equivalent and links to the maintained PlaceCall agent
instructions for interactive calls and mid-call questions.

Before a confirmed submission, save its exact body, idempotency key and original
UTC creation time to an ignored `.voygr-calls/` JSON file. Use exclusive creation
and Unix owner-only permissions; never include the API credential. Fail before
HTTP if saving fails. Normal repeats under an existing key must match its saved
body. `--retry-request PATH` previews that saved body without HTTP; adding
`--confirm-call` replays it, including after the reservation time passes. Reject
booking/key overrides, malformed saved records and retries at/after 24 hours
from the original timestamp. Never reset that timestamp on retry. New bookings
retain the future-time check. A replay can place the call when the first request
never reached the API, so the README explains checking account calls first.

## Verification

Each new module has tests. Use real SDK/client behavior with `httpx.MockTransport`;
replace the network, not the business logic. Cover shuffled IDs, original-column
preservation, errors and unknown status, malformed CSV, missing env keys, output
collisions, response schema drift, idempotency and authorization headers, booking
preview without network, invalid inputs and call readback without a second POST.
Run the full existing unit and mocked integration suite with both `python -m pytest`
and CI's bare `pytest` entry point and coverage flags. Configure pytest's project
root import path so source examples need not ship inside the SDK package.
The repository defines no separate linter/type checker or live integration command.
Run compile checks, `git diff --check`, all three `--help` commands and the no-call
booking preview. Do not perform live paid jobs or calls as verification.

## Review and delivery

Retain this spec, a committed implementation plan, internal builder/code reviews
and an execution ledger. Open one public-repo PR under 100 changed files after
local verification. Inspect the existing Greptile configuration/reviews, reuse the
automatic review if present and obtain 5/5 on the exact head plus green CI before
merging. If reviews are pending, persist the prescribed issue wakeup loop and
report observed state. This is repository work, not a website preview request.
