# FlowSwitch 0.3 — input-hook experiment

This version replaces the `pynput` mouse listener on Windows with low-level Windows input hooks. It filters synthetic cursor-reposition events, suppresses local mouse movement/clicks while controlling the Mac, and sends relative motion based on the Windows cursor's position around the screen center. Keyboard events are also suppressed on Windows during remote mode.

## Setup

Keep using your existing `pynput` install on the Mac; the receiver still uses it. On Windows, `pynput` is no longer needed for the controller, but leaving it installed is harmless.

### Mac receiver

Stop the old receiver with Ctrl+C, update `receiver.py` from this release if included, and restart:

```bash
uv run receiver.py --token "YOUR_EXISTING_SECRET"
```

### Windows controller

Stop the old controller. Replace `controller.py` with this release's file and run:

```powershell
python controller.py --host YOUR_MAC_IP --token "YOUR_EXISTING_SECRET"
```

## Test

1. Move to the far-right edge of Windows to enter Mac mode.
2. Move the mouse physically; it should control the Mac without the Windows cursor flickering to the center.
3. Click and type in a harmless Mac app; input should go to the Mac rather than also clicking/typing in Windows.
4. Move inward on the Mac and then reach the Mac's left edge to return.
5. `Ctrl + Alt + F12` is the fallback toggle.

## Limitations / safety

- This is still experimental. It assumes one primary Windows display and the Mac positioned to the right.
- This prototype uses Windows low-level hooks and Windows cursor recentering; it is not a true raw-input virtual desktop and can still feel different from a native multi-monitor setup.
- Key mapping currently handles letters, digits, common punctuation and common special keys. International layouts, some OEM keys, IME input and some key combinations need additional work.
- If control gets stuck, press Ctrl+Alt+F12 or stop the controller with Ctrl+C.
- The prototype is not encrypted. Use only on a trusted private LAN, use a unique token, and do not expose port 24800 to the internet.
