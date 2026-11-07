"""CSV preservation, preflight and bulk-result integrity, over real SDK HTTP."""
import csv
import json

import pytest
from click.testing import CliRunner


def invoke(command, files, key="closed-example"):
    return CliRunner().invoke(command, [*map(str, files), "--idempotency-key", key])


def test_preserves_columns_and_matches_shuffled_results(closed_command, example_api, example_files):
    result = invoke(closed_command, example_files)
    assert result.exit_code == 0, result.output
    with example_files[1].open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert [row["name"] for row in rows] == ["First", "Café"]
    assert [row["id"] for row in rows] == ["crm-duplicate", "crm-duplicate"]
    assert [row["notes"] for row in rows] == ["keep me", "café note"]
    assert [row["voygr_status"] for row in rows] == ["open", "closed"]
    assert rows[1]["voygr_closure_reason"] == "permanent"
    submitted = example_api.requests[0]
    assert submitted.headers["Idempotency-Key"] == "closed-example"
    assert submitted.headers["X-API-Key"] == "test-example-key"
    assert [p["id"] for p in json.loads(submitted.content)["pois"]] == ["row-1", "row-2"]
    assert "x-api-key" not in example_api.requests[-1].headers
    assert "batch-example" in result.stderr
    assert "test-example-key" not in result.output


@pytest.mark.parametrize("text", [
    "", "name\n", "name,Name\nFirst,Second\n", "name,notes,Notes\nFirst,a,b\n",
    "name,\nFirst,a\n", "name,address\nFirst,address,extra\n", "name,address\nFirst\n",
    "name,voygr_status\nFirst,open\n", "name, VOYGR_ERROR \nFirst,old error\n",
    "name,address\n,1 Main St\n",
])
def test_bad_csv_sends_nothing(closed_command, example_api, example_files, text):
    example_files[0].write_text(text, encoding="utf-8")
    result = invoke(closed_command, example_files)
    assert result.exit_code != 0
    assert example_api.requests == []
    assert not example_files[1].exists()


@pytest.mark.parametrize("problem", ["exists", "missing-parent", "missing-key", "blank-key", "same-input"])
def test_preflight_preserves_files(closed_command, example_api, example_files, monkeypatch, problem):
    source, output = example_files
    key = "closed-example"
    if problem == "exists":
        output.write_text("keep existing output", encoding="utf-8")
    elif problem == "missing-parent":
        output = output / "missing" / "out.csv"
    elif problem == "missing-key":
        monkeypatch.delenv("VOYGR_API_KEY")
    elif problem == "blank-key":
        key = "   "
    else:
        output = source
    original = source.read_bytes()
    result = invoke(closed_command, (source, output), key)
    assert result.exit_code != 0
    assert example_api.requests == []
    assert source.read_bytes() == original
    if problem == "exists":
        assert output.read_text() == "keep existing output"


@pytest.mark.parametrize("problem", ["duplicate", "missing", "extra", "missing-success", "bad-success", "not-object"])
def test_schema_drift_leaves_output_untouched(closed_command, example_api, example_files, problem):
    if problem == "duplicate":
        example_api.results[0]["id"] = "row-1"
    elif problem == "missing":
        example_api.results.pop()
    elif problem == "extra":
        example_api.results[0]["id"] = "row-99"
    elif problem == "missing-success":
        del example_api.results[0]["success"]
    elif problem == "bad-success":
        example_api.results[0]["success"] = "true"
    else:
        example_api.results[0] = []
    result = invoke(closed_command, example_files)
    assert result.exit_code != 0
    assert not example_files[1].exists()
    assert "Error:" in result.stderr


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_failed_job_keeps_recovery_id(closed_command, example_api, example_files, status):
    example_api.status = status
    result = invoke(closed_command, example_files)
    assert result.exit_code != 0
    assert not example_files[1].exists()
    assert "batch-example" in result.stderr
    assert status in result.stderr


