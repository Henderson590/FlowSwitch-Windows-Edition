# FlowSwitch v0.4 — Failsafe patch

This patch updates the Windows controller and Mac receiver to improve recovery when the TCP connection or receiver disappears.

## Safety changes

- Windows input hooks no longer perform TCP writes directly. Events are queued for a dedicated socket-writer thread so a slow connection is less likely to stall a low-level input callback.
- The Windows controller detects socket write errors, receiver EOF, and missing heartbeat replies. On connection loss it marks remote mode inactive and restores the local cursor so physical Windows input is passed through.
- Heartbeats run every 0.5 seconds; the controller treats a missing pong for 2 seconds as a failed connection. A direct socket failure or EOF is handled sooner.
- The Mac replies to heartbeat pings and continues releasing held keys and mouse buttons in the client-session cleanup path when the connection ends.
- Ctrl+C posts a Windows quit message instead of raising `KeyboardInterrupt` inside a `ctypes` callback.
- Network writes are kept outside the Windows input-state lock to reduce lock-order deadlock risk.

## Compatibility

The protocol uses the existing port `24800`, token handshake, and existing input event names. Both sides should be updated together because the heartbeat ping/pong messages are part of this patch.

## Important limitations

This patch has passed Python syntax compilation in the build environment, but it has **not** been runtime-tested on the user's Windows machine or Hackintosh. It cannot guarantee release of an input if the Mac OS itself or the receiver process is forcibly terminated at exactly the wrong time; it does attempt release on ordinary socket disconnect and orderly receiver cleanup.

## Test plan — run only after backing up the known-good files

1. Start the Mac receiver, then the Windows controller.
2. Confirm edge handoff and return work normally.
3. While controlling the Mac, stop the receiver with Ctrl+C. Windows should regain local control after EOF/heartbeat timeout.
4. Repeat with the network connection interrupted. For a silent network failure, recovery should occur after the 2-second heartbeat timeout (possibly slightly longer under OS scheduling).
5. While controlling the Mac, stop the Windows controller with Ctrl+C. It should exit through normal cleanup without the prior callback `KeyboardInterrupt` message.
6. Confirm the Mac reports the controller disconnect and releases any held keys/buttons.

Do not test by force-killing either process as the first test. Keep the Mac's integrated keyboard available during initial tests.
