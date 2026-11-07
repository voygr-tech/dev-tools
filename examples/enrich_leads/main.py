"""Add business and owner contacts to a lead CSV using VOYGR Enrich."""
import json
from pathlib import Path

import click

from examples.csv_jobs import run_job


def render(row: dict) -> dict:
    attributes = row.get("attributes")
    if not isinstance(attributes, dict):
        raise ValueError("Unrecognized attributes in enrichment response")
    output = {}
    for name in ("phone", "email", "website", "owners"):
        attribute = attributes.get(name)
        if attribute is not None and (not isinstance(attribute, dict) or "value" not in attribute):
            raise ValueError(f"Unrecognized {name} attribute in enrichment response")
        output[f"voygr_{name}"] = json.dumps(attribute, ensure_ascii=False)
    return output


@click.command()
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("output_path", type=click.Path(dir_okay=False, path_type=Path))
@click.option("--idempotency-key", required=True, help="Unique job key. Reuse with identical input to retry.")
@click.option("--timeout", default=3600.0, type=click.FloatRange(min=0, min_open=True), show_default=True)
def main(input_path: Path, output_path: Path, idempotency_key: str, timeout: float) -> None:
    """Enrich leads in INPUT_PATH; create OUTPUT_PATH with contact attributes."""
    run_job(input_path, output_path, idempotency_key,
            ["voygr_phone", "voygr_email", "voygr_website", "voygr_owners"], render,
            attributes=["phone", "email", "website", {"name": "owners", "include": ["phone", "email"]}],
            timeout=timeout)


if __name__ == "__main__":
    main()
