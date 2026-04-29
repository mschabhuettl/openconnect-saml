"""Tk GUI for saved VPN profiles (#22).

Cisco-Secure-Client-style launcher with three tabs:

- **Profiles** — list, add, edit, delete; connect / disconnect.
- **Status** — live connection state, traffic counters / rate.
- **History** — recent connect / disconnect / error events.

Intentionally lightweight (Tk-only, no extra deps). Advanced flags
still go through the CLI.
"""

from __future__ import annotations

import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from openconnect_saml import config, history
from openconnect_saml.tui import (
    _augment_with_rate,
    _collect_status,
    _format_bytes,
    _format_rate,
)

BROWSER_CHOICES = ("chrome", "qt", "headless")
DEFAULT_BROWSER = "chrome"
TOTP_SOURCES = ("local", "2fauth", "bitwarden", "1password", "pass", "none")


# ---------------------------------------------------------------------------
# Profile-edit dialog
# ---------------------------------------------------------------------------


class ProfileDialog(tk.Toplevel):
    """Modal dialog for adding / editing a single profile."""

    def __init__(self, parent: tk.Tk, *, name: str = "", profile=None):
        super().__init__(parent)
        self.title("Edit profile" if name else "Add profile")
        self.transient(parent)
        self.grab_set()
        self.result: dict | None = None

        self.name_var = tk.StringVar(value=name)
        self.server_var = tk.StringVar(value=getattr(profile, "server", "") if profile else "")
        self.user_var = tk.StringVar(
            value=(profile.credentials.username if profile and profile.credentials else "")
        )
        self.group_var = tk.StringVar(value=getattr(profile, "user_group", "") if profile else "")
        self.totp_var = tk.StringVar(
            value=(profile.credentials.totp_source if profile and profile.credentials else "local")
        )

        frm = ttk.Frame(self, padding=12)
        frm.grid(row=0, column=0, sticky="nsew")
        for i, (label, var, opts) in enumerate(
            [
                (
                    "Name (config key)",
                    self.name_var,
                    {"state": "normal" if not name else "disabled"},
                ),
                ("Server", self.server_var, {}),
                ("Username (optional)", self.user_var, {}),
                ("User group (optional)", self.group_var, {}),
            ]
        ):
            ttk.Label(frm, text=label).grid(row=i, column=0, sticky="w", pady=2)
            entry = ttk.Entry(frm, textvariable=var, width=32, **opts)
            entry.grid(row=i, column=1, sticky="ew", padx=(8, 0), pady=2)

        ttk.Label(frm, text="TOTP source").grid(row=4, column=0, sticky="w", pady=2)
        ttk.Combobox(
            frm,
            textvariable=self.totp_var,
            values=TOTP_SOURCES,
            state="readonly",
            width=29,
        ).grid(row=4, column=1, sticky="ew", padx=(8, 0), pady=2)

        btn_row = ttk.Frame(frm)
        btn_row.grid(row=5, column=0, columnspan=2, pady=(12, 0), sticky="e")
        ttk.Button(btn_row, text="Cancel", command=self.destroy).grid(row=0, column=0, padx=4)
        ttk.Button(btn_row, text="Save", command=self._save).grid(row=0, column=1, padx=4)

        frm.columnconfigure(1, weight=1)
        self.wait_window()

    def _save(self):
        name = self.name_var.get().strip()
        server = self.server_var.get().strip()
        if not name:
            messagebox.showwarning("openconnect-saml", "Name is required.")
            return
        if not server:
            messagebox.showwarning("openconnect-saml", "Server is required.")
            return
        self.result = {
            "name": name,
            "server": server,
            "user": self.user_var.get().strip(),
            "user_group": self.group_var.get().strip(),
            "totp_source": self.totp_var.get(),
        }
        self.destroy()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------


