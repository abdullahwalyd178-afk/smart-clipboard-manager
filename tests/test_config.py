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


import pytest


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"retention_days": -1}, "retention_days"),
        ({"max_items": -1}, "max_items"),
        ({"poll_interval_seconds": 0}, "poll_interval_seconds"),
        ({"poll_interval_seconds": -0.5}, "poll_interval_seconds"),
        ({"ocr_engine": "missing"}, "ocr_engine"),
        ({"ocr_language": ""}, "ocr_language"),
        ({"copy_ocr_result_to_clipboard": "yes"}, "copy_ocr_result_to_clipboard"),
    ],
)
def test_invalid_config_values_are_rejected(overrides, message):
    with pytest.raises(ValueError, match=message):
        Config(**overrides)


def test_load_rejects_malformed_config(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError, match="Could not read configuration"):
        Config.load(path)


def test_load_rejects_non_object_json(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        Config.load(path)


def test_load_rejects_invalid_persisted_values(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"max_items": -4}), encoding="utf-8")
    with pytest.raises(ValueError, match="max_items"):
        Config.load(path)

@pytest.mark.parametrize("interval", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_poll_intervals_are_rejected(interval):
    with pytest.raises(ValueError, match="finite number"):
        Config(poll_interval_seconds=interval)


def test_non_string_ocr_engine_is_rejected():
    with pytest.raises(ValueError, match="ocr_engine"):
        Config(ocr_engine=[])
