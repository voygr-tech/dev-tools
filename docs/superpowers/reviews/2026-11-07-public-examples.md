# Public examples engineering record

- Human source: Yarik Markov, VOYG-503 comment `01a1b6f3-4a9f-72cb-82a8-23959d63ef3d`, authorizes the examples direction. Standing workspace policy delegates technical design, implementation and repository delivery.
- Installed process: Superpowers 7.0.1; workspace standing approval exception retained.
- Repository choice: existing public `voygr-tech/dev-tools`; dedicated Multica checkout and branch `agent/gtm-engineer/03ff7beb758a`. Native checkout uses a separate clone, not a linked worktree. No other checkout is modified.
- Design review: independent fresh builder `design_review` read the design and reported “Nothing important left before planning.” No unresolved product questions.
- Plan self-review: spec coverage, interfaces, step granularity and five review-focus cases checked. Inline execution selected internally under standing authorization.
- Baseline: `python -m pytest tests -q`, 496 passed in 2.83s. Existing integration tests replace the HTTP network with MockTransport. No live-service integration command, linter or type checker is configured.
- Prose skills: loaded stop-slop and humanizer 3.1.0 from the installed workspace copies in VOYG-538; supporting stop-slop references read.

## Independent code review and verification

A fresh reviewer inspected f5c0322..add6677 and ran the full suite: 569 passed. Two important findings were reproduced before fixes: unwritable output discovered after submission, and input mutation between reads causing incorrect row attribution. Both regression tests failed against the reviewed implementation and passed after the shared-path fixes. The updated full suite passes 572 tests. No live paid requests ran.

A documentation finding exposed conflicting result-finality advice in the public calling guide and maintained PlaceCall README. The example now directs readers to the detailed outcome and linked guide instead of promising that any non-null value is final. A minor diagnostic improvement remains deferred: surface bounded API error codes/messages instead of HTTP status alone.

Build: python -m pip wheel --no-deps . succeeded for voygr 0.4.0; no release/tag was created. All three --help commands and a fictional-number booking preview succeeded. Compile checks and git diff --check passed. All 11 README link targets returned HTTP 200 on GET; the documented MCP endpoint is a protocol URL rather than a web page. HTTP HEAD is unsupported by the documentation/checkout routes, so link verification used GET.

Public OpenAPI confirms flat POST /calls, GET /calls/{call_id}, and bulk enrichment rows accepting structured research attributes. Repository ruleset main: PR + 1 approval requires one approving GitHub review, with no bypass actors. The authenticated PR author is yamarkov and cannot self-approve. This remains a real merge requirement; settings and permissions were not changed.

## Execution ledger

```text
# SDD ledger — plan: docs/superpowers/plans/2026-11-07-public-examples.md

Pre-flight: Tasks 1 and 2 share run_job; plan signatures agree. Task 3 shares no code.
Baseline: 496 passed.
Task 1: complete (commits 3007238..07d699c, tests: ../.venv/bin/python -m pytest -q → 531 passed in 2.37s)
Task 2: Ruling: request owners with include=[phone,email] and widen the shared attribute annotation to list[str | dict] — public owner docs say a bare owners string returns no direct contacts; the example should include the requested owner contacts — cost if wrong: readers spend more research credits than a names-only lookup; README states the charge categories.
Task 2: complete (commits 07d699c..cba7d1f, tests: ../.venv/bin/python -m pytest tests/test_example_enrich_leads.py -q → 9 passed in 0.17s)
Task 3: complete (commits cba7d1f..add6677, tests: ../.venv/bin/python -m pytest -q → 569 passed in 4.76s)
Final: fixed unwritable output preflight — test_unwritable_output_fails_before_submission RED→GREEN; output is exclusively reserved before HTTP and removed on caught failure; suite 572/572.
Final: fixed same-count input mutation — test_one_snapshot_keeps_results_with_the_queried_business RED→GREEN; validation and preservation use one captured snapshot; suite 572/572.
Final: Ruling: reserve the exact output path before paid submission instead of creating it after serialization — only actual exclusive creation proves the destination is writable; caught failures clean up only our inode — cost if wrong: an abruptly killed process may leave an empty reservation; choose another output path to recover by batch ID.
Final: Ruling: regrade unconditional result-finality prose as a factual correctness issue — current calling guide and maintained PlaceCall README disagree, so the example delegates codes to the guide and tells readers to inspect booking details, without claiming unknown outcomes are final — cost if wrong: readers must inspect the detailed result instead of relying on a shortcut. Prose-only correction needs no mirrored text test.
Final: minor (deferred): call errors show HTTP status and retry guidance, without bounded API error codes/messages; richer diagnostics remain future work.
Final: Ruling: no live billing/call verification — protected actions are outside test authorization; risk: no live-service confirmation. Fixed API origin intentionally supports the public flat call response; risk: alternative deployments need adaptation. Existing SDK polling-schema robustness remains unchanged; risk: malformed upstream job status may surface the SDK error.
```
