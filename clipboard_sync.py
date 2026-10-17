"""Cross-platform text and image clipboard synchronization for FlowSwitch."""
import base64
import hashlib
import io
import os
import subprocess
import threading

from PIL import Image, ImageGrab

MAX_CLIPBOARD_CHARS = 32_000
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # PNG payload before base64 encoding
POLL_INTERVAL = 0.5

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    CF_UNICODETEXT = 13
    CF_DIB = 8
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

elif __import__("sys").platform == "darwin":
    # PyObjC provides native NSPasteboard access for images on macOS.
    from AppKit import NSPasteboard, NSImage
    from Foundation import NSData


def _image_to_png_bytes(image):
    try:
        image = image.convert("RGBA")
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True)
        data = output.getvalue()
        return data if 0 < len(data) <= MAX_IMAGE_BYTES else None
    except Exception:
        return None


def read_clipboard_image():
    """Return a normalized PNG byte string if the clipboard currently has an image."""
    if os.name == "nt":
        try:
            grabbed = ImageGrab.grabclipboard()
            if isinstance(grabbed, Image.Image):
                return _image_to_png_bytes(grabbed)
            return None  # Clipboard contains paths or another non-image format.
        except Exception:
            return None

    if __import__("sys").platform == "darwin":
        try:
            pasteboard = NSPasteboard.generalPasteboard()
            data = pasteboard.dataForType_("public.tiff")
            if data is None:
                return None
            raw = data.bytes().tobytes()
            with Image.open(io.BytesIO(raw)) as image:
                image.load()
                return _image_to_png_bytes(image)
        except Exception:
            return None

    return None


def write_clipboard_image(png_data):
    """Write PNG image bytes to the native clipboard; return success."""
    if not isinstance(png_data, bytes) or not 0 < len(png_data) <= MAX_IMAGE_BYTES:
        return False
    try:
        with Image.open(io.BytesIO(png_data)) as source:
            source.load()
            image = source.convert("RGBA")
    except Exception:
        return False

    if os.name == "nt":
        # Windows CF_DIB expects the BMP data without its 14-byte file header.
        try:
            bmp = io.BytesIO()
            image.convert("RGB").save(bmp, format="BMP")
            dib = bmp.getvalue()[14:]
            handle = _kernel32.GlobalAlloc(GMEM_MOVEABLE, len(dib))
            if not handle:
                return False
            pointer = _kernel32.GlobalLock(handle)
            if not pointer:
                _kernel32.GlobalFree(handle)
                return False
            try:
                ctypes.memmove(pointer, dib, len(dib))
            finally:
                _kernel32.GlobalUnlock(handle)

            opened = False
            transferred = False
            try:
                opened = bool(_user32.OpenClipboard(None))
                if not opened or not _user32.EmptyClipboard():
                    return False
                if not _user32.SetClipboardData(CF_DIB, handle):
                    return False
                transferred = True
                return True
            finally:
                if opened:
                    _user32.CloseClipboard()
                if not transferred:
                    _kernel32.GlobalFree(handle)
        except Exception:
            return False

    if __import__("sys").platform == "darwin":
        try:
            output = io.BytesIO()
            image.save(output, format="TIFF")
            raw = output.getvalue()
            native_data = NSData.dataWithBytes_length_(raw, len(raw))
            pasteboard = NSPasteboard.generalPasteboard()
            pasteboard.clearContents()
            return bool(pasteboard.setData_forType_(native_data, "public.tiff"))
        except Exception:
            return False

    return False


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

    if __import__("sys").platform == "darwin":
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
    return None


def write_clipboard_text(text):
    """Write plain text to the local clipboard. Return True on success."""
    if not isinstance(text, str) or len(text) > MAX_CLIPBOARD_CHARS:
        return False

    if os.name == "nt":
        encoded = text.encode("utf-16-le") + b"\x00\x00"
        handle = _kernel32.GlobalAlloc(GMEM_MOVEABLE, len(encoded))
        if not handle:
            return False
        pointer = _kernel32.GlobalLock(handle)
        if not pointer:
            _kernel32.GlobalFree(handle)
            return False
        try:
            ctypes.memmove(pointer, encoded, len(encoded))
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
            transferred = True
            return True
        except OSError:
            return False
        finally:
            if opened:
                _user32.CloseClipboard()
            if not transferred:
                _kernel32.GlobalFree(handle)

    if __import__("sys").platform == "darwin":
        try:
            result = subprocess.run(
                ["pbcopy"], input=text.encode("utf-8"), timeout=2.0, check=False
            )
            return result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
    return False


class ClipboardMonitor:
    """Poll text and images; remote writes are marked seen to prevent echoes."""
    def __init__(self, send_callback, stop_event=None):
        self.send_callback = send_callback
        self.stop_event = stop_event or threading.Event()
        self._lock = threading.RLock()
        self._last_seen = None

    @staticmethod
    def _signature(kind, data):
        if kind == "image":
            return (kind, hashlib.sha256(data).hexdigest())
        return (kind, data)

    def apply_remote_text(self, text):
        if not isinstance(text, str) or len(text) > MAX_CLIPBOARD_CHARS:
            return
        with self._lock:
            if read_clipboard_text() == text:
                self._last_seen = self._signature("text", text)
                return
            if write_clipboard_text(text):
                self._last_seen = self._signature("text", text)

    def apply_remote_image(self, encoded):
        if not isinstance(encoded, str):
            return
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, base64.binascii.Error):
            return
        if not 0 < len(data) <= MAX_IMAGE_BYTES:
            return
        signature = self._signature("image", data)
        with self._lock:
            current = read_clipboard_image()
            if current is not None and self._signature("image", current) == signature:
                self._last_seen = signature
                return
            if write_clipboard_image(data):
                self._last_seen = signature

    def _current_clipboard(self):
        image = read_clipboard_image()
        if image is not None:
            return self._signature("image", image), image
        text = read_clipboard_text()
        if text is not None and len(text) <= MAX_CLIPBOARD_CHARS:
            return self._signature("text", text), text
        return None, None

    def run(self):
        # Baseline the current clipboard; do not overwrite it on connection.
        self._last_seen, _ = self._current_clipboard()
        while not self.stop_event.wait(POLL_INTERVAL):
            try:
                signature, data = self._current_clipboard()
                if signature is None or signature == self._last_seen:
                    continue
                self._last_seen = signature
                if signature[0] == "image":
                    payload = {
                        "type": "clipboard_image",
                        "data": base64.b64encode(data).decode("ascii"),
                    }
                else:
                    payload = {"type": "clipboard_text", "text": data}
                self.send_callback(payload)
            except Exception:
                # Clipboard polling must never affect input forwarding/failsafe.
                pass
