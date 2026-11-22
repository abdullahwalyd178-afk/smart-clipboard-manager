import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clipboard_manager.storage import ClipboardStore  # noqa: E402


@pytest.fixture
def store(tmp_path):
    s = ClipboardStore(tmp_path / "history.db")
    yield s
    s.close()


@pytest.fixture
def images_dir(tmp_path):
    d = tmp_path / "images"
    d.mkdir()
    return d
