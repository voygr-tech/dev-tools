# VOYGR examples

Run these Python examples against [VOYGR](https://voygr.tech) to check a business
list, find owner contacts or request a restaurant reservation by phone.

| Your task | Example |
| --- | --- |
| Which stores in my spreadsheet are closed? | [Check closed stores](check_closed_stores/) |
| Can I add owners, phone, email and website to my lead list? | [Enrich leads](enrich_leads/) |
| Can an AI agent call a restaurant and book a table? | [Book a table](book_table/) |

Clone this repository and run `python -m pip install -e .` from its root with
Python 3.10 or newer. Each example has its own command and sample inputs in
its README. Run the `python -m examples.…` commands from the repository root.

[Get a free API key](https://api.voygr.tech/checkout) and put it in an environment
variable, as each example describes. The checkout page shows current allowances
and rates. The CSV commands submit billable jobs; the phone example previews
its request until you confirm a call. Keep local input/output files and API keys
out of commits.

For assistant workflows, see [Prospecting MCP](https://github.com/voygr-tech/prospecting)
and [PlaceCall MCP](https://github.com/voygr-tech/placecall).
The [API docs](https://api.voygr.tech/docs/) describe the public contracts.

## Development checks

```sh
python -m pip install -e '.[dev]'
python -m pytest
python -m compileall -q examples
git diff --check
```

The tests replace HTTP with local transports. They do not spend credits or
place phone calls. This repository has no separate configured linter, type
checker or live-service integration suite.
