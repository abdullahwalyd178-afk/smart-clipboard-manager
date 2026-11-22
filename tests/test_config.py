"""Config defaults, persistence, and tolerance of unknown keys."""

import json

from clipboard_manager.config import Config


def test_defaults():
    cfg = Config()
    assert cfg.retention_days == 3  # items older than 3 days are deleted
    assert cfg.ocr_engine == "tesseract"
    assert cfg.copy_ocr_result_to_clipboard is True
    assert cfg.max_items == 500


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "config.json"
    cfg = Config(retention_days=7, ocr_language="eng+ara", data_dir=str(tmp_path))
    cfg.save(path)

    loaded = Config.load(path)
    assert loaded.retention_days == 7
    assert loaded.ocr_language == "eng+ara"


def test_load_ignores_unknown_keys(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"retention_days": 10, "future_option": True}))
    loaded = Config.load(path)
    assert loaded.retention_days == 10
    assert not hasattr(loaded, "future_option")


def test_load_missing_file_returns_defaults(tmp_path):
    loaded = Config.load(tmp_path / "nope.json")
    assert loaded.retention_days == 3
