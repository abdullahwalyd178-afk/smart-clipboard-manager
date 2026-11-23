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
