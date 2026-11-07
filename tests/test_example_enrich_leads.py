import csv
import importlib
import json
from pathlib import Path

import pytest
from click.testing import CliRunner


@pytest.fixture
def enrich_command(example_api):
    assert Path("examples/enrich_leads/main.py").is_file(), "Lead enrichment example is missing"
    return importlib.import_module("examples.enrich_leads.main").main


def run(command, files):
    return CliRunner().invoke(command, [*map(str, files), "--idempotency-key", "lead-enrich-001"])


def test_enriches_business_and_owner_contacts(enrich_command, example_api, example_files):
    example_api.results = [
        {"id": "row-2", "success": True, "attributes": {
            "phone": {"value": {"number": "+15125550102"}, "confidence": "high"},
            "email": {"value": None, "confidence": "low"},
            "website": {"value": {"url": "https://example.com"}, "confidence": "medium"},
            "owners": {"value": [{"name": "Jane Example", "role": "Owner", "phone": None,
                                   "email": "jane@example.com"}], "status": "confirmed"},
        }},
        {"id": "row-1", "success": True, "attributes": {}},
    ]
    result = run(enrich_command, example_files)
    assert result.exit_code == 0, result.output
    with example_files[1].open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[1]["notes"] == "café note"
    assert rows[1]["id"] == "crm-duplicate"
    assert json.loads(rows[1]["voygr_phone"]) == {"value": {"number": "+15125550102"}, "confidence": "high"}
    assert json.loads(rows[1]["voygr_owners"]) == {
        "value": [{"name": "Jane Example", "role": "Owner", "phone": None, "email": "jane@example.com"}],
        "status": "confirmed",
    }
    assert json.loads(rows[1]["voygr_email"]) == {"value": None, "confidence": "low"}
    assert json.loads(rows[0]["voygr_owners"]) is None
    request = example_api.requests[0]
    assert request.url.path == "/v1/jobs/enrich"
    assert request.headers["Idempotency-Key"] == "lead-enrich-001"
    expected = ["phone", "email", "website", {"name": "owners", "include": ["phone", "email"]}]
    assert all(place["attributes"] == expected for place in json.loads(request.content)["pois"])


@pytest.mark.parametrize("attributes", [None, [], "bad", {"phone": "bad"}, {"owners": []}, {"email": {"confidence": "high"}}])
def test_malformed_attributes_fail_without_output(enrich_command, example_api, example_files, attributes):
    example_api.results[0]["attributes"] = attributes
    example_api.results[1]["attributes"] = {}
    result = run(enrich_command, example_files)
    assert result.exit_code != 0
    assert "Error:" in result.stderr
    assert not example_files[1].exists()


def test_null_attribute_is_preserved(enrich_command, example_api, example_files):
    for row in example_api.results:
        row["attributes"] = {"owners": None}
    result = run(enrich_command, example_files)
    assert result.exit_code == 0, result.output
    with example_files[1].open(newline="", encoding="utf-8") as f:
        assert next(csv.DictReader(f))["voygr_owners"] == "null"


def test_existing_enrichment_columns_are_rejected(enrich_command, example_api, example_files):
    example_files[0].write_text("name,voygr_owners\nFirst,original-owner\n", encoding="utf-8")
    result = run(enrich_command, example_files)
    assert result.exit_code != 0
    assert example_api.requests == []
    assert not example_files[1].exists()
