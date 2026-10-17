# FlowSwitch Desktop v0.5 — GUI starter

This is the first desktop-GUI development checkpoint based on the working v0.4 failsafe scripts. It adds a small Windows controller window and Mac receiver window. The existing input protocol remains the same; the Mac receiver now has a programmatic start/stop function for its GUI.

**Important:** These are source projects, not prebuilt `.exe`/`.app` installers. Build each app on its target operating system. The current environment can check Python syntax, but cannot verify Windows low-level input hooks or macOS accessibility/input behavior. Keep the known-good v0.4 files as a fallback and test with the Mac's built-in keyboard available.

## Windows controller

1. Install Python 3.11+ from python.org. During setup, enable adding Python to PATH.
2. Open PowerShell in this folder.
3. Run `python windows_app.py`.
4. Enter the Mac's IP address and the same shared token configured on the Mac, then select **Connect to Receiver**.
5. Use `Ctrl+Alt+F12` to toggle control. Use **Disconnect** or close the app to return control to Windows safely.

Build a standalone Windows executable (run these commands on Windows):

```powershell
py -m pip install --upgrade pyinstaller
py -m PyInstaller --noconfirm --clean --windowed --name FlowSwitch windows_app.py
```

The executable will be under `dist/FlowSwitch/` (or `dist/FlowSwitch.exe`, depending on PyInstaller version/options).

## Mac receiver

1. Use a Python installation that includes Tkinter. Python.org's macOS installer is a suitable option.
2. Open Terminal in this folder and install the dependency:

```bash
python3 -m pip install -r requirements-mac.txt
```

3. Run `python3 mac_app.py`.
4. Copy the displayed local IP address into the Windows app. Enter the same token on both sides and press **Start Receiver**.
5. On first use, macOS may require granting Accessibility/Input Monitoring permissions to the app or Python runtime. Approve only the permissions required for input control.

Build a standalone Mac application (run these commands on macOS):

```bash
python3 -m pip install --upgrade pyinstaller
python3 -m PyInstaller --noconfirm --clean --windowed --name FlowSwitch mac_app.py
```

The app bundle will be under `dist/FlowSwitch.app`.

## Token and network safety

- Use a long, unique shared token (at least 16 characters; 32 random characters is better).
- Use only on a trusted private LAN. The current TCP protocol is not encrypted; do not port-forward TCP 24800 to the internet.
- Both apps use TCP port 24800 by default. Allow it through the Mac firewall only on your trusted local network if prompted.

## Current scope and next steps

Included: launchable GUI source for each side, displayed Mac LAN IP, shared-token entry, start/connect and stop/disconnect controls, and a status line.

Not included yet: custom screen-edge configuration, drag-and-drop transfer, auto-reconnect, signed/notarized release packages, or polished installer/update flow. These should be added incrementally while preserving automatic local-input recovery on Windows.


## Temporary heartbeat diagnostics (v0.5.1)

This diagnostic build adds console messages to trace whether the Mac receives each ping, sends each pong, and whether Windows receives it. Launch both GUIs from Terminal/PowerShell so their console output is visible. This is for troubleshooting only; it is not a prebuilt app and is not runtime-tested on both operating systems. Do not change the timeout or disable the failsafe.


## v0.5.2 connection-lifecycle fix

The Windows GUI runs the controller in a worker thread. Python prohibits calling `signal.signal()` from a worker thread, so the previous diagnostics build could raise `ValueError` immediately after opening the socket and starting heartbeat traffic. The controller now installs the Ctrl+C handler only when running on the main thread; the GUI uses its existing safe `request_stop()` path. The Windows GUI also preserves exception text in its status line instead of immediately overwriting it with a generic stopped message.

This patch is syntax-checked only. Test on Windows and macOS with the Mac's built-in keyboard available; keep the known-good v0.4 backup.

## v0.6.0 — plain-text clipboard sync (first implementation)

The original v0.6.0 release added bidirectional plain-text clipboard synchronization. Copy text, code, links, or an image on either computer; after the next clipboard poll (normally within about half a second), the other computer's clipboard is updated. Text is limited to 32,000 characters and images to 8 MiB of PNG data before network encoding. Rich formatting is not preserved.

**Update both computers together:** the v0.6.x protocol uses `clipboard_text` and `clipboard_image` messages, so use the matching source files on both machines. Do not mix this with the older receiver if you expect clipboard sync to work.

Clipboard behavior:
- The apps establish a baseline when a connection starts, so neither clipboard is automatically overwritten just because you connected.
- Only clipboard changes after connection are synchronized.
- Remote clipboard updates are marked as already seen to prevent an endless echo loop.
- Windows uses the native Unicode text clipboard API and Pillow for image conversion through the Windows DIB clipboard format. macOS uses `pbpaste`/`pbcopy` for text and native NSPasteboard TIFF data for images (through PyObjC).
- Clipboard polling runs in a separate daemon thread and is designed not to interfere with input forwarding or the Windows failsafe.
- The protocol is still unencrypted. Keep it on a trusted private network and do not forward port 24800 to the internet.

### Test checklist

1. Keep the known-good v0.5.2 folder/ZIP as your rollback checkpoint.
2. Extract this version into a new folder on both computers; do not overwrite the working backup.
3. Start the new Mac receiver and new Windows controller with the same IP/token as before.
4. Copy a short plain-text sentence on Windows, wait about one second, and paste on the Mac.
5. Copy a URL and a multi-line code snippet on the Mac, then paste on Windows.
6. Verify switching input in both directions and the emergency toggle still work.
7. Copy an image on Windows and paste it into an image editor or message on the Mac.
8. Copy an image on the Mac and paste it into an image editor or message on Windows.
9. Test a large image, then test text sharing again in both directions.
10. Disconnect the Mac receiver while Windows is controlling it and confirm Windows input immediately returns locally.

This source is syntax-checked, but native clipboard image access has **not** been runtime-tested on actual Windows and macOS machines in this environment. Treat it as a test build until you complete the checklist on your hardware. Images are sent as base64-encoded PNG inside the existing newline-delimited JSON protocol, with the receiver's maximum message size increased to 12 MiB to accommodate the 8 MiB image limit. The protocol is still unencrypted, so use only on a trusted private LAN.


## v0.6.1 — image clipboard sync

Adds bidirectional image clipboard synchronization. The monitor checks for images before text so image clipboard formats are not accidentally treated as text. Images are normalized to PNG, limited to 8 MiB, and transferred with a `clipboard_image` message. Both machines must run this version and install their listed dependencies.

### Dependencies for v0.6.1

On Windows, open PowerShell in the extracted folder and run:

```powershell
py -m pip install -r requirements-windows.txt
```

On macOS, run in Terminal from the extracted folder:

```bash
python3 -m pip install -r requirements-mac.txt
```

Restart both apps after installing dependencies. This remains a source build; no prebuilt `.exe` or `.app` is included.
