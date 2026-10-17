import argparse
import hmac
import json
import socket
import threading
import time
from pynput import keyboard, mouse

PORT = 24800
MAX_LINE = 8192
EDGE_TOLERANCE = 2

mouse_controller = mouse.Controller()
keyboard_controller = keyboard.Controller()
pressed_keys = {}
pressed_buttons = {}
state_lock = threading.RLock()
send_lock = threading.Lock()
active_connection = None
remote_mode = False
edge_armed = False
screen_width = 0
screen_height = 0


def send_to_controller(payload):
    global active_connection
    conn = active_connection
    if conn is None:
        return
    try:
        data = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        with send_lock:
            conn.sendall(data)
    except OSError:
        pass


def resolve_key(value):
    if not isinstance(value, str):
        return None
    if value.startswith("Key."):
        return getattr(keyboard.Key, value[4:], None)
    if value.startswith("char:"):
        char = value[5:]
        return char if len(char) == 1 else None
    return None


def handle_event(event):
    global remote_mode, edge_armed
    kind = event.get("type")

    if kind == "enter":
        with state_lock:
            remote_mode = True
            edge_armed = False
        # Start a few pixels inside the left edge; user must move inward before
        # reaching the edge again to request a return to Windows.
        mouse_controller.position = (min(4, max(0, screen_width - 1)), screen_height // 2)

    elif kind == "move":
        mouse_controller.move(int(event.get("dx", 0)), int(event.get("dy", 0)))

    elif kind == "click":
        button_name = event.get("button", "left")
        button = getattr(mouse.Button, button_name, None)
        if button is not None:
            if event.get("action") == "down":
                mouse_controller.press(button)
                pressed_buttons[button_name] = button
            elif event.get("action") == "up":
                mouse_controller.release(button)
                pressed_buttons.pop(button_name, None)

    elif kind == "scroll":
        mouse_controller.scroll(int(event.get("dx", 0)), int(event.get("dy", 0)))

    elif kind in ("key_down", "key_up"):
        key_obj = resolve_key(event.get("key"))
        if key_obj is None:
            return
        key_id = str(event.get("key"))
        if kind == "key_down":
            keyboard_controller.press(key_obj)
            pressed_keys[key_id] = key_obj
        else:
            keyboard_controller.release(key_obj)
            pressed_keys.pop(key_id, None)


def release_all():
    for key_obj in list(pressed_keys.values()):
        try:
            keyboard_controller.release(key_obj)
        except Exception:
            pass
    pressed_keys.clear()
    for button in list(pressed_buttons.values()):
        try:
            mouse_controller.release(button)
        except Exception:
            pass
    pressed_buttons.clear()


def on_mac_mouse_move(x, y):
    global edge_armed, remote_mode
    with state_lock:
        if not remote_mode:
            return
        if x > 20:
            edge_armed = True
        elif edge_armed and x <= EDGE_TOLERANCE:
            edge_armed = False
            remote_mode = False
            send_to_controller({"type": "edge_exit"})
            # Keep the Mac cursor just inside its own screen after returning.
            mouse_controller.position = (min(4, max(0, screen_width - 1)), y)


def client_session(conn, expected_token):
    global active_connection, remote_mode, edge_armed
    with conn:
        file = conn.makefile("r", encoding="utf-8", newline="\n")
        try:
            first_line = file.readline(MAX_LINE + 1)
            if not first_line or len(first_line) > MAX_LINE:
                return
            try:
                hello = json.loads(first_line)
            except json.JSONDecodeError:
                return

            supplied = str(hello.get("token", ""))
            if hello.get("type") != "hello" or not hmac.compare_digest(supplied, expected_token):
                print("Rejected client: invalid token.")
                return

            active_connection = conn
            conn.sendall(b'{"type":"ok"}\n')
            print(f"Controller connected from {conn.getpeername()}")

            for line in file:
                if len(line) > MAX_LINE:
                    break
                try:
                    event = json.loads(line)
                    if isinstance(event, dict):
                        handle_event(event)
                except (json.JSONDecodeError, ValueError, TypeError, OSError) as exc:
                    print(f"Ignored invalid input event: {exc}")
        except (ConnectionError, OSError) as exc:
            print(f"Connection ended: {exc}")
        finally:
            with state_lock:
                remote_mode = False
                edge_armed = False
            active_connection = None
            release_all()
            print("Controller disconnected; released held keys/buttons.")


def main():
    global screen_width, screen_height
    parser = argparse.ArgumentParser(description="FlowSwitch input receiver")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: all network interfaces)")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--token", required=True, help="Shared secret; use a long random value")
    args = parser.parse_args()
    if len(args.token) < 16:
        parser.error("Use a token at least 16 characters long.")

    # Tk reads the Mac's actual screen dimensions without an additional dependency.
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        root.destroy()
    except Exception as exc:
        raise SystemExit(f"Could not determine Mac screen size via Tk: {exc}")

    listener = mouse.Listener(on_move=on_mac_mouse_move)
    listener.start()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((args.host, args.port))
    server.listen(4)
    print(f"FlowSwitch receiver listening on {args.host}:{args.port}")
    print(f"Detected Mac display: {screen_width}x{screen_height}")
    print("Only use this prototype on a trusted private network.")

    try:
        while True:
            conn, address = server.accept()
            threading.Thread(target=client_session, args=(conn, args.token), daemon=True).start()
    except KeyboardInterrupt:
        print("\nStopping FlowSwitch receiver.")
    finally:
        server.close()
        listener.stop()
        release_all()


if __name__ == "__main__":
    main()
