# Check which stores in a spreadsheet are closed

Give this example a CSV of businesses. It adds open/closed status and a closure
reason using the [VOYGR](https://voygr.tech) Validate API. You keep your original
columns, customer IDs and row order.

## Install

Clone [dev-tools](https://github.com/voygr-tech/dev-tools) and run this from its root:

```sh
python -m pip install -e .
```

Use Python 3.10 or newer. [Get a free API key](https://api.voygr.tech/checkout),
then set `VOYGR_API_KEY` in your environment. Keep your key out of source files.
The checkout page lists your credits and current rates.

## Run

Save this as `stores.csv` in the repository root. These are example inputs;
the script looks up their current status when you run it.

```csv
name,address,country,id,notes
Tartine Bakery,"600 Guerrero St, San Francisco, CA 94110",US,crm-1,San Francisco
Blue Bottle Coffee,"66 Mint St, San Francisco, CA 94103",US,crm-2,Check old branch
```

```sh
python -m examples.check_closed_stores.main stores.csv stores-checked.csv --idempotency-key my-store-check-001
```

The command submits a bulk job and waits up to an hour. It adds:

| Column | Meaning |
| --- | --- |
| `voygr_status` | `open`, `closed`, `unknown` or `not_exists` |
| `voygr_closure_reason` | The API's closure reason, if available |
| `voygr_error` | A row error as JSON, or an empty cell |

`unknown` needs review. A high existence score does not establish that a shop
is open. Check `voygr_status` before removing a business from a list.

The input needs a `name` header. The SDK also accepts `address`, `country`,
`latitude` and `longitude`; give a full address to identify a particular branch.
Header names ignore case and surrounding spaces. A job takes up to 10,000 rows.
The script checks the whole file before submission and refuses existing output
files or columns that would collide with its output. It reserves an empty output
file before submission to check write access, then fills it after validating the
results. Caught failures remove that reservation. It reads one input snapshot so
edits during the job do not attach results to another business.

## Errors and recovery

The script prints the idempotency key and job ID to stderr. To retry an uncertain
submission, use the same key and identical input. Use a new key for a new check.
The API controls how long it retains job keys; keep the printed batch ID for recovery.

```sh
voygr jobs status BATCH_ID
voygr jobs results BATCH_ID
```

A failed/cancelled job leaves the output path untouched. The `jobs results`
command can retrieve processed rows. A completed job with row errors writes the
CSV and exits with code 1; inspect `voygr_error`. Authentication, malformed
responses and missing results also exit with code 1. `--timeout SECONDS` changes
the wait limit; timing out does not cancel the server job.

Read the [validation guide](https://api.voygr.tech/docs/guides/validate-business/)
and [API reference](https://api.voygr.tech/docs/). To do the same work from an
assistant, use [Prospecting MCP](https://github.com/voygr-tech/prospecting)
with its CSV upload, check and export tools.
