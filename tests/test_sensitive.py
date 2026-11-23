"""Sensitive-data protection: secret heuristics and the filtering provider.

All fixture secrets are synthetic patterns, never real credentials.
"""

import clipboard_manager.sensitive as sensitive
from clipboard_manager.sensitive import (
    SensitiveFilterProvider,
    looks_like_secret,
)
from clipboard_manager.watcher import ClipboardProvider


class FakeInner(ClipboardProvider):
    def __init__(self, text=None, image=None):
        self._text = text
        self._image = image
        self.set_calls = []

    def get_text(self):
        return self._text

    def get_image_png_bytes(self):
        return self._image

    def set_text(self, text):
        self.set_calls.append(text)


# -- heuristics ---------------------------------------------------------------


def test_password_assignment_detected():
    assert looks_like_secret("db_password=Sup3rSecret!") is not None
    assert looks_like_secret("API_KEY: abcdefghijklmnop123456") is not None


def test_known_token_formats_detected():
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJVadQssw5c"
    assert looks_like_secret(jwt) == "JWT"
    assert looks_like_secret("key is AKIAIOSFODNN7EXAMPLE here") == "AWS access key"
    assert looks_like_secret("ghp_" + "a1B2" * 10) == "GitHub token"
    assert "private key" in looks_like_secret("-----BEGIN PRIVATE KEY----- stuff")


def test_luhn_checked_card_detected():
    assert looks_like_secret("my card 4111 1111 1111 1111") == "payment card number"
    # Same shape but fails Luhn - not flagged as a card.
    assert looks_like_secret("4111 1111 1111 1112") != "payment card number"


def test_high_entropy_bare_token_detected():
    assert looks_like_secret("Xk9Qm2Lp7Vb4Nh8Ts3Rf6Gy1") is not None


def test_normal_text_not_flagged():
    assert looks_like_secret("meet at cairo university at 5pm") is None
    assert looks_like_secret("123456") is None  # too short, low entropy
    assert looks_like_secret("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa") is None  # low entropy
    assert looks_like_secret("call +20 115 250 3331 tomorrow") is None


# --- filtering provider ------------------------------------------------------


def test_suspected_secret_is_dropped_not_stored():
    inner = FakeInner(text="password=Tr0ub4dor&3")
    provider = SensitiveFilterProvider(inner, skip_suspected_secrets=True)
    assert provider.get_text() is None
    assert "suspected secret" in provider.last_skip_reason


def test_normal_text_passes_and_reason_cleared():
    inner = FakeInner(text="ordinary note")
    provider = SensitiveFilterProvider(inner)
    assert provider.get_text() == "ordinary note"
    assert provider.last_skip_reason is None


def test_detection_can_be_disabled():
    inner = FakeInner(text="password=Tr0ub4dor&3")
    provider = SensitiveFilterProvider(inner, skip_suspected_secrets=False)
    assert provider.get_text() == "password=Tr0ub4dor&3"


def test_excluded_app_skips_capture(monkeypatch):
    monkeypatch.setattr(
        sensitive, "active_window_info", lambda: ("keepassxc.exe", "KeePassXC")
    )
    inner = FakeInner(text="anything", image=b"png-bytes")
    provider = SensitiveFilterProvider(inner, excluded_apps=["keepassxc.exe"])
    assert provider.get_text() is None
    assert provider.get_image_png_bytes() is None
    assert "excluded app" in provider.last_skip_reason


def test_excluded_window_keyword_skips_capture(monkeypatch):
    monkeypatch.setattr(
        sensitive, "active_window_info", lambda: ("firefox.exe", "My Bank - Login")
    )
    provider = SensitiveFilterProvider(
        FakeInner(text="anything"), excluded_window_keywords=["bank"]
    )
    assert provider.get_text() is None
    assert "window title" in provider.last_skip_reason


def test_unknown_foreground_window_does_not_filter(monkeypatch):
    """Non-Windows (or lookup failure) -> None -> no exclusion, capture works."""
    monkeypatch.setattr(sensitive, "active_window_info", lambda: None)
    provider = SensitiveFilterProvider(
        FakeInner(text="fine"), excluded_apps=["keepassxc.exe"]
    )
    assert provider.get_text() == "fine"


def test_set_text_passes_through():
    inner = FakeInner()
    provider = SensitiveFilterProvider(inner)
    provider.set_text("hello")
    assert inner.set_calls == ["hello"]


def test_skip_reason_reset_after_allowed_image_capture(monkeypatch):
    """Regression: a successful image capture must clear the last skip reason."""
    import clipboard_manager.sensitive as S

    inner = FakeInner(text=None, image=b"png-bytes")
    provider = SensitiveFilterProvider(inner=inner, excluded_window_keywords=["bank"])

    monkeypatch.setattr(S, "active_window_info", lambda: ("chrome.exe", "My Bank - Login"))
    assert provider.get_image_png_bytes() is None
    assert provider.last_skip_reason is not None

    monkeypatch.setattr(S, "active_window_info", lambda: ("chrome.exe", "ordinary page"))
    assert provider.get_image_png_bytes() == b"png-bytes"
    assert provider.last_skip_reason is None
