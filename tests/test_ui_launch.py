"""Single-instance guard for the history window (ui_launch)."""

import os

from clipboard_manager.ui_launch import (
    claim_ui_instance,
    release_ui_instance,
    ui_already_running,
)


def test_no_pidfile_means_not_running(tmp_path):
    assert ui_already_running(tmp_path) is False


def test_claim_then_running_then_release(tmp_path):
    assert claim_ui_instance(tmp_path) is True
    assert ui_already_running(tmp_path) is True
    release_ui_instance(tmp_path)
    assert ui_already_running(tmp_path) is False


def test_second_claim_rejected_while_first_alive(tmp_path):
    assert claim_ui_instance(tmp_path, pid=os.getpid()) is True
    # A second process (different pid, but we simulate with our own live pid
    # already recorded) must not take over the guard.
    assert claim_ui_instance(tmp_path, pid=os.getpid()) is False


def test_stale_pidfile_is_reclaimed(tmp_path):
    (tmp_path / "ui.pid").write_text("99999999")  # almost certainly dead
    assert ui_already_running(tmp_path) is False
    assert claim_ui_instance(tmp_path) is True
    assert ui_already_running(tmp_path) is True


def test_garbage_pidfile_is_not_running(tmp_path):
    (tmp_path / "ui.pid").write_text("not-a-number")
    assert ui_already_running(tmp_path) is False


def test_release_only_removes_own_pidfile(tmp_path):
    claim_ui_instance(tmp_path, pid=os.getpid())
    release_ui_instance(tmp_path, pid=os.getpid() + 1)  # not ours
    assert ui_already_running(tmp_path) is True
    release_ui_instance(tmp_path, pid=os.getpid())
    assert ui_already_running(tmp_path) is False


def test_zombie_pid_counts_as_dead(tmp_path, monkeypatch):
    # A zombie passes os.kill(pid, 0) but must not hold the single-instance
    # guard - otherwise one crashed window blocks every future launch.
    from clipboard_manager import ui_launch

    pidfile = tmp_path / "ui.pid"
    pidfile.write_text("424242")

    monkeypatch.setattr(ui_launch.os, "kill", lambda *_a: None)  # zombie passes kill(.., 0)

    real_path = ui_launch.Path

    class FakePath(type(real_path())):
        pass

    original_read_text = real_path.read_text

    def fake_read_text(self, *a, **k):
        if str(self) == "/proc/424242/stat":
            return "424242 (python3) Z 1 2 3"
        return original_read_text(self, *a, **k)

    monkeypatch.setattr(ui_launch.Path, "read_text", fake_read_text)
    assert ui_launch.ui_already_running(tmp_path) is False
    # And a running (sleeping) process with the same shape still counts as alive.
    def fake_read_text_running(self, *a, **k):
        if str(self) == "/proc/424242/stat":
            return "424242 (python3) S 1 2 3"
        return original_read_text(self, *a, **k)

    monkeypatch.setattr(ui_launch.Path, "read_text", fake_read_text_running)
    assert ui_launch.ui_already_running(tmp_path) is True
