"""Small cross-platform plain-text clipboard polling for FlowSwitch.

Only text is synchronized in this milestone. Clipboard images and rich formats
are intentionally left for a later step.
"""
import os
import subprocess
import threading
import time

MAX_CLIPBOARD_CHARS = 32_000
POLL_INTERVAL = 0.5

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _user32.OpenClipboard.argtypes = [wintypes.HWND]
    _user32.OpenClipboard.restype = wintypes.BOOL
    _user32.CloseClipboard.argtypes = []
    _user32.CloseClipboard.restype = wintypes.BOOL
    _user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    _user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    _user32.GetClipboardData.argtypes = [wintypes.UINT]
    _user32.GetClipboardData.restype = wintypes.HANDLE
    _user32.EmptyClipboard.argtypes = []
    _user32.EmptyClipboard.restype = wintypes.BOOL
    _user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    _user32.SetClipboardData.restype = wintypes.HANDLE

    _kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    _kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    _kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalLock.restype = ctypes.c_void_p
    _kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalUnlock.restype = wintypes.BOOL
    _kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalFree.restype = wintypes.HGLOBAL


def read_clipboard_text():
    """Return clipboard text, or None when text cannot currently be read."""
    if os.name == "nt":
        opened = False
        try:
            opened = bool(_user32.OpenClipboard(None))
            if not opened or not _user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                return None
            handle = _user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return None
            pointer = _kernel32.GlobalLock(handle)
            if not pointer:
                return None
            try:
                text = ctypes.wstring_at(pointer)
            finally:
                _kernel32.GlobalUnlock(handle)
            return text if len(text) <= MAX_CLIPBOARD_CHARS else None
        except (OSError, ValueError):
            return None
        finally:
            if opened:
                _user32.CloseClipboard()

    try:
        result = subprocess.run(
            ["pbpaste"], capture_output=True, timeout=1.5, check=False
        )
        if result.returncode != 0:
            return None
        text = result.stdout.decode("utf-8", errors="replace")
        return text if len(text) <= MAX_CLIPBOARD_CHARS else None
    except (OSError, subprocess.SubprocessError):
        return None


def write_clipboard_text(text):
    """Write plain text to the local clipboard. Return True on success."""
    if not isinstance(text, str) or len(text) > MAX_CLIPBOARD_CHARS:
        return False

    if os.name == "nt":
        # Encode explicitly as UTF-16LE: Python counts a non-BMP emoji as one
        # character, while Windows clipboard text stores it as a surrogate pair.
        encoded = text.encode("utf-16-le") + b"\x00\x00"
        encoded_size = len(encoded)
        handle = _kernel32.GlobalAlloc(GMEM_MOVEABLE, encoded_size)
        if not handle:
            return False
        pointer = _kernel32.GlobalLock(handle)
        if not pointer:
            _kernel32.GlobalFree(handle)
            return False
        try:
            ctypes.memmove(pointer, encoded, encoded_size)
        finally:
            _kernel32.GlobalUnlock(handle)

        opened = False
        transferred = False
        try:
            opened = bool(_user32.OpenClipboard(None))
            if not opened or not _user32.EmptyClipboard():
                return False
            if not _user32.SetClipboardData(CF_UNICODETEXT, handle):
                return False
            transferred = True  # Windows owns the handle after success.
            return True
        except OSError:
            return False
        finally:
            if opened:
                _user32.CloseClipboard()
            if not transferred:
                _kernel32.GlobalFree(handle)

    try:
        result = subprocess.run(
            ["pbcopy"], input=text.encode("utf-8"), timeout=2.0, check=False
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


class ClipboardMonitor:
    """Poll local text clipboard and send changes without echoing remote updates."""
    def __init__(self, send_callback, stop_event=None):
        self.send_callback = send_callback
        self.stop_event = stop_event or threading.Event()
        self._lock = threading.RLock()
        self._last_seen = None

    def apply_remote_text(self, text):
        if not isinstance(text, str) or len(text) > MAX_CLIPBOARD_CHARS:
            return
        with self._lock:
            current = read_clipboard_text()
            if current == text:
                self._last_seen = text
                return
            if write_clipboard_text(text):
                self._last_seen = text

    def run(self):
        # Establish a baseline rather than overwriting either computer's clipboard
        # immediately on connection.
        self._last_seen = read_clipboard_text()
        while not self.stop_event.wait(POLL_INTERVAL):
            with self._lock:
                current = read_clipboard_text()
                if current is None or current == self._last_seen:
                    continue
                self._last_seen = current
            if len(current) <= MAX_CLIPBOARD_CHARS:
                try:
                    self.send_callback({"type": "clipboard_text", "text": current})
                except Exception:
                    # Clipboard polling must never affect input forwarding/failsafe.
                    pass
