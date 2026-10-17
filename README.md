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

Not included yet: custom screen-edge configuration, clipboard sync (text/images), drag-and-drop transfer, auto-reconnect, signed/notarized release packages, or polished installer/update flow. These should be added incrementally while preserving automatic local-input recovery on Windows.


## Temporary heartbeat diagnostics (v0.5.1)

This diagnostic build adds console messages to trace whether the Mac receives each ping, sends each pong, and whether Windows receives it. Launch both GUIs from Terminal/PowerShell so their console output is visible. This is for troubleshooting only; it is not a prebuilt app and is not runtime-tested on both operating systems. Do not change the timeout or disable the failsafe.


## v0.5.2 connection-lifecycle fix

The Windows GUI runs the controller in a worker thread. Python prohibits calling `signal.signal()` from a worker thread, so the previous diagnostics build could raise `ValueError` immediately after opening the socket and starting heartbeat traffic. The controller now installs the Ctrl+C handler only when running on the main thread; the GUI uses its existing safe `request_stop()` path. The Windows GUI also preserves exception text in its status line instead of immediately overwriting it with a generic stopped message.

This patch is syntax-checked only. Test on Windows and macOS with the Mac's built-in keyboard available; keep the known-good v0.4 backup.
