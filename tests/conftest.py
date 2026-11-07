import pytest
from pathlib import Path


@pytest.fixture
def config_dir(tmp_path):
    """Provides a temporary config directory, patching the default location."""
    return tmp_path / "voygr"


@pytest.fixture
def example_api(monkeypatch):
    """Exercise example commands through the real SDK, replacing HTTP only."""
    import gzip
    import hashlib
    import importlib
    import json

    import httpx
    from voygr import Client

    assert Path("examples/csv_jobs.py").is_file(), "CSV job example is missing"
    jobs = importlib.import_module("examples.csv_jobs")

    class API:
        def __init__(self):
            self.requests = []
            self.status = "completed"
            self.results = [
                {"id": "row-2", "success": True,
                 "operational_status": {"status": "closed", "closure_reason": "permanent"}},
                {"id": "row-1", "success": True,
                 "operational_status": {"status": "open", "closure_reason": None}},
            ]

        def __call__(self, request):
            self.requests.append(request)
            blob = gzip.compress(b"\n".join(json.dumps(row).encode() for row in self.results))
            if request.url.host == "results.example.test":
                return httpx.Response(200, content=blob)
            if request.method == "POST":
                return httpx.Response(202, json={"batch_id": "batch-example", "status": "queued"})
            return httpx.Response(200, json={
                "batch_id": "batch-example", "status": self.status,
                "progress": {"processed": 2, "succeeded": 2, "failed": 0},
                "results": {"format": "jsonl.gz", "total_items": len(self.results), "files": [{
                    "url": "https://results.example.test/rows?signature=private",
                    "sha256": hashlib.sha256(blob).hexdigest(), "size_bytes": len(blob),
                }]},
            })

    api = API()
    monkeypatch.setenv("VOYGR_API_KEY", "test-example-key")
    monkeypatch.setattr(jobs, "Client", lambda **kw: Client(transport=httpx.MockTransport(api), **kw))
    return api


@pytest.fixture
def example_files(tmp_path):
    source = tmp_path / "input.csv"
    source.write_text(
        'name,address,country,id,notes\n'
        'First,"1 Main St, Austin, TX",US,crm-duplicate,keep me\n'
        'Café,"2 Main St, Austin, TX",US,crm-duplicate,café note\n', encoding="utf-8"
    )
    return source, tmp_path / "output.csv"


@pytest.fixture
def closed_command(example_api):
    import importlib
    assert Path("examples/check_closed_stores/main.py").is_file(), "Closed stores example is missing"
    return importlib.import_module("examples.check_closed_stores.main").main
