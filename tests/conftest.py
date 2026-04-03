import pytest
from pathlib import Path


@pytest.fixture
def config_dir(tmp_path):
    """Provides a temporary config directory, patching the default location."""
    return tmp_path / "voygr"
