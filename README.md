# Voygr

`voygr` is a command-line tool and Python client for the [Voygr Places API](https://api.voygr.tech/docs/). Give it a business list and it tells you which places still exist and which are still open. Then it fills in what the list is missing: phone, website, opening hours, social profiles and email. It can also research a question of your own about each place. Run it on one place, or on a CSV of up to 10,000 as one job. Keys are self-serve and free to start.

Every output below is from a real run on 21 October 2026. Commands that call the API ran against `api.voygr.tech`. We cut fields from some outputs and left the values as the API returned them.

## Install

```bash
pip install voygr
```

Needs Python 3.10 or newer.

## Quick start

### 1. Get a key

```bash
voygr signup you@example.com --name "Your Name"
```

```json
{"success": true, "message": "If this is a new email, an API key has been sent. If an account already exists, click “Recover your key” below to receive a new API key."}
```

The key arrives by email. The reply is the same for every address, and its "click below" line refers to the web page. If you already have an account, run `voygr recover you@example.com` instead.

### 2. Save the key

```bash
voygr login YOUR_API_KEY
```

```json
{"success": true, "message": "API key saved"}
```

`voygr login` saves the key to `~/.config/voygr/config.json`.

### 3. Validate a place

```bash
voygr validate "Blue Bottle Coffee" "66 Mint St, San Francisco, CA 94103" --country US
```

```json
{"success": true, "existence_confidence": 0.9954, "closure_confidence": 0.939, "operational_status": {"status": "closed", "closure_confidence": 0.939, "closure_probability": 0.939, "closure_reason": "permanent"}, "request_id": "req_507ce1033d904137a422c7ef", "validation_timestamp": "2026-10-21T04:20:03.526336Z"}
```

Read `operational_status.status`. It is `open`, `closed`, `unknown` or `not_exists`. This café scores 0.9954 on existence, but the API found it closed, with `closure_reason` `permanent`. A closed place can still score high on existence, so go by the status.

### 4. Enrich it

```bash
voygr enrich "Blue Bottle Coffee" "66 Mint St, San Francisco, CA 94103" --country US --attr phone --attr website --attr opening_hours
```

```json
{"success": true, "attributes": {"phone": {"value": {"number": "+15106533394"}, "as_of": null, "confidence": "medium"}, "website": {"value": {"url": "https://bluebottlecoffee.com"}, "as_of": null, "confidence": "high"}, "opening_hours": {"value": {"days": {"monday": "closed", "tuesday": "closed", "wednesday": "closed", "thursday": "closed", "friday": "closed", "saturday": "closed", "sunday": "closed"}}, "as_of": "2023-04-06", "confidence": "medium"}}, "enrichment_timestamp": "2026-10-21T04:20:28.936262Z", "request_id": "req_2c8330617cb141579e86d065"}
```

Each value comes with a `confidence` of `high`, `medium` or `low`. Leave out `--attr` to get the whole standard set: `opening_hours`, `phone`, `website`, `facebook`, `instagram`, `tiktok`, `x`, `email`, `existence` and `open_closed`.

### 5. Check your credits

```bash
voygr --human usage
```

```
Tier:      free
Status:    active (lifetime)
Available: 2487 credits
```

## Bulk with a CSV

The CSV needs a header row with a `name` column. `address`, `country`, `latitude`, `longitude` and `id` are optional. The CLI ignores other columns. Column names match regardless of case and surrounding spaces, and the command stops if a column appears twice, such as `address` and `Address`.

```csv
name,address,country,id
Blue Bottle Coffee,"66 Mint St, San Francisco, CA 94103",US,bb-mint
Tartine Bakery,"600 Guerrero St, San Francisco, CA 94110",US,tartine
Philz Coffee,"3101 24th St, San Francisco, CA 94110",US,philz-24th
```

```bash
voygr validate --file places.csv
```

The job ID goes to stderr straight away:

```
Submitted job batch_01M5EBKVAR1AATSRWXDQBY9RZD (3 places).
```

The CLI then polls until the job ends and prints one JSON line per row, in the file's order:

```jsonl
{"id": "bb-mint", "success": true, "existence_confidence": 0.9954, "closure_confidence": 0.939, "operational_status": {"status": "closed", "closure_confidence": 0.939, "closure_probability": 0.939, "closure_reason": "permanent"}, "error": null, "error_code": null, "validation_timestamp": "2026-10-21T04:30:51.901547Z"}
{"id": "tartine", "success": true, "existence_confidence": 0.9979, "closure_confidence": 0.005980588495731354, "operational_status": {"status": "open", "closure_confidence": 0.005980588495731354, "closure_probability": 0.005980588495731354, "closure_reason": null}, "error": null, "error_code": null, "validation_timestamp": "2026-10-21T04:31:00.482057Z"}
{"id": "philz-24th", "success": true, "existence_confidence": 0.9986, "closure_confidence": 0.939, "operational_status": {"status": "closed", "closure_confidence": 0.939, "closure_probability": 0.939, "closure_reason": "permanent"}, "error": null, "error_code": null, "validation_timestamp": "2026-10-21T04:31:02.537909Z"}
```

Enrich takes the same file. `--attr`, `--research`, `--summary` and `--max-credits` apply to every row:

```bash
voygr enrich --file places.csv --attr phone --attr website
```

```jsonl
{"success": true, "attributes": {"phone": {"value": {"number": "+15106533394"}, "as_of": null, "confidence": "medium"}, "website": {"value": {"url": "https://bluebottlecoffee.com"}, "as_of": null, "confidence": "medium"}}, "enrichment_timestamp": "2026-10-21T04:31:20.777200Z", "id": "bb-mint"}
{"success": true, "attributes": {"phone": {"value": {"number": "+14154872600"}, "as_of": null, "confidence": "high"}, "website": {"value": {"url": "https://tartinebakery.com"}, "as_of": null, "confidence": "high"}}, "enrichment_timestamp": "2026-10-21T04:31:17.449209Z", "id": "tartine"}
{"success": true, "attributes": {"phone": {"value": {"number": "+14158759370"}, "as_of": null, "confidence": "high"}, "website": {"value": {"url": "https://www.philzcoffee.com/"}, "as_of": null, "confidence": "high"}}, "enrichment_timestamp": "2026-10-21T04:31:17.661324Z", "id": "philz-24th"}
```

- A job takes 1 to 10,000 places.
- The CLI checks the file before it sends anything. An empty name, a latitude without a longitude, a coordinate that isn't a number, or more than 10,000 rows stops the command with exit code 2 and the line number, and you pay nothing.
- A retried submit sends the same `Idempotency-Key`, so a retry replays the same job.
- If a submit fails without a clear answer, the job may still exist. The error then gives a key. Run the same command with `--idempotency-key KEY` to replay that job instead of paying for a second one.
- `--no-wait` prints the submitted job and exits. Fetch the rows later with `voygr jobs results BATCH_ID`.
- Ctrl-C stops waiting and leaves the job running. The CLI prints the `jobs results` and `jobs cancel` commands for it and exits 130.
- For a failed or cancelled job, the CLI prints the rows it processed, then exits 1.

## Research fields and cost

`voygr pricing` lists every rate. This output is cut to the three that apply to this CLI:

```bash
voygr --human pricing
```

```
Single-record validation and enrichment: 1 credit per request
Standard attributes: 1 credit per place
Research fields: 1 credit per place per field
```

Standard attributes cost 1 credit per place however many you ask for. A research field is any other attribute name, and costs 1 credit per place per field. A request can mix both and pays for each. `owners` and `key_people` cost 1 credit for the names plus 1 for the roles or titles, per place, and 1 more per included contact. `--summary` doesn't change the cost. Credits never expire.

Give a research field a name, with a plain question after `=` if you like. Add `--estimate` to see the cost first:

```bash
voygr enrich "Blue Bottle Coffee" "66 Mint St, San Francisco, CA 94103" --country US \
  --research "wheelchair_accessible=Is the entrance step-free?" --estimate
```

```json
{"success": true, "id": null, "attributes": {}, "meta": {"steps": 0, "tool_calls": 0, "cost_units": 0, "stopped_reason": "estimate_only", "estimated_credits": 1}, "enrichment_timestamp": "2026-10-21T04:20:37.420669Z", "request_id": "req_d8f11cddc7a9480d83d65f39"}
```

With `--human`:

```
Estimated cost: 1 credit. Nothing was charged.
```

Drop `--estimate` to run it:

```json
{"success": true, "id": null, "attributes": {"wheelchair_accessible": {"value": true, "confidence": "medium", "status": "confirmed"}}, "meta": {"steps": 3, "tool_calls": 5, "cost_units": 5, "stopped_reason": "completed", "estimated_credits": 1, "lanes": {"deep": 1}}, "enrichment_timestamp": "2026-10-21T04:20:56.513604Z", "request_id": "req_c5b06866b2644540a287fe44"}
```

The CLI waits up to 3,700 seconds for an enrich request with a research field, and up to 90 seconds for any other request.

`--estimate` prices one place, so you can't use it with `--file`. For a file, multiply the cost of one place by the number of places: 3 places with 2 standard attributes and 1 research field cost 3 × (1 + 1) = 6 credits. `--max-credits N` refuses a request that would cost more than N. With `--file`, the limit applies to each place.

## Command reference

| Command | What it does |
| --- | --- |
| `voygr signup EMAIL [--name NAME]` | Email a new API key. |
| `voygr recover EMAIL` | Email a recovery link. Clicking it replaces the key, and the old key stops working. |
| `voygr login API_KEY` | Save the key to `~/.config/voygr/config.json`. |
| `voygr logout` | Delete the saved key. |
| `voygr validate NAME [ADDRESS]` | Check that a place exists and whether it is open. |
| `voygr enrich NAME [ADDRESS]` | Look up attributes and research fields for a place. |
| `voygr validate --file CSV`, `voygr enrich --file CSV` | Run a CSV of places as one job. Add `--no-wait` to return straight away. |
| `voygr jobs status BATCH_ID` | Show a job's status and progress. |
| `voygr jobs results BATCH_ID` | Wait for a job, then print its rows as JSON Lines. |
| `voygr jobs cancel BATCH_ID` | Stop a job. Rows already processed stay billed and downloadable. |
| `voygr usage` | Show your credits. |
| `voygr pricing` | Show the rates. No key needed. |
| `voygr completions [bash\|zsh\|fish]` | Print the line that turns on tab completion. |

`validate` and `enrich` take these options for a single place:

| Option | Meaning |
| --- | --- |
| `--country CC` | Two-letter country code, for example `US`. |
| `--lat N --lng N` | Coordinates. Give both or neither. |
| `--id ID` | Your own ID for the place. It is echoed in the result. |

`enrich` also takes:

| Option | Meaning |
| --- | --- |
| `--attr NAME` | A standard attribute. Repeat for several. Default: the whole standard set. |
| `--research NAME[=DESCRIPTION]` | A research field. Repeat for several. |
| `--summary` | Also return a short summary of the place. |
| `--estimate` | Print the estimated cost. Nothing runs and nothing is charged. |
| `--max-credits N` | Refuse a place that would cost more than N credits. With `--file`, the limit applies to each row. |

### Global options

Put these before the command, as in `voygr --human usage`.

| Option | Meaning |
| --- | --- |
| `--api-key KEY` | API key for this command. |
| `--base-url URL` | API base URL. Default `https://api.voygr.tech`. |
| `--human` | Readable text instead of JSON. |
| `--debug` | Print each HTTP request's method, URL, status and time to stderr. |
| `--version` | Print the version. |

The key comes from `--api-key`, then the `VOYGR_API_KEY` environment variable, then the saved config file. `VOYGR_BASE_URL` sets the base URL when `--base-url` isn't given.

### Examples

```bash
voygr --human validate "Blue Bottle Coffee" "66 Mint St, San Francisco, CA 94103" --country US
```

```
Existence: 1.00 confidence
Status:    closed (permanent)
Request:   req_a3343dde884742b7a24925fc
```

```bash
voygr --human enrich "Blue Bottle Coffee" "66 Mint St, San Francisco, CA 94103" --country US --attr phone --attr website --attr opening_hours
```

```
phone: {"number":"+15106533394"} (medium)
website: {"url":"https://bluebottlecoffee.com"} (high)
opening_hours: {"days":{"monday":"closed","tuesday":"closed","wednesday":"closed","thursday":"closed","friday":"closed","saturday":"closed","sunday":"closed"}} (medium)
```

`one.csv` holds the Tartine Bakery row from `places.csv`:

```bash
voygr validate --file one.csv --no-wait
```

```json
{"batch_id": "batch_01M5EBNC3G8TSM96ZP8GCF060D", "type": "validate", "status": "queued", "created_at": "2026-10-21T04:31:41Z", "total_items": 1, "eta_seconds": 1, "eta_completion_at": "2026-10-21T04:31:42Z"}
```

```bash
voygr jobs results batch_01M5EBNC3G8TSM96ZP8GCF060D
```

```jsonl
{"id": "tartine", "success": true, "existence_confidence": 0.9979, "closure_confidence": 0.005980588495731354, "operational_status": {"status": "open", "closure_confidence": 0.005980588495731354, "closure_probability": 0.005980588495731354, "closure_reason": null}, "error": null, "error_code": null, "validation_timestamp": "2026-10-21T04:31:41.629553Z"}
```

```bash
voygr jobs status batch_01M5EBMFVJJBSABVKJZDCBGSBW
```

This example leaves out the download `url`. It is a presigned link that expires in about 15 minutes, and `voygr jobs results` fetches a fresh one when it needs to.

```json
{"batch_id": "batch_01M5EBMFVJJBSABVKJZDCBGSBW", "type": "enrich", "status": "completed", "created_at": "2026-10-21T04:31:12Z", "started_at": "2026-10-21T04:31:12Z", "completed_at": "2026-10-21T04:31:20Z", "total_items": 3, "progress": {"processed": 3, "succeeded": 3, "failed": 0}, "results": {"format": "jsonl.gz", "total_items": 3, "files": [{"size_bytes": 313, "sha256": "89a17518fd9e911dd70ab51e51c245e9a777d093f5c0e17504eb141fa0bab9ab", "expires_at": "2026-10-21T04:46:31Z"}]}}
```

```bash
voygr --human jobs status batch_01M5EBMFVJJBSABVKJZDCBGSBW
```

```
Job batch_01M5EBMFVJJBSABVKJZDCBGSBW: completed
Progress: 3/3, 0 failed
```

```bash
voygr usage
```

Cut to 6 of its fields:

```json
{"tier": "free", "available": 2487, "owed": 0, "period": "lifetime", "status": "active", "validation_timestamp": "2026-10-21T04:32:26Z"}
```

```bash
voygr recover you@example.com
```

```json
{"success": true, "message": "If an account exists for that email, a recovery link has been sent."}
```

```bash
voygr logout
```

```json
{"success": true, "message": "API key removed"}
```

```bash
voygr completions zsh
```

```
# Add this to your shell profile:
eval "$(_VOYGR_COMPLETE=zsh_source voygr)"
```

### Output, errors and exit codes

Results are JSON on stdout. Bulk rows are JSON Lines, one per input row. API and network errors go to stderr as JSON:

```bash
voygr jobs status batch_nope
```

```json
{"error": "NOT_FOUND", "message": "NOT_FOUND: Batch not found"}
```

A mistake on the command line prints a usage message instead:

```bash
voygr validate "Tartine Bakery" --lat 37.76
```

```
Usage: voygr validate [OPTIONS] [NAME] [ADDRESS]
Try 'voygr validate --help' for help.

Error: --lat and --lng go together
```

| Exit code | Meaning |
| --- | --- |
| `0` | Success |
| `1` | API error, network error, or a job that failed or was cancelled |
| `2` | Usage error, or a CSV that can't be sent |
| `130` | Ctrl-C while waiting for a job |

### Retries

The CLI retries a failed request up to 3 times, with exponential backoff. It honours `Retry-After` up to 60 seconds. `validate`, `enrich`, `signup` and `recover` retry only on 429. Job submits, job reads, result downloads and `jobs cancel` also retry on 500, 502, 503 and 504. Job submits also retry timeouts and connection errors, with the same `Idempotency-Key` and body. No other call retries them.

## Python library

```python
import os

from voygr import APIError, Client

with Client(api_key=os.environ["VOYGR_API_KEY"], retries=3) as client:
    place = client.validate("Tartine Bakery", address="600 Guerrero St, San Francisco, CA 94110", country="US")
    print(place["operational_status"]["status"])

    details = client.enrich("Tartine Bakery", address="600 Guerrero St, San Francisco, CA 94110", country="US",
                            attributes=["phone", "website"])
    print(details["attributes"]["website"]["value"])

    job = client.submit_validate_job([
        {"poi_name": "Tartine Bakery", "address": "600 Guerrero St, San Francisco, CA 94110", "id": "tartine"},
        {"poi_name": "Philz Coffee", "address": "3101 24th St, San Francisco, CA 94110", "id": "philz-24th"},
    ])
    client.wait_for_job(job["batch_id"])
    for row in client.iter_job_results(job["batch_id"]):
        print(row["id"], row["operational_status"]["status"])

    try:
        client.get_job("batch_nope")
    except APIError as e:
        print(e.status_code, e.error_code)
```

```
open
{'url': 'https://tartinebakery.com'}
tartine open
philz-24th closed
404 NOT_FOUND
```

The constructor is `Client(api_key=None, base_url="https://api.voygr.tech", debug=False, transport=None, retries=0)`. Retries are off unless you set `retries`. Every method returns the parsed JSON as a `dict`. An HTTP error raises `APIError`, with `status_code` and `error_code`.

| Method | Calls |
| --- | --- |
| `validate(poi_name, **fields)` | `POST /v1/validate`. Fields include `address`, `country`, `latitude`, `longitude` and `id`. |
| `enrich(poi_name, *, attributes=None, **fields)` | `POST /v1/enrich`. `attributes` holds standard names and research fields as `{"name": ..., "description": ...}`. Other request options pass through as keywords, for example `estimate_only=True`. |
| `submit_validate_job(pois, *, idempotency_key=None)` | `POST /v1/jobs/validate` with 1 to 10,000 request dicts. |
| `submit_enrich_job(pois, *, idempotency_key=None)` | `POST /v1/jobs/enrich`, the same way. |
| `get_job(batch_id)` | `GET /v1/jobs/{batch_id}` |
| `cancel_job(batch_id)` | `DELETE /v1/jobs/{batch_id}` |
| `wait_for_job(batch_id, *, poll_interval=5.0, timeout=None, on_progress=None)` | Polls until the job is `completed`, `failed` or `cancelled` and returns that status. Raises `TimeoutError` after `timeout` seconds, and never starts a poll after that. |
| `iter_job_results(batch_id)` | Downloads the result files and yields one row at a time, in input order. |
| `usage()` | `GET /v1/usage` |
| `pricing()` | `GET /v1/pricing` |
| `signup(email, name)` | `POST /signup` |
| `recover(email)` | `POST /recover` |

## Links

- [API documentation](https://api.voygr.tech/docs/)
- [llms.txt](https://api.voygr.tech/llms.txt)
- [OpenAPI spec](https://api.voygr.tech/openapi.json)
- [Rates as JSON](https://api.voygr.tech/v1/pricing)
- [PlaceCall](https://github.com/voygr-tech/placecall), Voygr's API for transactional AI phone calls
- [API terms of service](https://voygr.tech/terms-api/)

## Licence

MIT
