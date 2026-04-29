"""Minimal Tk GUI for saved VPN profiles (#22).

This intentionally stays small: it is a convenience wrapper around the existing
CLI/profile system, not a full Cisco Secure Client clone.
"""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from openconnect_saml import config


class ProfileGui:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("openconnect-saml")
        self.proc: subprocess.Popen[str] | None = None
        self.log_queue: queue.Queue[str] = queue.Queue()

        self.cfg = config.load()
        self.profiles = dict(self.cfg.list_profiles())
        names = sorted(self.profiles)

        self.profile_var = tk.StringVar(value=names[0] if names else "")
        self.status_var = tk.StringVar(value="Disconnected")

        frame = ttk.Frame(root, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(3, weight=1)

        ttk.Label(frame, text="Profile").grid(row=0, column=0, sticky="w")
        self.profile_box = ttk.Combobox(
            frame, textvariable=self.profile_var, values=names, state="readonly"
        )
        self.profile_box.grid(row=0, column=1, columnspan=3, sticky="ew", padx=(8, 0))

        ttk.Label(frame, text="Status").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Label(frame, textvariable=self.status_var).grid(
            row=1, column=1, sticky="w", pady=(8, 0)
        )

        self.connect_btn = ttk.Button(frame, text="Connect", command=self.connect)
        self.connect_btn.grid(row=2, column=0, pady=8, sticky="ew")
        self.disconnect_btn = ttk.Button(
            frame, text="Disconnect", command=self.disconnect, state="disabled"
        )
        self.disconnect_btn.grid(row=2, column=1, pady=8, padx=8, sticky="ew")
        ttk.Button(frame, text="Refresh", command=self.refresh_profiles).grid(
            row=2, column=2, pady=8, sticky="ew"
        )

        self.log = tk.Text(frame, height=16, width=72)
        self.log.grid(row=3, column=0, columnspan=4, sticky="nsew")
        self.log.insert("end", "Select a saved profile and press Connect.\n")
        if not names:
            self.log.insert(
                "end",
                "No saved profiles found. Add one with: openconnect-saml profiles add NAME --server HOST\n",
            )
            self.connect_btn.configure(state="disabled")

        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(250, self.drain_log_queue)

    def refresh_profiles(self):
        self.cfg = config.load()
        self.profiles = dict(self.cfg.list_profiles())
        names = sorted(self.profiles)
        self.profile_box.configure(values=names)
        if names and self.profile_var.get() not in names:
            self.profile_var.set(names[0])
        self.connect_btn.configure(state="normal" if names and not self.proc else "disabled")

    def connect(self):
        name = self.profile_var.get()
        if not name:
            messagebox.showwarning("openconnect-saml", "No saved profile selected.")
            return
        cmd = [sys.executable, "-m", "openconnect_saml.cli", "connect", name, "--browser", "chrome"]
        self.log.insert("end", f"$ {' '.join(cmd)}\n")
        self.proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self.status_var.set("Connecting…")
        self.connect_btn.configure(state="disabled")
        self.disconnect_btn.configure(state="normal")
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        assert self.proc is not None
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self.log_queue.put(line)
        rc = self.proc.wait()
        self.log_queue.put(f"\nProcess exited with code {rc}.\n")
        self.log_queue.put("__PROCESS_EXITED__")

    def drain_log_queue(self):
        try:
            while True:
                line = self.log_queue.get_nowait()
                if line == "__PROCESS_EXITED__":
                    self.proc = None
                    self.status_var.set("Disconnected")
                    self.connect_btn.configure(
                        state="normal" if self.profile_var.get() else "disabled"
                    )
                    self.disconnect_btn.configure(state="disabled")
                else:
                    self.log.insert("end", line)
                    self.log.see("end")
        except queue.Empty:
            pass
        self.root.after(250, self.drain_log_queue)

    def disconnect(self):
        if self.proc and self.proc.poll() is None:
            self.status_var.set("Disconnecting…")
            self.proc.terminate()

    def on_close(self):
        if self.proc and self.proc.poll() is None:
            if not messagebox.askyesno(
                "openconnect-saml", "Disconnect the active VPN process and quit?"
            ):
                return
            self.proc.terminate()
        self.root.destroy()


def main():
    root = tk.Tk()
    ProfileGui(root)
    root.mainloop()
    return 0