class ProfileGui:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("openconnect-saml")
        self.root.geometry("780x520")
        self.proc: subprocess.Popen[str] | None = None
        self.log_queue: queue.Queue[str] = queue.Queue()
        self._prev_status: dict | None = None

        self.cfg = config.load()
        self.profiles_map = dict(self.cfg.list_profiles())
        names = sorted(self.profiles_map)

        self.browser_var = tk.StringVar(value=DEFAULT_BROWSER)
        self.status_var = tk.StringVar(value="Disconnected")

        # ---------------------------------------------------------------- top
        top = ttk.Frame(root, padding=(12, 8))
        top.pack(side="top", fill="x")
        ttk.Label(top, text="Browser:").pack(side="left")
        ttk.Combobox(
            top,
            textvariable=self.browser_var,
            values=BROWSER_CHOICES,
            state="readonly",
            width=10,
        ).pack(side="left", padx=(6, 12))
        ttk.Label(top, text="Status:").pack(side="left")
        ttk.Label(top, textvariable=self.status_var, font=("TkDefaultFont", 10, "bold")).pack(
            side="left", padx=(6, 0)
        )

        # ------------------------------------------------------------ tabs
        notebook = ttk.Notebook(root)
        notebook.pack(side="top", fill="both", expand=True, padx=12, pady=(0, 12))

        self.profiles_tab = ttk.Frame(notebook, padding=8)
        self.status_tab = ttk.Frame(notebook, padding=8)
        self.history_tab = ttk.Frame(notebook, padding=8)
        notebook.add(self.profiles_tab, text="Profiles")
        notebook.add(self.status_tab, text="Status")
        notebook.add(self.history_tab, text="History")

        self._build_profiles_tab(names)
        self._build_status_tab()
        self._build_history_tab()

        # Periodic refreshes
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(250, self.drain_log_queue)
        self.root.after(2000, self._tick_status)
        self.root.after(5000, self._tick_history)

    # ---------------------------------------------------------- profiles tab

    def _build_profiles_tab(self, names: list[str]):
        cols = ("name", "server", "user", "group", "totp")
        tree = ttk.Treeview(
            self.profiles_tab, columns=cols, show="headings", selectmode="browse", height=10
        )
        for c, label, w in (
            ("name", "Name", 110),
            ("server", "Server", 220),
            ("user", "User", 180),
            ("group", "Group", 100),
            ("totp", "TOTP", 90),
        ):
            tree.heading(c, text=label)
            tree.column(c, width=w, anchor="w")
        tree.pack(side="top", fill="both", expand=True)
        self.profiles_tree = tree

        btn_row = ttk.Frame(self.profiles_tab)
        btn_row.pack(side="top", fill="x", pady=(8, 0))
        self.connect_btn = ttk.Button(btn_row, text="Connect", command=self.connect)
        self.connect_btn.pack(side="left")
        self.disconnect_btn = ttk.Button(
            btn_row, text="Disconnect", command=self.disconnect, state="disabled"
        )
        self.disconnect_btn.pack(side="left", padx=(8, 0))
        ttk.Separator(btn_row, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Button(btn_row, text="Add", command=self.add_profile).pack(side="left")
        ttk.Button(btn_row, text="Edit", command=self.edit_profile).pack(side="left", padx=(8, 0))
        ttk.Button(btn_row, text="Delete", command=self.delete_profile).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(btn_row, text="Refresh", command=self.refresh_profiles).pack(side="right")

        # Log pane below the buttons
        log_frame = ttk.LabelFrame(self.profiles_tab, text="Process output")
        log_frame.pack(side="top", fill="both", expand=True, pady=(8, 0))
        self.log = tk.Text(log_frame, height=8, wrap="word")
        self.log.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        scrollbar.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=scrollbar.set)
        self.log.insert("end", "Select a profile and press Connect.\n")

        self._populate_profile_tree(names)

    def _populate_profile_tree(self, names: list[str]):
        tree = self.profiles_tree
        tree.delete(*tree.get_children())
        for n in names:
            p = self.profiles_map.get(n)
            user = p.credentials.username if p and p.credentials else ""
            totp = p.credentials.totp_source if p and p.credentials else ""
            tree.insert(
                "",
                "end",
                iid=n,
                values=(n, getattr(p, "server", ""), user, p.user_group or "", totp),
            )
        if names:
            tree.selection_set(names[0])

    def _selected_profile_name(self) -> str | None:
        sel = self.profiles_tree.selection()
        return sel[0] if sel else None

    # ----------------------------------------------------------- status tab

    def _build_status_tab(self):
        labels = [
            ("State", "state"),
            ("Profile", "profile"),
            ("Server", "server"),
            ("User", "user"),
            ("Interface / IP", "iface_ip"),
            ("Uptime", "uptime"),
            ("TX / RX", "tx_rx"),
            ("Rate ↑/↓", "rate"),
            ("Reconnects", "reconnects"),
        ]
        self.status_labels: dict[str, tk.StringVar] = {}
        for i, (label, key) in enumerate(labels):
            ttk.Label(self.status_tab, text=label + ":", font=("TkDefaultFont", 10, "bold")).grid(
                row=i, column=0, sticky="w", pady=3
            )
            var = tk.StringVar(value="—")
            ttk.Label(self.status_tab, textvariable=var).grid(
                row=i, column=1, sticky="w", padx=(12, 0), pady=3
            )
            self.status_labels[key] = var

    def _tick_status(self):
        try:
            status = _collect_status()
            if status is not None:
                status["_sampled_at"] = time.monotonic()
                _augment_with_rate(status, self._prev_status)
            self._update_status_pane(status)
            self._prev_status = status
        finally:
            self.root.after(2000, self._tick_status)

    def _update_status_pane(self, status):
        if not status:
            self.status_labels["state"].set("Disconnected")
            for k in (
                "profile",
                "server",
                "user",
                "iface_ip",
                "uptime",
                "tx_rx",
                "rate",
                "reconnects",
            ):
                self.status_labels[k].set("—")
            self.status_var.set("Disconnected")
            return
        self.status_labels["state"].set("Connected")
        self.status_labels["profile"].set(str(status.get("profile", "—")))
        self.status_labels["server"].set(str(status.get("server", "—")))
        self.status_labels["user"].set(str(status.get("user", "—")))
        self.status_labels["iface_ip"].set(
            f"{status.get('interface', '—')} / {status.get('ip', '—')}"
        )
        self.status_labels["uptime"].set(str(status.get("uptime") or "—"))
        self.status_labels["tx_rx"].set(
            f"{_format_bytes(status.get('tx'))} / {_format_bytes(status.get('rx'))}"
        )
        if status.get("tx_rate") is not None or status.get("rx_rate") is not None:
            self.status_labels["rate"].set(
                f"{_format_rate(status.get('tx_rate'))} / {_format_rate(status.get('rx_rate'))}"
            )
        else:
            self.status_labels["rate"].set("—")
        self.status_labels["reconnects"].set(str(status.get("reconnects", 0)))
        self.status_var.set("Connected")

    # ---------------------------------------------------------- history tab

    def _build_history_tab(self):
        cols = ("when", "event", "profile", "duration", "server")
        tree = ttk.Treeview(self.history_tab, columns=cols, show="headings", height=14)
        for c, label, w in (
            ("when", "When", 150),
            ("event", "Event", 110),
            ("profile", "Profile", 110),
            ("duration", "Duration", 90),
            ("server", "Server", 220),
        ):
            tree.heading(c, text=label)
            tree.column(c, width=w, anchor="w")
        tree.pack(side="top", fill="both", expand=True)
        self.history_tree = tree

    def _tick_history(self):
        try:
            entries = list(reversed(history.read_history(limit=40)))
            self.history_tree.delete(*self.history_tree.get_children())
            for e in entries:
                duration = e.get("duration_seconds")
                duration_s = history._format_duration(duration) if duration is not None else "—"
                self.history_tree.insert(
                    "",
                    "end",
                    values=(
                        history._format_timestamp(e.get("timestamp", "")),
                        e.get("event", "?"),
                        e.get("profile") or "—",
                        duration_s,
                        e.get("server", "?"),
                    ),
                )
        finally:
            self.root.after(5000, self._tick_history)

    # ----------------------------------------------- connect / disconnect

    def refresh_profiles(self):
        self.cfg = config.load()
        self.profiles_map = dict(self.cfg.list_profiles())
        names = sorted(self.profiles_map)
        self._populate_profile_tree(names)

    def add_profile(self):
        dlg = ProfileDialog(self.root)
        if not dlg.result:
            return
        cfg = config.load()
        data = {
            "server": dlg.result["server"],
            "user_group": dlg.result["user_group"],
            "name": dlg.result["name"],
        }
        if dlg.result["user"]:
            data["credentials"] = {
                "username": dlg.result["user"],
                "totp_source": dlg.result["totp_source"],
            }
        cfg.add_profile(dlg.result["name"], data)
        config.save(cfg)
        self.refresh_profiles()

    def edit_profile(self):
        name = self._selected_profile_name()
        if not name:
            messagebox.showwarning("openconnect-saml", "Select a profile to edit.")
            return
        cfg = config.load()
        prof = cfg.get_profile(name)
        dlg = ProfileDialog(self.root, name=name, profile=prof)
        if not dlg.result:
            return
        data = {
            "server": dlg.result["server"],
            "user_group": dlg.result["user_group"],
            "name": dlg.result["name"],
        }
        if dlg.result["user"]:
            data["credentials"] = {
                "username": dlg.result["user"],
                "totp_source": dlg.result["totp_source"],
            }
        cfg.add_profile(name, data)
        config.save(cfg)
        self.refresh_profiles()

    def delete_profile(self):
        name = self._selected_profile_name()
        if not name:
            messagebox.showwarning("openconnect-saml", "Select a profile to delete.")
            return
        if not messagebox.askyesno(
            "openconnect-saml", f"Delete profile '{name}'? This cannot be undone."
        ):
            return
        cfg = config.load()
        cfg.remove_profile(name)
        if cfg.active_profile == name:
            cfg.active_profile = None
        config.save(cfg)
        self.refresh_profiles()

    def connect(self):
        name = self._selected_profile_name()
        if not name:
            messagebox.showwarning("openconnect-saml", "No profile selected.")
            return
        browser = self.browser_var.get() or DEFAULT_BROWSER
        cmd = [sys.executable, "-m", "openconnect_saml.cli", "connect", name, "--browser", browser]
        self.log.insert("end", f"$ {' '.join(cmd)}\n")
        self.proc = subprocess.Popen(  # nosec
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
                    self.connect_btn.configure(state="normal")
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
