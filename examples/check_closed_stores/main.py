"""Add business open/closed status to a CSV using the VOYGR Validate API."""
from pathlib import Path

import click

from examples.csv_jobs import run_job


def render(row: dict) -> dict:
    status = row.get("operational_status")
    if not isinstance(status, dict) or status.get("status") not in ("open", "closed", "unknown", "not_exists"):
        raise ValueError("Unrecognized operational_status in validation response")
    reason = status.get("closure_reason")
    if reason is not None and not isinstance(reason, str):
        raise ValueError("Unrecognized closure_reason in validation response")
    return {"voygr_status": status["status"], "voygr_closure_reason": reason or ""}


@click.command()
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("output_path", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--idempotency-key", required=True, help="Unique job key. Reuse with identical input to retry.")
@click.option("--timeout", default=3600.0, type=click.FloatRange(min=0, min_open=True), show_default=True)
def main(input_path: Path, output_path: Path, idempotency_key: str, timeout: float) -> None:
    """Check which stores in INPUT_PATH are closed; create OUTPUT_PATH."""
    run_job(input_path, output_path, idempotency_key,
            ["voygr_status", "voygr_closure_reason"], render, timeout=timeout)


if __name__ == "__main__":
    main()
