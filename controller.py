
import argparse
import ctypes
import json
import queue
import socket
import signal
import threading
import time
from ctypes import wintypes

PORT = 24800

WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0201, 0x0202
WM_RBUTTONDOWN, WM_RBUTTONUP = 0x0204, 0x0205
WM_MBUTTONDOWN, WM_MBUTTONUP = 0x0207, 0x0208
WM_MOUSEWHEEL, WM_MOUSEHWHEEL = 0x020A, 0x020E
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0104, 0x0105

WH_KEYBOARD_LL, WH_MOUSE_LL = 13, 14
LLMHF_INJECTED, LLKHF_INJECTED = 0x00000001, 0x00000010
HOTKEY = "Ctrl + Alt + F12"
HEARTBEAT_INTERVAL = 0.5
HEARTBEAT_TIMEOUT = 2.0
OUTBOUND_QUEUE_LIMIT = 1000

# Use WinDLL with use_last_error=True so ctypes can retrieve
# the actual Windows error when an API call fails.
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

ULONG_PTR = (
    ctypes.c_ulonglong
    if ctypes.sizeof(ctypes.c_void_p) == 8
    else ctypes.c_ulong
)

LRESULT = ctypes.c_ssize_t
HHOOK = ctypes.c_void_p
HINSTANCE = ctypes.c_void_p


class POINT(ctypes.Structure):
    _fields_ = [
        ("x", wintypes.LONG),
        ("y", wintypes.LONG),
    ]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(
    LRESULT,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM,
)

# Configure the Windows API signatures explicitly.
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = HINSTANCE

user32.SetWindowsHookExW.argtypes = [
    ctypes.c_int,
    HOOKPROC,
    HINSTANCE,
    wintypes.DWORD,
]
user32.SetWindowsHookExW.restype = HHOOK

user32.UnhookWindowsHookEx.argtypes = [HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL

user32.CallNextHookEx.argtypes = [
    HHOOK,
    ctypes.c_int,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
user32.CallNextHookEx.restype = LRESULT

user32.GetMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG),
    wintypes.HWND,
    wintypes.UINT,
    wintypes.UINT,
]
user32.GetMessageW.restype = ctypes.c_int

user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.TranslateMessage.restype = wintypes.BOOL

user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = LRESULT

user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int

user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = wintypes.BOOL

user32.ShowCursor.argtypes = [wintypes.BOOL]
user32.ShowCursor.restype = ctypes.c_int

user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.PostQuitMessage.restype = None


VK_NAMES = {
    0x08: "Key.backspace",
    0x09: "Key.tab",
    0x0D: "Key.enter",
    0x10: "Key.shift",
    0x11: "Key.ctrl",
    0x12: "Key.alt",
    0x13: "Key.pause",
    0x14: "Key.caps_lock",
    0x1B: "Key.esc",
    0x20: "Key.space",
    0x21: "Key.page_up",
    0x22: "Key.page_down",
    0x23: "Key.end",
    0x24: "Key.home",
    0x25: "Key.left",
    0x26: "Key.up",
    0x27: "Key.right",
    0x28: "Key.down",
    0x2D: "Key.insert",
    0x2E: "Key.delete",
    0x5B: "Key.cmd",
    0x5C: "Key.cmd",
    0x5D: "Key.menu",
    0xA0: "Key.shift",
    0xA1: "Key.shift",
    0xA2: "Key.ctrl",
    0xA3: "Key.ctrl",
    0xA4: "Key.alt",
    0xA5: "Key.alt",
    0x70: "Key.f1",
    0x71: "Key.f2",
    0x72: "Key.f3",
    0x73: "Key.f4",
    0x74: "Key.f5",
    0x75: "Key.f6",
    0x76: "Key.f7",
    0x77: "Key.f8",
    0x78: "Key.f9",
    0x79: "Key.f10",
    0x7A: "Key.f11",
    0x7B: "Key.f12",
    0x90: "Key.num_lock",
    0x91: "Key.scroll_lock",
    0xBA: "char:;",
    0xBB: "char:=",
    0xBC: "char:,",
    0xBD: "char:-",
    0xBE: "char:.",
    0xBF: "char:/",
    0xC0: "char:`",
    0xDB: "char:[",
    0xDC: "char:\\",
    0xDD: "char:]",
    0xDE: "char:'",
}

