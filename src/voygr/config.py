import json
import os
from pathlib import Path


def get_config_path() -> Path:
    return Path.home() / ".config" / "voygr"


def load_config(config_dir: Path | None = None) -> dict:
    config_dir = config_dir or get_config_path()
    config_file = config_dir / "config.json"
    if not config_file.exists():
        return {}
    try:
        return json.loads(config_file.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_api_key(api_key: str, config_dir: Path | None = None) -> None:
    config_dir = config_dir or get_config_path()
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.json"
    config = load_config(config_dir=config_dir)
    config["api_key"] = api_key
    fd = os.open(str(config_file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(json.dumps(config, indent=2) + "\n")


def delete_config(config_dir: Path | None = None) -> None:
    config_dir = config_dir or get_config_path()
    config_file = config_dir / "config.json"
    if config_file.exists():
        config_file.unlink()
