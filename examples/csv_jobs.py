"""Shared CSV preservation and bulk-job plumbing for the two Places examples."""
import csv
import io
import json
import os
from collections.abc import Callable
from pathlib import Path

import click

from voygr import APIError, Client
from voygr.csv_input import read_places


def run_job(
    input_path: Path,
    output_path: Path,
    idempotency_key: str,
    fields: list[str],
    render: Callable[[dict], dict],
    *,
    attributes: list[str] | None = None,
    timeout: float = 3600,
) -> None:
    """Submit once, join by internal row ID, and create a new CSV after validation."""
    try:
        key = os.environ.get("VOYGR_API_KEY", "").strip()
        if not key:
            raise ValueError("Set VOYGR_API_KEY to your VOYGR API key")
        if not idempotency_key.strip():
            raise ValueError("Use a nonempty --idempotency-key; keep it for retries")
        if os.path.lexists(output_path):
            raise ValueError(f"Output already exists: {output_path}; choose a new path")
        if not output_path.parent.is_dir():
            raise ValueError(f"Output directory does not exist: {output_path.parent}")
        places = read_places(input_path)
        with input_path.open(newline="", encoding="utf-8-sig") as source:
            reader = csv.DictReader(source, strict=True)
            headers = reader.fieldnames or []
            normalized = [h.strip().lower() for h in headers]
            if not all(normalized) or len(set(normalized)) != len(normalized):
                raise ValueError("CSV needs nonempty, unique column names")
            reserved = [*fields, "voygr_error"]
            if set(normalized).intersection(reserved):
                raise ValueError("CSV already has an output column; rename the voygr_ columns")
            originals = []
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError(f"CSV line {reader.line_num}: row width differs from the header")
                if any(value.strip() for value in row.values()):
                    originals.append(row)
        if len(originals) != len(places):
            raise ValueError("CSV rows changed while reading; save the file and retry")
        for number, place in enumerate(places, 1):
            place["id"] = f"row-{number}"
            if attributes is not None:
                place["attributes"] = attributes

        click.echo(f"Idempotency key: {idempotency_key} (reuse with identical input for retries)", err=True)
        with Client(api_key=key, retries=3) as client:
            submit = client.submit_validate_job if attributes is None else client.submit_enrich_job
            submitted = submit(places, idempotency_key=idempotency_key)
            batch_id = submitted.get("batch_id") if isinstance(submitted, dict) else None
            if not isinstance(batch_id, str) or not batch_id:
                raise ValueError("Job response is missing batch_id; retry only with the same key and input")
            click.echo(f"Job: {batch_id}. Recover with: voygr jobs results {batch_id}", err=True)
            status = client.wait_for_job(batch_id, timeout=timeout)
            if status.get("status") != "completed":
                raise ValueError(f"Job {batch_id} ended with status {status.get('status')}; retrieve partial results with voygr jobs results")
            results = list(client.iter_job_results(batch_id))

        expected = {place["id"] for place in places}
        indexed = {}
        for row in results:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                raise ValueError("Result row is missing its string id")
            row_id = row["id"]
            if row_id not in expected or row_id in indexed:
                raise ValueError(f"Unexpected or duplicate result id: {row_id}")
            if not isinstance(row.get("success"), bool):
                raise ValueError(f"Result {row_id} is missing boolean success")
            indexed[row_id] = row
        if set(indexed) != expected:
            raise ValueError("Job results are missing input rows; output was not created")

        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=[*headers, *reserved])
        writer.writeheader()
        failed = 0
        for original, place in zip(originals, places):
            row = indexed[place["id"]]
            if row["success"]:
                derived = render(row)
                derived["voygr_error"] = ""
            else:
                failed += 1
                derived = {"voygr_error": json.dumps({
                    "error_code": row.get("error_code"), "error": row.get("error"),
                }, ensure_ascii=False)}
            writer.writerow({**original, **derived})
        # Exclusive creation also protects against a file appearing during the job.
        with output_path.open("x", newline="", encoding="utf-8") as destination:
            destination.write(buffer.getvalue())
        click.echo(f"Wrote {len(originals)} rows to {output_path}", err=True)
        if failed:
            raise click.ClickException(f"{failed} row(s) failed; inspect voygr_error in the output")
    except (APIError, OSError, ValueError, csv.Error, TimeoutError) as exc:
        raise click.ClickException(str(exc)) from exc
