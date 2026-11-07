# Enrich a small-business lead list with owners and contacts

Add business phone, email and website, plus owners with direct phone and email,
to a CSV of leads. This example uses the [VOYGR](https://voygr.tech) Enrich API
and keeps your original columns, customer IDs and row order.

## Install

Clone [dev-tools](https://github.com/voygr-tech/dev-tools) and run this from its root:

```sh
python -m pip install -e .
```

Use Python 3.10 or newer. [Get a free API key](https://api.voygr.tech/checkout),
then set `VOYGR_API_KEY` in your environment. Keep your key out of source files.
Check your credit balance and rates before running a list:

```sh
voygr usage
voygr pricing
```

## Run

Save this as `leads.csv` in the repository root:

```csv
name,address,country,id,segment
Tartine Bakery,"600 Guerrero St, San Francisco, CA 94110",US,crm-1,bakery
Zuni Café,"1658 Market St, San Francisco, CA 94102",US,crm-2,restaurant
```

```sh
python -m examples.enrich_leads.main leads.csv leads-enriched.csv --idempotency-key my-lead-enrichment-001
```

The command submits one bulk job, waits up to an hour, and adds `voygr_phone`,
`voygr_email`, `voygr_website`, `voygr_owners` and `voygr_error`. The four
attribute columns contain JSON so you keep the API's value and supporting fields.
For example, a phone object can include a confidence score; owner results have
names, roles and requested contacts. Owner columns do not have confidence scores.

An owner contact of `null` means the lookup found no answer. A missing contact
key means it was not looked up or the lookup failed. An owner `value` of `null`
does not establish that the business has no owner. An omitted or null attribute
appears as JSON `null` in this example; inspect `voygr_error` for row failures.

## Cost and recovery

The example requests standard business contacts plus
`{"name":"owners","include":["phone","email"]}`. Owner names, roles and
contacts consume research credits. The [owner guide](https://api.voygr.tech/docs/guides/owners-and-key-people/)
explains the units and estimation options. Completed research can cost credits
even when it finds no answer. A free key lets you try a small list; check the
[checkout page](https://api.voygr.tech/checkout) for its current allowance.

The script prints a job ID and idempotency key to stderr. If submission is
uncertain, retry with the same key and identical input. Use the batch ID to read
status or retrieve results without submitting another job:

```sh
voygr jobs status BATCH_ID
voygr jobs results BATCH_ID
```

Existing output files, duplicate/empty headers and conflicting output columns
stop the command before submission. A completed job with failed rows writes the
CSV and exits with code 1. Failed/cancelled jobs and malformed responses leave
the output path untouched. `--timeout SECONDS` changes the wait limit; the job
continues on the server if the local wait ends.

## Use an assistant instead

[Prospecting MCP](https://github.com/voygr-tech/prospecting) supports CSV upload,
`places_fill` and CSV export through an assistant. Connect it and ask to add
owners and business contacts to your list; review its quote before paid work.

See the [API documentation](https://api.voygr.tech/docs/) for request fields
and current contracts.
