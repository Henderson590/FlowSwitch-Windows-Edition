"""FlowSwitch Windows GUI launcher. Run on Windows with Python 3.11+ and tkinter."""
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from controller import FlowSwitchController, PORT


class WindowsApp:
    def __init__(self, root):
        self.root = root
        self.root.title("FlowSwitch — Windows Controller")
        self.root.geometry("480x470")
        self.root.minsize(440, 440)
        self.messages = queue.Queue()
        self.controller = None
        self.worker = None

        frame = ttk.Frame(root, padding=22)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="FlowSwitch", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(frame, text="Connect this PC to your Mac receiver.").pack(anchor="w", pady=(2, 18))

        ttk.Label(frame, text="Mac IP address").pack(anchor="w")
        self.host = ttk.Entry(frame)
        self.host.insert(0, "192.168.1.")
        self.host.pack(fill="x", pady=(4, 12))

        ttk.Label(frame, text="Shared token").pack(anchor="w")
        self.token = ttk.Entry(frame, show="•")
        self.token.pack(fill="x", pady=(4, 16))

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")
        self.connect_button = ttk.Button(buttons, text="Connect to Receiver", command=self.connect)
        self.connect_button.pack(side="left", fill="x", expand=True)
        self.stop_button = ttk.Button(buttons, text="Disconnect", command=self.disconnect, state="disabled")
        self.stop_button.pack(side="left", padx=(8, 0))

        file_frame = ttk.LabelFrame(frame, text="File transfer", padding=10)
        file_frame.pack(fill="x", pady=(16, 0))
        ttk.Label(file_frame, text="Incoming files are saved to your Downloads folder by default.", wraplength=400).pack(anchor="w")
        file_buttons = ttk.Frame(file_frame)
        file_buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(file_buttons, text="Send File(s)…", command=self.send_files).pack(side="left", fill="x", expand=True)
        ttk.Button(file_buttons, text="Choose Save Folder…", command=self.choose_download_dir).pack(side="left", padx=(8, 0))

        self.status = tk.StringVar(value="Not connected")
        ttk.Label(frame, textvariable=self.status, wraplength=420).pack(anchor="w", pady=(12, 0))
        ttk.Label(frame, text="Emergency toggle: Ctrl + Alt + F12", foreground="#666666").pack(anchor="w", pady=(6, 0))
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(150, self.poll_messages)

    def connect(self):
        host = self.host.get().strip()
        token = self.token.get()
        if not host:
            messagebox.showerror("Missing IP address", "Enter the Mac's IP address.", parent=self.root)
            return
        if len(token) < 16:
            messagebox.showerror("Token too short", "Use the same token as the Mac receiver (at least 16 characters).", parent=self.root)
            return
        if self.worker and self.worker.is_alive():
            return
        self.connect_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status.set("Connecting…")
        self.controller = FlowSwitchController(host, PORT, token, status_callback=self.messages.put)
        if getattr(self, "download_dir", None):
            self.controller.file_transfer.set_download_dir(self.download_dir)
        self.worker = threading.Thread(target=self.run_controller, daemon=True)
        self.worker.start()

    def run_controller(self):
        failed = False
        try:
            self.controller.run()
        except Exception as exc:
            failed = True
            self.messages.put(f"Connection stopped: {exc}. Windows input is local.")
        finally:
            if not failed:
                self.messages.put("Disconnected. Windows input is local.")

    def choose_download_dir(self):
        folder = filedialog.askdirectory(title="Choose where incoming files are saved", parent=self.root)
        if folder:
            # Remember the folder for current and future connections.
            self.download_dir = folder
            if self.controller:
                self.controller.file_transfer.set_download_dir(folder)
            self.status.set(f"Incoming files will be saved to: {folder}")

    def send_files(self):
        paths = filedialog.askopenfilenames(title="Choose files to send", parent=self.root)
        if not paths:
            return
        if not self.controller or not self.worker or not self.worker.is_alive():
            messagebox.showwarning("Not connected", "Connect to your Mac before sending files.", parent=self.root)
            return
        self.controller.file_transfer.send_files(paths)

    def disconnect(self):
        if self.controller:
            self.status.set("Disconnecting safely…")
            self.controller.request_stop()

    def poll_messages(self):
        try:
            while True:
                self.status.set(self.messages.get_nowait())
        except queue.Empty:
            pass
        if not (self.worker and self.worker.is_alive()):
            self.connect_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
        self.root.after(150, self.poll_messages)

    def close(self):
        if self.controller and self.worker and self.worker.is_alive():
            self.controller.request_stop()
            self.root.after(300, self.finish_close)
        else:
            self.root.destroy()

    def finish_close(self):
        if self.worker and self.worker.is_alive():
            self.root.after(200, self.finish_close)
        else:
            self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    WindowsApp(root)
    root.mainloop()