BUTTON_MESSAGES = {
    WM_LBUTTONDOWN: ("left", "down"),
    WM_LBUTTONUP: ("left", "up"),
    WM_RBUTTONDOWN: ("right", "down"),
    WM_RBUTTONUP: ("right", "up"),
    WM_MBUTTONDOWN: ("middle", "down"),
    WM_MBUTTONUP: ("middle", "up"),
}


def signed_word(value):
    value &= 0xFFFF
    return value - 0x10000 if value & 0x8000 else value


class FlowSwitchController:
    def __init__(self, host, port, token):
        self.host = host
        self.port = port
        self.token = token

        self.sock = None
        self.sock_file = None
        self.sock_lock = threading.Lock()
        self.state_lock = threading.RLock()
        self.outbound_queue = queue.Queue(maxsize=OUTBOUND_QUEUE_LIMIT)
        self.shutdown_event = threading.Event()
        self.connection_dead = False
        self.last_pong = time.monotonic()

        self.active = False
        self.last_toggle = 0.0

        self.screen_w = user32.GetSystemMetrics(0)
        self.screen_h = user32.GetSystemMetrics(1)
        self.center = (
            max(1, self.screen_w // 2),
            max(1, self.screen_h // 2),
        )
        self.return_y = self.screen_h // 2
        self.cursor_hidden = False

        # Physical Windows virtual keys currently held.
        self.keys_down = set()

        # String key IDs actually sent to the Mac.
        self.remote_keys = set()

        self.mouse_hook = None
        self.keyboard_hook = None

        # Keep callback objects alive for as long as the hooks exist.
        self.mouse_callback = HOOKPROC(self._mouse_hook_proc)
        self.keyboard_callback = HOOKPROC(self._keyboard_hook_proc)

    def send(self, payload):
        """Queue a protocol message quickly; hook callbacks never block on TCP."""
        if self.connection_dead or self.sock is None:
            return False
        try:
            self.outbound_queue.put_nowait(payload)
            return True
        except queue.Full:
            self.connection_lost("outbound queue overloaded")
            return False

    def _writer_loop(self):
        """Serialize all protocol writes on a worker thread."""
        while not self.shutdown_event.is_set():
            try:
                payload = self.outbound_queue.get(timeout=0.25)
            except queue.Empty:
                continue

            with self.sock_lock:
                sock = self.sock
            if sock is None or self.connection_dead:
                return

            try:
                data = (
                    json.dumps(payload, separators=(",", ":")) + "\n"
                ).encode("utf-8")
                sock.sendall(data)
            except OSError as exc:
                if not self.shutdown_event.is_set():
                    self.connection_lost(f"send failed: {exc}")
                return
            finally:
                self.outbound_queue.task_done()

    def connection_lost(self, reason):
        """Fail closed: stop suppressing local input before doing I/O cleanup."""
        with self.sock_lock:
            if self.connection_dead:
                return
            self.connection_dead = True
            sock = self.sock
            sock_file = self.sock_file
            self.sock = None
            self.sock_file = None

        # This transition is deliberately local-only. Once the connection is
        # gone, do not try to send releases over a dead socket.
        self.force_local_control(send_releases=False)
        print(f"\nFlowSwitch connection lost ({reason}). Windows input restored.")

        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

    def force_local_control(self, send_releases=True):
        """Always restore the local cursor and let physical input pass through."""
        with self.state_lock:
            was_active = self.active
            self.active = False
            self.show_cursor()
            if not send_releases or self.connection_dead:
                self.remote_keys.clear()

        if send_releases and not self.connection_dead:
            self.send_release_all()

        if was_active:
            print("Remote input OFF — control returned to Windows.")

    def hide_cursor(self):
        if not self.cursor_hidden:
            while user32.ShowCursor(False) >= 0:
                pass
            self.cursor_hidden = True

    def show_cursor(self):
        if self.cursor_hidden:
            while user32.ShowCursor(True) < 0:
                pass
            self.cursor_hidden = False

    def warp_cursor(self, x, y):
        user32.SetCursorPos(int(x), int(y))

    def set_active(self, enabled, move_to_edge=True):
        if enabled and (self.connection_dead or self.sock is None):
            return

        with self.state_lock:
            if self.active == enabled:
                return
            if enabled and (self.connection_dead or self.sock is None):
                return

            self.active = enabled
            if enabled:
                self.hide_cursor()
                self.warp_cursor(*self.center)
            else:
                self.show_cursor()
                if move_to_edge:
                    self.warp_cursor(
                        self.screen_w - 3,
                        max(1, min(self.screen_h - 2, self.return_y)),
                    )

        # Do all network I/O after releasing state_lock. This avoids lock-order
        # deadlocks when the reader and low-level hook callbacks run together.
        if enabled:
            if not self.send({"type": "enter"}):
                self.force_local_control(send_releases=False)
                return
            print("Remote input ON — move to the Mac's left edge to return.")
        else:
            self.send_release_all()
            print("Remote input OFF — control returned to Windows.")

    def send_release_all(self):
        with self.state_lock:
            keys = list(self.remote_keys)
            self.remote_keys.clear()

        for key_id in keys:
            if not self.send({"type": "key_up", "key": key_id}):
                return
        for button in ("left", "right", "middle"):
            if not self.send({
                "type": "click", "button": button, "action": "up"
            }):
                return

    def toggle(self):
        now = time.monotonic()
        if now - self.last_toggle < 0.4:
            return

        self.last_toggle = now
        self.set_active(not self.active)

    def key_id(self, vk):
        if vk in VK_NAMES:
            return VK_NAMES[vk]

        if 0x41 <= vk <= 0x5A:
            return "char:" + chr(vk).lower()

        if 0x30 <= vk <= 0x39:
            return "char:" + chr(vk)

        if 0x60 <= vk <= 0x69:
            return "char:" + chr(vk - 0x30)

        return None

    def _mouse_hook_proc(self, n_code, w_param, l_param):
        if n_code < 0:
            return user32.CallNextHookEx(
                self.mouse_hook, n_code, w_param, l_param
            )

        data = ctypes.cast(
            l_param, ctypes.POINTER(MSLLHOOKSTRUCT)
        ).contents

        # Ignore injected events so cursor recentering doesn't loop.
        if data.flags & LLMHF_INJECTED:
            return user32.CallNextHookEx(
                self.mouse_hook, n_code, w_param, l_param
            )

        msg = int(w_param)
        x, y = int(data.pt.x), int(data.pt.y)

        with self.state_lock:
            active = self.active

        if msg == WM_MOUSEMOVE:
            if not active:
                if x >= self.screen_w - 2:
                    self.return_y = y
                    self.set_active(True)
                    if not self.active:
                        return user32.CallNextHookEx(
                            self.mouse_hook, n_code, w_param, l_param
                        )
                    return 1

                return user32.CallNextHookEx(
                    self.mouse_hook, n_code, w_param, l_param
                )

            cx, cy = self.center
            dx, dy = x - cx, y - cy

            if dx or dy:
                if not self.send({
                    "type": "move",
                    "dx": dx,
                    "dy": dy,
                }) or not self.active:
                    return user32.CallNextHookEx(
                        self.mouse_hook, n_code, w_param, l_param
                    )
                self.warp_cursor(cx, cy)

            return 1 if self.active else user32.CallNextHookEx(
                self.mouse_hook, n_code, w_param, l_param
            )

        with self.state_lock:
            active = self.active

        if not active:
            return user32.CallNextHookEx(
                self.mouse_hook, n_code, w_param, l_param
            )

        if msg in BUTTON_MESSAGES:
            button, action = BUTTON_MESSAGES[msg]
            if not self.send({
                "type": "click",
                "button": button,
                "action": action,
            }) or not self.active:
                return user32.CallNextHookEx(
                    self.mouse_hook, n_code, w_param, l_param
                )
            return 1

        if msg in (WM_MOUSEWHEEL, WM_MOUSEHWHEEL):
            amount = signed_word(data.mouseData >> 16)

            if not self.send({
                "type": "scroll",
                "dx": amount if msg == WM_MOUSEHWHEEL else 0,
                "dy": amount if msg == WM_MOUSEWHEEL else 0,
            }) or not self.active:
                return user32.CallNextHookEx(
                    self.mouse_hook, n_code, w_param, l_param
                )
            return 1

        return user32.CallNextHookEx(
            self.mouse_hook, n_code, w_param, l_param
        )

    def _keyboard_hook_proc(self, n_code, w_param, l_param):
        if n_code < 0:
            return user32.CallNextHookEx(
                self.keyboard_hook, n_code, w_param, l_param
            )

        data = ctypes.cast(
            l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)
        ).contents

        if data.flags & LLKHF_INJECTED:
            return user32.CallNextHookEx(
                self.keyboard_hook, n_code, w_param, l_param
            )

        msg = int(w_param)
        vk = int(data.vkCode)

        is_down = msg in (WM_KEYDOWN, WM_SYSKEYDOWN)
        is_up = msg in (WM_KEYUP, WM_SYSKEYUP)

        if not (is_down or is_up):
            return user32.CallNextHookEx(
                self.keyboard_hook, n_code, w_param, l_param
            )

        if is_down:
            self.keys_down.add(vk)
        else:
            self.keys_down.discard(vk)

        ctrl = bool(
            self.keys_down.intersection({0x11, 0xA2, 0xA3})
        )
        alt = bool(
            self.keys_down.intersection({0x12, 0xA4, 0xA5})
        )

        if is_down and vk == 0x7B and ctrl and alt:
            self.toggle()
            return 1

        with self.state_lock:
            active = self.active

        if not active:
            return user32.CallNextHookEx(
                self.keyboard_hook, n_code, w_param, l_param
            )

        key_id = self.key_id(vk)

        if key_id:
            if is_down:
                if self.send({
                    "type": "key_down",
                    "key": key_id,
                }):
                    with self.state_lock:
                        if self.active:
                            self.remote_keys.add(key_id)
            else:
                self.send({
                    "type": "key_up",
                    "key": key_id,
                })
                with self.state_lock:
                    self.remote_keys.discard(key_id)

        # If a disconnect happened during forwarding, do not swallow this
        # physical event; subsequent events are also passed to Windows.
        if not self.active:
            return user32.CallNextHookEx(
                self.keyboard_hook, n_code, w_param, l_param
            )
        return 1

    def _read_receiver_lines(self, file):
        try:
            for line in file:
                if not line:
                    break
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue

                kind = message.get("type")
                if kind == "edge_exit":
                    self.set_active(False)
                elif kind == "pong":
                    self.last_pong = time.monotonic()
        except (OSError, ValueError) as exc:
            if not self.shutdown_event.is_set():
                self.connection_lost(f"receiver read failed: {exc}")
        finally:
            try:
                file.close()
            except (OSError, ValueError):
                pass

        if not self.shutdown_event.is_set():
            self.connection_lost("receiver closed the connection")

    def _heartbeat_loop(self):
        while not self.shutdown_event.wait(HEARTBEAT_INTERVAL):
            if self.connection_dead:
                return
            if time.monotonic() - self.last_pong > HEARTBEAT_TIMEOUT:
                self.connection_lost("heartbeat timed out")
                return
            if not self.send({"type": "ping"}):
                return

    @staticmethod
    def _sigint_handler(signum, frame):
        # Do not raise KeyboardInterrupt from inside a ctypes hook callback.
        # Posting WM_QUIT lets the message loop exit and run normal cleanup.
        user32.PostQuitMessage(0)

    def run(self):
        print(f"Connecting to {self.host}:{self.port} ...")

        self.sock = socket.create_connection(
            (self.host, self.port), timeout=8
        )
        self.sock.settimeout(None)

        self.sock.sendall(
            (
                json.dumps({
                    "type": "hello",
                    "token": self.token,
                }) + "\n"
            ).encode("utf-8")
        )

        file = self.sock.makefile(
            "r", encoding="utf-8", newline="\n"
        )
        self.sock_file = file

        response = file.readline()

        if not response or json.loads(response).get("type") != "ok":
            self.sock.close()
            self.sock = None
            raise RuntimeError("Receiver rejected the token.")

        self.last_pong = time.monotonic()
        threading.Thread(
            target=self._writer_loop,
            daemon=True,
            name="FlowSwitchSocketWriter",
        ).start()
        threading.Thread(
            target=self._read_receiver_lines,
            args=(file,),
            daemon=True,
            name="FlowSwitchReceiverReader",
        ).start()
        threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name="FlowSwitchHeartbeat",
        ).start()

        module = kernel32.GetModuleHandleW(None)

        self.mouse_hook = user32.SetWindowsHookExW(
            WH_MOUSE_LL,
            self.mouse_callback,
            module,
            0,
        )

        if not self.mouse_hook:
            error = ctypes.get_last_error()
            raise OSError(
                error,
                "Failed to install mouse hook: "
                + ctypes.FormatError(error).strip(),
            )

        self.keyboard_hook = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL,
            self.keyboard_callback,
            module,
            0,
        )

        if not self.keyboard_hook:
            error = ctypes.get_last_error()

            user32.UnhookWindowsHookEx(self.mouse_hook)
            self.mouse_hook = None

            raise OSError(
                error,
                "Failed to install keyboard hook: "
                + ctypes.FormatError(error).strip(),
            )

        print("Connected.")
        print("Move the cursor to the RIGHT edge to enter the Mac.")
        print(f"Fallback toggle: {HOTKEY}. Move to the Mac's left edge to return.")

        msg = wintypes.MSG()
        signal.signal(signal.SIGINT, self._sigint_handler)

        try:
            while True:
                result = user32.GetMessageW(
                    ctypes.byref(msg), None, 0, 0
                )

                if result == -1:
                    error = ctypes.get_last_error()
                    raise OSError(
                        error,
                        "GetMessageW failed: "
                        + ctypes.FormatError(error).strip(),
                    )
                if result == 0:
                    break

                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

        finally:
            self.shutdown_event.set()
            # Restore local input before removing hooks or closing the socket.
            self.force_local_control(send_releases=not self.connection_dead)

            if self.mouse_hook:
                user32.UnhookWindowsHookEx(self.mouse_hook)
                self.mouse_hook = None
            if self.keyboard_hook:
                user32.UnhookWindowsHookEx(self.keyboard_hook)
                self.keyboard_hook = None

            self.show_cursor()

            with self.sock_lock:
                sock = self.sock
                self.sock = None
                self.sock_file = None
            if sock is not None:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    sock.close()
                except OSError:
                    pass


def main():
    parser = argparse.ArgumentParser(
        description="FlowSwitch Windows controller with low-level input hooks"
    )
    parser.add_argument(
        "--host",
        required=True,
        help="Receiver Mac's local IP address",
    )
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument(
        "--token",
        required=True,
        help="Same shared secret used by the Mac receiver",
    )

    args = parser.parse_args()

    try:
        FlowSwitchController(
            args.host, args.port, args.token
        ).run()
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(f"FlowSwitch: {exc}")


if __name__ == "__main__":
    main()