def test_row_error_is_written_with_original_row(closed_command, example_api, example_files):
    example_api.results[0] = {"id": "row-2", "success": False,
                              "error_code": "LOOKUP_FAILED", "error": "Try later"}
    result = invoke(closed_command, example_files)
    assert result.exit_code == 1
    with example_files[1].open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[1]["name"] == "Café"
    assert rows[1]["voygr_status"] == ""
    assert json.loads(rows[1]["voygr_error"]) == {"error_code": "LOOKUP_FAILED", "error": "Try later"}
    assert rows[0]["voygr_error"] == ""


def test_sdk_error_is_clear_and_has_recovery_key(closed_command, example_api, example_files, monkeypatch):
    import examples.csv_jobs as jobs
    from voygr import APIError
    def rejected(**kwargs):
        raise APIError("QUOTA_EXCEEDED: no credits", status_code=402)
    monkeypatch.setattr(jobs, "Client", rejected)
    result = invoke(closed_command, example_files)
    assert result.exit_code == 1
    assert "QUOTA_EXCEEDED" in result.stderr
    assert "closed-example" in result.stderr
    assert not example_files[1].exists()


def test_unwritable_output_fails_before_submission(closed_command, example_api, example_files, monkeypatch):
    from pathlib import Path
    original_open = Path.open
    def denied(path, *args, **kwargs):
        if path == example_files[1]:
            raise PermissionError("Output cannot be created")
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", denied)
    result = invoke(closed_command, example_files)
    assert result.exit_code == 1
    assert example_api.requests == []
    assert not example_files[1].exists()


def test_one_snapshot_keeps_results_with_the_queried_business(closed_command, example_api, example_files, monkeypatch):
    import examples.csv_jobs as jobs
    original_read = jobs.read_places
    def edited_between_reads(path):
        places = original_read(path)
        text = example_files[0].read_text(encoding="utf-8")
        example_files[0].write_text(text.replace("First,", "Different Store,"), encoding="utf-8")
        return places
    monkeypatch.setattr(jobs, "read_places", edited_between_reads)
    result = invoke(closed_command, example_files)
    assert result.exit_code == 0, result.output
    submitted = json.loads(example_api.requests[0].content)["pois"]
    with example_files[1].open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert submitted[0]["poi_name"] == "First"
    assert rows[0]["name"] == "First"
    assert rows[0]["voygr_status"] == "open"


def test_failed_job_releases_reserved_output(closed_command, example_api, example_files):
    example_api.status = "failed"
    result = invoke(closed_command, example_files)
    assert result.exit_code == 1
    assert not example_files[1].exists()


@pytest.mark.parametrize("header", ["id", " ID "])
def test_long_customer_id_is_preserved_without_api_limits(closed_command, example_api, example_files, header):
    customer_id = "customer-" + "x" * 1000
    example_files[0].write_text(f"name,{header}\nFirst,{customer_id}\nCafé,{customer_id}\n", encoding="utf-8")
    result = invoke(closed_command, example_files)
    assert result.exit_code == 0, result.output
    submitted = json.loads(example_api.requests[0].content)["pois"]
    assert [p["id"] for p in submitted] == ["row-1", "row-2"]
    with example_files[1].open(newline="", encoding="utf-8") as f:
        assert [r[header] for r in csv.DictReader(f)] == [customer_id, customer_id]


def test_id_only_row_is_invalid_before_submission(closed_command, example_api, example_files):
    example_files[0].write_text("name,id\n,customer-1\nFirst,customer-2\n", encoding="utf-8")
    result = invoke(closed_command, example_files)
    assert result.exit_code != 0
    assert example_api.requests == []


@pytest.mark.parametrize("text,line", [
    ("name,address\n\n,1 Main St\n", 3),
    ('name,id,latitude,longitude\nFirst,"customer\nwrapped",37,-122\nSecond,customer2,nan,-122\n', 4),
    ('name,address,id\nFirst,"1 Main St\nUnit A",customer1\n\n,2 Main St,customer2\n', 5),
    ('name,id\n,"customer\nwrapped"\n', 3),
])
def test_validation_error_names_original_source_line(closed_command, example_api, example_files, text, line):
    example_files[0].write_text(text, encoding="utf-8")
    result = invoke(closed_command, example_files)
    assert result.exit_code == 1
    assert f"Error: line {line}:" in result.stderr
    assert example_api.requests == []
    assert not example_files[1].exists()
