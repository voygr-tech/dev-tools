import csv

import pytest
from click.testing import CliRunner


@pytest.mark.parametrize("status", ["open", "closed", "unknown", "not_exists"])
def test_reports_status_without_guessing(closed_command, example_api, example_files, status):
    example_api.results[1]["operational_status"]["status"] = status
    result = CliRunner().invoke(closed_command, [*map(str, example_files), "--idempotency-key", "statuses"])
    assert result.exit_code == 0, result.output
    with example_files[1].open(newline="", encoding="utf-8") as f:
        assert next(csv.DictReader(f))["voygr_status"] == status
    assert example_api.requests[0].url.path == "/v1/jobs/validate"


@pytest.mark.parametrize("value", [None, {}, [], {"status": "unexpected"}, {"status": []}])
def test_rejects_unrecognized_status_schema(closed_command, example_api, example_files, value):
    example_api.results[0]["operational_status"] = value
    result = CliRunner().invoke(closed_command, [*map(str, example_files), "--idempotency-key", "bad-status"])
    assert result.exit_code != 0
    assert "Error:" in result.stderr
    assert not example_files[1].exists()
