import json
import pytest
from voygr.config import load_config, save_api_key, delete_config, get_config_path


class TestSaveApiKey:
    def test_creates_dir_and_file(self, config_dir):
        save_api_key("pk_live_abc123", config_dir=config_dir)
        config_file = config_dir / "config.json"
        assert config_file.exists()
        data = json.loads(config_file.read_text())
        assert data["api_key"] == "pk_live_abc123"

    def test_overwrites_existing_key(self, config_dir):
        save_api_key("pk_live_old", config_dir=config_dir)
        save_api_key("pk_live_new", config_dir=config_dir)
        data = json.loads((config_dir / "config.json").read_text())
        assert data["api_key"] == "pk_live_new"


class TestLoadConfig:
    def test_returns_config_when_exists(self, config_dir):
        save_api_key("pk_live_abc123", config_dir=config_dir)
        config = load_config(config_dir=config_dir)
        assert config["api_key"] == "pk_live_abc123"

    def test_returns_empty_dict_when_no_file(self, config_dir):
        config = load_config(config_dir=config_dir)
        assert config == {}

    def test_returns_empty_dict_when_corrupt_json(self, config_dir):
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.json").write_text("not json{{{")
        config = load_config(config_dir=config_dir)
        assert config == {}


class TestDeleteConfig:
    def test_removes_config_file(self, config_dir):
        save_api_key("pk_live_abc123", config_dir=config_dir)
        delete_config(config_dir=config_dir)
        assert not (config_dir / "config.json").exists()

    def test_no_error_when_file_missing(self, config_dir):
        delete_config(config_dir=config_dir)  # should not raise


class TestGetConfigPath:
    def test_returns_xdg_path(self):
        path = get_config_path()
        assert path.name == "voygr"
        assert ".config" in str(path)
