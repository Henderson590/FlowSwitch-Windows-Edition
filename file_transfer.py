"""Bidirectional, chunked file transfer over the authenticated FlowSwitch connection."""
import base64
import os
import queue
import threading
import uuid
from pathlib import Path

CHUNK_BYTES = 192 * 1024
MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB per file
ACK_TIMEOUT = 20.0


class FileTransferManager:
    def __init__(self, send_callback, download_dir=None, status_callback=None):
        self.send_callback = send_callback
        self.download_dir = Path(download_dir or (Path.home() / "Downloads")).expanduser()
        self.status_callback = status_callback
        self._lock = threading.RLock()
        self._pending = {}
        self._ack_cache = {}
        self._incoming = {}

    def set_download_dir(self, path):
        with self._lock:
            self.download_dir = Path(path).expanduser()

    def _status(self, text):
        if self.status_callback:
            try:
                self.status_callback(text)
            except Exception:
                pass

    def _send(self, payload):
        try:
            return bool(self.send_callback(payload))
        except Exception:
            return False

    def _wait_ack(self, transfer_id, stage, sequence=None, timeout=ACK_TIMEOUT):
        key = (transfer_id, stage, sequence)
        event = threading.Event()
        record = {"event": event, "ok": False, "error": "No acknowledgement received."}
        with self._lock:
            cached = self._ack_cache.pop(key, None)
            if cached is not None:
                record.update(cached)
                record["event"].set()
            else:
                self._pending[key] = record
        if not event.wait(timeout):
            with self._lock:
                self._pending.pop(key, None)
            raise TimeoutError("The other computer did not respond to the file transfer.")
        if not record["ok"]:
            raise RuntimeError(record.get("error") or "The other computer rejected the transfer.")

    def handle_message(self, message):
        """Process a file-transfer protocol message. Safe to call from the socket reader."""
        kind = message.get("type")
        transfer_id = message.get("transfer_id")
        if not isinstance(transfer_id, str) or len(transfer_id) > 80:
            return False

        if kind == "file_ack":
            key = (transfer_id, message.get("stage"), message.get("sequence"))
            with self._lock:
                record = self._pending.get(key)
                result = {"ok": bool(message.get("ok")),
                          "error": str(message.get("error", "Transfer rejected."))}
                if record:
                    record.update(result)
                    record["event"].set()
                else:
                    # An extremely fast local transfer can be acknowledged before
                    # the sender thread begins waiting for it.
                    self._ack_cache[key] = result
                    if len(self._ack_cache) > 256:
                        self._ack_cache.pop(next(iter(self._ack_cache)))
            return True

        if kind == "file_start":
            name = message.get("name")
            size = message.get("size")
            if not isinstance(name, str) or not name or len(name) > 255 or not isinstance(size, int) or size < 0 or size > MAX_FILE_BYTES:
                self._ack(transfer_id, "ready", ok=False, error="Invalid filename or file size.")
                return True
            safe_name = Path(name.replace("\\", "/")).name
            if safe_name in ("", ".", ".."):
                self._ack(transfer_id, "ready", ok=False, error="Invalid filename.")
                return True
            try:
                self.download_dir.mkdir(parents=True, exist_ok=True)
                destination = self._unique_path(self.download_dir / safe_name)
                temporary = destination.with_name(destination.name + ".flowswitch-part")
                # Do not clobber a stale partial file from an earlier interrupted transfer.
                suffix = 1
                while temporary.exists():
                    temporary = destination.with_name(f"{destination.name}.{suffix}.flowswitch-part")
                    suffix += 1
                handle = open(temporary, "xb")
                with self._lock:
                    self._incoming[transfer_id] = {
                        "name": safe_name, "size": size, "written": 0,
                        "destination": destination, "temporary": temporary,
                        "handle": handle, "next_sequence": 0,
                    }
                self._ack(transfer_id, "ready", ok=True)
                self._status(f"Receiving {safe_name}…")
            except OSError as exc:
                self._ack(transfer_id, "ready", ok=False, error=f"Cannot save file: {exc}")
            return True

        if kind == "file_chunk":
            sequence = message.get("sequence")
            try:
                encoded = message.get("data")
                if not isinstance(encoded, str):
                    raise ValueError("Missing chunk data.")
                data = base64.b64decode(encoded, validate=True)
                if not data or len(data) > CHUNK_BYTES:
                    raise ValueError("Invalid chunk size.")
                with self._lock:
                    incoming = self._incoming.get(transfer_id)
                    if incoming is None:
                        raise ValueError("No active transfer for this chunk.")
                    if sequence != incoming["next_sequence"]:
                        raise ValueError("File chunk arrived out of order.")
                    if incoming["written"] + len(data) > incoming["size"]:
                        raise ValueError("Received more data than the declared file size.")
                    incoming["handle"].write(data)
                    incoming["written"] += len(data)
                    incoming["next_sequence"] += 1
                    written, total, name = incoming["written"], incoming["size"], incoming["name"]
                self._ack(transfer_id, "chunk", sequence=sequence, ok=True)
                percent = 100 if total == 0 else int(written * 100 / total)
                self._status(f"Receiving {name}: {percent}%")
            except Exception as exc:
                self._ack(transfer_id, "chunk", sequence=sequence, ok=False, error=str(exc))
            return True

        if kind == "file_end":
            try:
                with self._lock:
                    incoming = self._incoming.pop(transfer_id, None)
                if incoming is None:
                    raise ValueError("No active transfer to finish.")
                incoming["handle"].flush()
                os.fsync(incoming["handle"].fileno())
                incoming["handle"].close()
                if incoming["written"] != incoming["size"]:
                    try:
                        incoming["temporary"].unlink(missing_ok=True)
                    finally:
                        raise ValueError("The received file size did not match the expected size.")
                os.replace(incoming["temporary"], incoming["destination"])
                self._ack(transfer_id, "complete", ok=True)
                self._status(f"Received {incoming['name']} → {incoming['destination']}")
            except Exception as exc:
                self._ack(transfer_id, "complete", ok=False, error=str(exc))
            return True

        if kind == "file_cancel":
            self._discard_incoming(transfer_id)
            self._status("Incoming file transfer cancelled.")
            return True
        return False

    def _ack(self, transfer_id, stage, sequence=None, ok=True, error=""):
        self._send({"type": "file_ack", "transfer_id": transfer_id, "stage": stage,
                    "sequence": sequence, "ok": bool(ok), "error": str(error)[:500]})

    @staticmethod
    def _unique_path(path):
        if not path.exists():
            return path
        for number in range(1, 10000):
            candidate = path.with_name(f"{path.stem} ({number}){path.suffix}")
            if not candidate.exists():
                return candidate
        raise OSError("Too many files with the same name in the destination folder.")

    def _discard_incoming(self, transfer_id):
        with self._lock:
            incoming = self._incoming.pop(transfer_id, None)
        if incoming:
            try:
                incoming["handle"].close()
            except OSError:
                pass
            try:
                incoming["temporary"].unlink(missing_ok=True)
            except OSError:
                pass

    def send_files(self, paths):
        paths = [str(p) for p in paths]
        threading.Thread(target=self._send_files_worker, args=(paths,), daemon=True,
                         name="FlowSwitchFileSender").start()

    def _send_files_worker(self, paths):
        for path_string in paths:
            path = Path(path_string)
            transfer_id = uuid.uuid4().hex
            try:
                if not path.is_file():
                    raise ValueError(f"Not a regular file: {path.name}")
                size = path.stat().st_size
                if size > MAX_FILE_BYTES:
                    raise ValueError(f"{path.name} exceeds the 2 GiB per-file limit.")
                if not self._send({"type": "file_start", "transfer_id": transfer_id,
                                   "name": path.name, "size": size}):
                    raise ConnectionError("FlowSwitch is not connected.")
                self._wait_ack(transfer_id, "ready")
                sent = 0
                sequence = 0
                with path.open("rb") as source:
                    while True:
                        chunk = source.read(CHUNK_BYTES)
                        if not chunk:
                            break
                        payload = {"type": "file_chunk", "transfer_id": transfer_id,
                                   "sequence": sequence,
                                   "data": base64.b64encode(chunk).decode("ascii")}
                        if not self._send(payload):
                            raise ConnectionError("Connection was lost while sending the file.")
                        self._wait_ack(transfer_id, "chunk", sequence)
                        sent += len(chunk)
                        sequence += 1
                        percent = 100 if size == 0 else int(sent * 100 / size)
                        self._status(f"Sending {path.name}: {percent}%")
                if not self._send({"type": "file_end", "transfer_id": transfer_id}):
                    raise ConnectionError("Connection was lost before the file could finish.")
                self._wait_ack(transfer_id, "complete")
                self._status(f"Sent {path.name} successfully.")
            except Exception as exc:
                self._status(f"File transfer failed ({path.name}): {exc}")
                self._send({"type": "file_cancel", "transfer_id": transfer_id})
