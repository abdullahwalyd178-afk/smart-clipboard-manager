"""Sensitive-data protection for the clipboard watcher.

This is *actual filtering*, not a warning: it wraps the clipboard provider and
drops captures before they ever reach the database.

Two independent mechanisms, each configurable:

1. Foreground-app exclusion (Windows only): when the active window belongs to
   an excluded process (e.g. a password manager) or its title contains an
   excluded keyword, nothing is captured. On non-Windows systems there is no
   reliable stdlib way to read the foreground window, so this mechanism is
   inactive there and ``last_skip_reason`` stays honest about that.

2. Suspected-secret detection (all platforms): text that looks like a
   credential - a password/token assignment, a JWT, an AWS/GitHub key, a
   payment-card number (Luhn-checked), or a single long high-entropy token -
   is not stored. Heuristics cannot catch every secret; this is a seatbelt,
   not a guarantee. Pause capture remains the certain way to keep a copy out
   of the history.

Nothing here phones home: detection is local regex/entropy checks only.
"""

from __future__ import annotations

import ctypes
import logging
import math
import re
import sys
from dataclasses import dataclass, field

from .watcher import ClipboardProvider

logger = logging.getLogger(__name__)

# --- suspected-secret patterns ---------------------------------------------

_KEY_VALUE_SECRET = re.compile(
    r"(?i)(?:password|passwd|pwd|passcode|secret|api[_-]?key|access[_-]?token|"
    r"auth[_-]?token|private[_-]?key|client[_-]?secret)\s*[:=]\s*\S+"
)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}\b")
_AWS_KEY = re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b")
_GITHUB_TOKEN = re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|github_pat_[A-Za-z0-9_]{20,}\b")
_PRIVATE_KEY_BLOCK = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")
_CARD_NUMBER = re.compile(r"\b(?:\d[ -]?){13,19}\b")


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = {}
    for ch in value:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(value)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def looks_like_secret(text: str) -> str | None:
    """Return a short reason if the text looks like a credential, else None."""
    if _KEY_VALUE_SECRET.search(text):
        return "password/token assignment"
    if _PRIVATE_KEY_BLOCK.search(text):
        return "private key block"
    if _JWT.search(text):
        return "JWT"
    if _AWS_KEY.search(text):
        return "AWS access key"
    if _GITHUB_TOKEN.search(text):
        return "GitHub token"
    for match in _CARD_NUMBER.finditer(text):
        digits = re.sub(r"\D", "", match.group(0))
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            return "payment card number"
    # A bare high-entropy token: one long "word" with no spaces, mixed
    # character classes, e.g. an API key pasted alone.
    stripped = text.strip()
    if 24 <= len(stripped) <= 200 and " " not in stripped and "\n" not in stripped:
        classes = sum(
            bool(re.search(pattern, stripped))
            for pattern in (r"[a-z]", r"[A-Z]", r"\d")
        )
        if classes >= 3 and _shannon_entropy(stripped) >= 4.2:
            return "high-entropy token"
    return None


# --- foreground window detection (Windows) ---------------------------------


def active_window_info() -> tuple[str, str] | None:
    """Return (process_name, window_title) of the foreground window.

    Windows only. Returns None on other platforms or on any failure - callers
    must treat None as "unknown", never as "safe to skip filtering" nor as
    "matches an exclusion".
    """
    if sys.platform != "win32":
        return None
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        length = user32.GetWindowTextLengthW(hwnd)
        title_buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title_buf, length + 1)
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process = ""
        psapi = ctypes.windll.psapi
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x0400 | 0x0010, False, pid.value)  # QUERY_INFORMATION|VM_READ
        if handle:
            try:
                name_buf = ctypes.create_unicode_buffer(260)
                if psapi.GetModuleBaseNameW(handle, None, name_buf, 260):
                    process = name_buf.value
            finally:
                kernel32.CloseHandle(handle)
        return (process.lower(), title_buf.value)
    except Exception:
        logger.debug("foreground window lookup failed", exc_info=True)
        return None


# --- filtering provider -----------------------------------------------------


@dataclass
class SensitiveFilterProvider(ClipboardProvider):
    """ClipboardProvider wrapper that drops sensitive captures.

    ``excluded_apps``: lowercase process names (e.g. "keepassxc.exe"); when the
    foreground window belongs to one, capture is skipped entirely.
    ``excluded_window_keywords``: case-insensitive substrings of the window
    title (e.g. "bank", "كلمة المرور") that also skip capture.
    ``skip_suspected_secrets``: drop text clips that look like credentials.
    """

    inner: ClipboardProvider
    excluded_apps: list[str] = field(default_factory=list)
    excluded_window_keywords: list[str] = field(default_factory=list)
    skip_suspected_secrets: bool = True
    # Set after each skipped capture; None when the last check captured fine.
    # Useful for a tray tooltip / log line, never contains the dropped content.
    last_skip_reason: str | None = None

    def _foreground_excluded(self) -> str | None:
        info = active_window_info()
        if info is None:
            return None
        process, title = info
        if process and process in {a.strip().lower() for a in self.excluded_apps}:
            return f"excluded app: {process}"
        lowered = title.lower()
        for keyword in self.excluded_window_keywords:
            if keyword.strip() and keyword.strip().lower() in lowered:
                return f"excluded window title keyword: {keyword.strip()}"
        return None

    def get_text(self) -> str | None:
        reason = self._foreground_excluded()
        if reason:
            self.last_skip_reason = reason
            logger.info("capture skipped (%s)", reason)
            return None
        text = self.inner.get_text()
        if text and self.skip_suspected_secrets:
            reason = looks_like_secret(text)
            if reason:
                self.last_skip_reason = f"suspected secret ({reason})"
                logger.info("capture skipped (%s)", self.last_skip_reason)
                return None
        self.last_skip_reason = None
        return text

    def get_image_png_bytes(self) -> bytes | None:
        reason = self._foreground_excluded()
        if reason:
            self.last_skip_reason = reason
            logger.info("capture skipped (%s)", reason)
            return None
        return self.inner.get_image_png_bytes()

    def set_text(self, text: str) -> None:
        self.inner.set_text(text)
