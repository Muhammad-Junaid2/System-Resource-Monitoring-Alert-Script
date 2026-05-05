#!/usr/bin/env python3
"""
gui.py
======
Tkinter GUI dashboard for SysMon.

Features
--------
* Three animated arc gauges (CPU / RAM / Disk) with threshold tick-marks
* Embedded matplotlib sparkline charts (falls back to pure-Canvas if absent)
* Real-time alert feed panel with timestamps
* Log-viewer tab that auto-refreshes on tab switch
* Threshold editor (modal Toplevel with validated spinboxes)
* Start / Stop / Export controls in a fixed status bar
* Clean shutdown — no zombie threads on window close

Architecture
------------
All UI mutations are routed through ``Tk.after(0, ...)`` so tkinter stays
single-threaded.  MonitorLoop fires callbacks from its daemon thread;
those callbacks immediately re-schedule themselves on the main thread.
"""

from __future__ import annotations

import argparse
import datetime
import logging
import math
import sys
import threading
import tkinter as tk
from collections import deque
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from constants import APP_NAME, APP_VERSION, GUI, LOG_FILE
from models import AlertKind, ResourceSnapshot, Thresholds
from monitor import CsvLogger, MonitorLoop, configure_logging

# ── Optional matplotlib ────────────────────────────────────────────────────────
try:
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

log = logging.getLogger(__name__)

# Unpack palette
BG     = GUI["BG"]
PANEL  = GUI["PANEL"]
BORDER = GUI["BORDER"]
ACCENT = GUI["ACCENT"]
GREEN  = GUI["GREEN"]
YELLOW = GUI["YELLOW"]
RED    = GUI["RED"]
TEXT   = GUI["TEXT"]
DIM    = GUI["DIM"]
FONT_H = GUI["FONT_H"]
FONT_M = GUI["FONT_M"]
FONT_S = GUI["FONT_S"]


# ── Colour helper ──────────────────────────────────────────────────────────────
def _value_color(value: float, threshold: float) -> str:
    if value >= threshold:          return RED
    if value >= threshold * 0.80:   return YELLOW
    return GREEN


# ─────────────────────────────────────────────────────────────────────────────
# Arc Gauge widget
# ─────────────────────────────────────────────────────────────────────────────
class GaugeWidget(tk.Canvas):
    """
    Circular arc gauge drawn on a tk.Canvas.

    The track sweeps 240° (210° → −30° clockwise).  A red tick marks the
    threshold position.  Value text and label sit at the centre.
    """

    _CX = 82
    _CY = 82
    _R  = 60

    def __init__(
        self,
        parent: tk.Widget,
        label: str,
        threshold: float = 80.0,
        **kwargs,
    ) -> None:
        super().__init__(
            parent,
            width=164,
            height=140,
            bg=BG,
            highlightthickness=0,
            **kwargs,
        )
        self._label     = label
        self._threshold = threshold
        self._value     = 0.0
        self._redraw()

    # ── Public ────────────────────────────────────────────────────────────────
    def update_threshold(self, threshold: float) -> None:
        self._threshold = threshold
        self._redraw()

    def set_value(self, value: float) -> None:
        self._value = max(0.0, min(100.0, value))
        self._redraw()

    # ── Drawing ───────────────────────────────────────────────────────────────
    def _redraw(self) -> None:
        self.delete("all")
        cx, cy, r = self._CX, self._CY, self._R
        color = _value_color(self._value, self._threshold)

        # Background track
        self.create_arc(
            cx - r, cy - r, cx + r, cy + r,
            start=210, extent=-240,
            style="arc", outline=BORDER, width=10,
        )

        # Value arc
        extent = -int(240 * self._value / 100)
        if extent != 0:
            self.create_arc(
                cx - r, cy - r, cx + r, cy + r,
                start=210, extent=extent,
                style="arc", outline=color, width=10,
            )

        # Threshold tick mark
        tick_deg = 210 - (self._threshold / 100 * 240)
        tick_rad = math.radians(tick_deg)
        r_i, r_o = r - 8, r + 3
        self.create_line(
            cx + r_i * math.cos(tick_rad),
            cy - r_i * math.sin(tick_rad),
            cx + r_o * math.cos(tick_rad),
            cy - r_o * math.sin(tick_rad),
            fill=RED, width=2,
        )

        # Percentage text
        self.create_text(
            cx, cy - 10,
            text=f"{self._value:.1f}%",
            font=("Consolas", 14, "bold"),
            fill=color,
        )

        # Label
        self.create_text(
            cx, cy + 14,
            text=self._label,
            font=FONT_S,
            fill=DIM,
        )

        # Limit label
        self.create_text(
            cx, cy + 30,
            text=f"lim {self._threshold:.0f}%",
            font=("Consolas", 7),
            fill=DIM,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Sparkline panel (matplotlib or canvas fallback)
# ─────────────────────────────────────────────────────────────────────────────
class SparklinePanel(tk.Frame):
    """
    Scrolling time-series chart embedded in a tk.Frame.

    Uses matplotlib/TkAgg when available; falls back to a hand-drawn
    tk.Canvas polyline otherwise.
    """

    _FACE = "#111523"

    def __init__(
        self,
        parent: tk.Widget,
        label: str,
        color: str,
        max_points: int = 60,
        **kwargs,
    ) -> None:
        super().__init__(
            parent,
            bg=PANEL,
            highlightthickness=1,
            highlightbackground=BORDER,
            **kwargs,
        )
        self._label    = label
        self._color    = color
        self._max_pts  = max_points
        self._data: deque[float] = deque([0.0] * max_points, maxlen=max_points)
        self._build()

    # ── Layout ────────────────────────────────────────────────────────────────
    def _build(self) -> None:
        hdr = tk.Frame(self, bg=PANEL)
        hdr.pack(fill="x", padx=8, pady=(4, 0))
        tk.Label(hdr, text=self._label, font=FONT_S,
                 bg=PANEL, fg=DIM).pack(side="left")
        self._cur_lbl = tk.Label(hdr, text="—", font=FONT_M,
                                 bg=PANEL, fg=self._color)
        self._cur_lbl.pack(side="right")

        if HAS_MPL:
            self._build_mpl()
        else:
            self._build_canvas()

    def _build_mpl(self) -> None:
        fig = Figure(figsize=(4, 0.7), dpi=96, facecolor=self._FACE)
        self._ax = fig.add_subplot(111)
        self._ax.set_facecolor(self._FACE)
        self._ax.set_xlim(0, self._max_pts - 1)
        self._ax.set_ylim(0, 105)
        self._ax.axis("off")
        fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

        self._line, = self._ax.plot(
            list(self._data), color=self._color, linewidth=1.2,
        )
        self._fill = self._ax.fill_between(
            range(self._max_pts), list(self._data),
            color=self._color, alpha=0.12,
        )

        canvas = FigureCanvasTkAgg(fig, master=self)
        canvas.get_tk_widget().configure(bg=self._FACE, highlightthickness=0)
        canvas.get_tk_widget().pack(fill="x", padx=4, pady=(0, 4))
        self._canvas = canvas

    def _build_canvas(self) -> None:
        self._tk_canvas = tk.Canvas(
            self, height=52, bg=self._FACE,
            highlightthickness=0,
        )
        self._tk_canvas.pack(fill="x", padx=4, pady=(0, 4))

    # ── Public ────────────────────────────────────────────────────────────────
    def push(self, value: float) -> None:
        self._data.append(value)
        self._cur_lbl.configure(text=f"{value:.1f}%")
        if HAS_MPL:
            self._update_mpl()
        else:
            self._update_canvas()

    # ── Render helpers ────────────────────────────────────────────────────────
    def _update_mpl(self) -> None:
        y = list(self._data)
        x = list(range(len(y)))
        self._line.set_data(x, y)
        self._fill.remove()
        self._fill = self._ax.fill_between(x, y,
                                           color=self._color, alpha=0.12)
        self._canvas.draw_idle()

    def _update_canvas(self) -> None:
        c = self._tk_canvas
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 2 or h < 2:
            return
        pts = list(self._data)
        n   = len(pts)
        step = w / max(n - 1, 1)
        coords = []
        for i, v in enumerate(pts):
            x = i * step
            y = h - (v / 100.0) * (h - 4) - 2
            coords.extend([x, y])
        if len(coords) >= 4:
            c.create_line(*coords, fill=self._color, width=1.5, smooth=True)


# ─────────────────────────────────────────────────────────────────────────────
# Alert feed panel
# ─────────────────────────────────────────────────────────────────────────────
class AlertFeedPanel(tk.Frame):
    """Scrolling text widget that accumulates alert messages."""

    _MAX_LINES = 200

    def __init__(self, parent: tk.Widget, **kwargs) -> None:
        super().__init__(parent, bg=PANEL,
                         highlightthickness=1,
                         highlightbackground=BORDER, **kwargs)
        hdr = tk.Frame(self, bg=PANEL)
        hdr.pack(fill="x", padx=8, pady=(4, 0))
        tk.Label(hdr, text="⚠  ALERT FEED", font=FONT_S,
                 bg=PANEL, fg=RED).pack(side="left")
        self._count_lbl = tk.Label(hdr, text="0 alerts", font=FONT_S,
                                   bg=PANEL, fg=DIM)
        self._count_lbl.pack(side="right")

        self._text = tk.Text(
            self,
            height=4,
            bg=PANEL,
            fg=RED,
            font=FONT_S,
            state="disabled",
            bd=0,
            highlightthickness=0,
            wrap="word",
        )
        self._text.pack(fill="x", padx=6, pady=(2, 6))
        self._alert_count = 0

    def push(self, snap: ResourceSnapshot) -> None:
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        lines = []
        if AlertKind.CPU  in snap.alerts:
            lines.append(f"CPU  {snap.cpu_percent:.1f}%")
        if AlertKind.RAM  in snap.alerts:
            lines.append(f"RAM  {snap.ram_percent:.1f}%")
        if AlertKind.DISK in snap.alerts:
            lines.append(f"Disk {snap.disk_percent:.1f}%")

        self._text.configure(state="normal")
        for line in lines:
            self._alert_count += 1
            self._text.insert("end", f"[{ts}]  ⚠  {line}\n")
        # Trim old lines to avoid unbounded growth
        total = int(self._text.index("end-1c").split(".")[0])
        if total > self._MAX_LINES:
            self._text.delete("1.0", f"{total - self._MAX_LINES}.0")
        self._text.see("end")
        self._text.configure(state="disabled")
        self._count_lbl.configure(text=f"{self._alert_count} alert(s)")


# ─────────────────────────────────────────────────────────────────────────────
# Threshold editor dialog
# ─────────────────────────────────────────────────────────────────────────────
class ThresholdDialog(tk.Toplevel):
    """
    Modal dialog for editing alert thresholds.

    After the user presses Save, ``self.result`` contains the new Thresholds
    object.  On Cancel / close, ``self.result`` is None.
    """

    def __init__(self, parent: tk.Widget, current: Thresholds) -> None:
        super().__init__(parent)
        self.title("Set Thresholds")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.grab_set()           # modal
        self.result: Optional[Thresholds] = None

        self._vars: dict[str, tk.DoubleVar] = {
            "cpu":  tk.DoubleVar(value=current.cpu),
            "ram":  tk.DoubleVar(value=current.ram),
            "disk": tk.DoubleVar(value=current.disk),
        }

        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        # Centre over the parent window
        self.update_idletasks()
        px = parent.winfo_rootx() + (parent.winfo_width()  - self.winfo_width())  // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{px}+{py}")

        self.wait_window(self)   # block until closed

    def _build(self) -> None:
        tk.Label(self, text="Alert Thresholds", font=FONT_H,
                 bg=BG, fg=ACCENT).grid(row=0, column=0, columnspan=2,
                                        padx=24, pady=(18, 10))

        for i, (key, label) in enumerate(
            [("cpu", "CPU  %"), ("ram", "RAM  %"), ("disk", "Disk %")],
            start=1,
        ):
            tk.Label(self, text=label, font=FONT_M,
                     bg=BG, fg=TEXT).grid(row=i, column=0,
                                          padx=(24, 8), pady=8, sticky="w")
            sb = tk.Spinbox(
                self,
                from_=1, to=99,
                textvariable=self._vars[key],
                width=7,
                font=FONT_M,
                bg=PANEL, fg=ACCENT,
                buttonbackground=BORDER,
                insertbackground=ACCENT,
                relief="flat",
                bd=1,
            )
            sb.grid(row=i, column=1, padx=(0, 24), pady=8, sticky="w")

        btn_frame = tk.Frame(self, bg=BG)
        btn_frame.grid(row=4, column=0, columnspan=2, pady=(4, 18))

        tk.Button(
            btn_frame, text="Cancel", command=self._on_cancel,
            font=FONT_S, bg=BORDER, fg=DIM,
            activebackground=BORDER, relief="flat", padx=16, pady=5,
        ).pack(side="left", padx=6)

        tk.Button(
            btn_frame, text="Save", command=self._on_save,
            font=FONT_S, bg=BORDER, fg=GREEN,
            activebackground=GREEN, activeforeground=BG,
            relief="flat", padx=16, pady=5,
        ).pack(side="left", padx=6)

    def _on_save(self) -> None:
        try:
            self.result = Thresholds(
                cpu=float(self._vars["cpu"].get()),
                ram=float(self._vars["ram"].get()),
                disk=float(self._vars["disk"].get()),
            )
        except ValueError as exc:
            messagebox.showerror("Invalid Value", str(exc), parent=self)
            return
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# Log viewer tab
# ─────────────────────────────────────────────────────────────────────────────
class LogViewerTab(tk.Frame):
    """Notebook tab that shows the last N CSV log entries in a Treeview."""

    _COLS = ("Timestamp", "CPU%", "RAM%", "Disk%", "Alerts")
    _WIDTHS = (180, 70, 70, 70, 120)

    def __init__(self, parent: tk.Widget, csv_logger: CsvLogger, **kwargs) -> None:
        super().__init__(parent, bg=BG, **kwargs)
        self._csv_logger = csv_logger
        self._build()

    def _build(self) -> None:
        toolbar = tk.Frame(self, bg=BG)
        toolbar.pack(fill="x", padx=14, pady=(10, 4))

        tk.Button(
            toolbar, text="↻  Refresh", command=self.refresh,
            font=FONT_S, bg=BORDER, fg=ACCENT,
            activebackground=ACCENT, activeforeground=BG,
            relief="flat", padx=12, pady=4,
        ).pack(side="left")

        self._path_lbl = tk.Label(
            toolbar,
            text=f"Log: {self._csv_logger.path}",
            font=FONT_S, bg=BG, fg=DIM,
        )
        self._path_lbl.pack(side="left", padx=10)

        # Configure Treeview style
        style = ttk.Style()
        style.theme_use("default")
        style.configure(
            "LogTree.Treeview",
            background=PANEL, foreground=TEXT,
            fieldbackground=PANEL,
            rowheight=22, font=FONT_S,
        )
        style.configure(
            "LogTree.Treeview.Heading",
            background=BORDER, foreground=ACCENT, font=FONT_S,
        )
        style.map("LogTree.Treeview",
                  background=[("selected", GUI["ACCENT2"])],
                  foreground=[("selected", BG)])

        frame = tk.Frame(self, bg=BG)
        frame.pack(fill="both", expand=True, padx=14, pady=(0, 12))

        self._tree = ttk.Treeview(
            frame,
            columns=self._COLS,
            show="headings",
            height=18,
            style="LogTree.Treeview",
        )
        for col, width in zip(self._COLS, self._WIDTHS):
            self._tree.heading(col, text=col)
            self._tree.column(col, width=width, anchor="center",
                              minwidth=width)

        vsb = ttk.Scrollbar(frame, orient="vertical",
                            command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)

        self._tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

    def refresh(self) -> None:
        self._tree.delete(*self._tree.get_children())
        for snap in reversed(self._csv_logger.read_last(200)):
            alert_str = snap.alert_flags.upper() if snap.has_alerts else "—"
            self._tree.insert(
                "", "end",
                values=(
                    snap.timestamp,
                    f"{snap.cpu_percent:.1f}%",
                    f"{snap.ram_percent:.1f}%",
                    f"{snap.disk_percent:.1f}%",
                    alert_str,
                ),
            )
        # Scroll to the most-recent (first) row
        children = self._tree.get_children()
        if children:
            self._tree.see(children[0])


# ─────────────────────────────────────────────────────────────────────────────
# Main application window
# ─────────────────────────────────────────────────────────────────────────────
class SysMonApp(tk.Tk):
    """
    Root window.  Owns the MonitorLoop, CsvLogger, and all top-level widgets.
    """

    def __init__(
        self,
        interval:  float = 3.0,
        disk_path: str   = "/",
    ) -> None:
        super().__init__()
        self.title(f"⚡  {APP_NAME}  v{APP_VERSION}  —  System Monitor")
        self.configure(bg=BG)
        self.geometry("860x680")
        self.minsize(760, 580)

        self._interval    = interval
        self._disk_path   = disk_path
        self._thresholds  = Thresholds()
        self._csv_logger  = CsvLogger()
        self._loop: Optional[MonitorLoop] = None

        self._build_titlebar()
        self._notebook = self._build_notebook()
        self._build_statusbar()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Window construction ────────────────────────────────────────────────────
    def _build_titlebar(self) -> None:
        bar = tk.Frame(self, bg=PANEL, height=48)
        bar.pack(fill="x")
        bar.pack_propagate(False)

        tk.Label(
            bar,
            text=f"⚡  {APP_NAME.upper()}",
            font=("Consolas", 15, "bold"),
            bg=PANEL, fg=ACCENT,
        ).pack(side="left", padx=18, pady=12)

        tk.Label(bar, text=f"v{APP_VERSION}",
                 font=FONT_S, bg=PANEL, fg=DIM).pack(side="left")

        self._status_lbl = tk.Label(
            bar, text="● IDLE", font=FONT_S, bg=PANEL, fg=DIM,
        )
        self._status_lbl.pack(side="right", padx=18)

        self._ts_lbl = tk.Label(bar, text="", font=FONT_S, bg=PANEL, fg=DIM)
        self._ts_lbl.pack(side="right", padx=8)

    def _build_notebook(self) -> ttk.Notebook:
        style = ttk.Style()
        style.theme_use("default")
        style.configure(
            "SysMonNB.TNotebook",
            background=BG, borderwidth=0, tabmargins=0,
        )
        style.configure(
            "SysMonNB.TNotebook.Tab",
            background=PANEL, foreground=DIM,
            font=FONT_S, padding=(16, 5),
        )
        style.map(
            "SysMonNB.TNotebook.Tab",
            background=[("selected", BORDER)],
            foreground=[("selected", ACCENT)],
        )

        nb = ttk.Notebook(self, style="SysMonNB.TNotebook")
        nb.pack(fill="both", expand=True, padx=6, pady=6)

        # Dashboard tab
        dash = tk.Frame(nb, bg=BG)
        nb.add(dash, text="  Dashboard  ")
        self._build_dashboard(dash)

        # Logs tab
        self._log_tab = LogViewerTab(nb, self._csv_logger)
        nb.add(self._log_tab, text="  Logs  ")

        nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        return nb

    def _build_dashboard(self, parent: tk.Frame) -> None:
        # Gauge row
        gauge_row = tk.Frame(parent, bg=BG)
        gauge_row.pack(fill="x", padx=14, pady=(12, 6))
        self._g_cpu  = self._make_gauge(gauge_row, "CPU Usage",  self._thresholds.cpu)
        self._g_ram  = self._make_gauge(gauge_row, "RAM Usage",  self._thresholds.ram)
        self._g_disk = self._make_gauge(gauge_row, "Disk Usage", self._thresholds.disk)

        # Sparkline charts
        spark_frame = tk.Frame(parent, bg=BG)
        spark_frame.pack(fill="x", padx=14, pady=2)
        self._sp_cpu  = SparklinePanel(spark_frame, "CPU  HISTORY", ACCENT)
        self._sp_ram  = SparklinePanel(spark_frame, "RAM  HISTORY", GREEN)
        self._sp_disk = SparklinePanel(spark_frame, "DISK HISTORY", YELLOW)
        for sp in (self._sp_cpu, self._sp_ram, self._sp_disk):
            sp.pack(fill="x", pady=2)

        # Alert feed
        self._alert_feed = AlertFeedPanel(parent)
        self._alert_feed.pack(fill="x", padx=14, pady=(4, 8))

    def _make_gauge(
        self, parent: tk.Frame, label: str, threshold: float,
    ) -> GaugeWidget:
        card = tk.Frame(
            parent, bg=PANEL,
            highlightthickness=1, highlightbackground=BORDER,
        )
        card.pack(side="left", expand=True, fill="x", padx=5)
        g = GaugeWidget(card, label, threshold=threshold)
        g.pack(pady=10)
        return g

    def _build_statusbar(self) -> None:
        bar = tk.Frame(self, bg=PANEL, height=50)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)

        def _btn(text: str, cmd, fg: str = ACCENT) -> tk.Button:
            return tk.Button(
                bar, text=text, command=cmd, font=FONT_S,
                bg=BORDER, fg=fg,
                activebackground=fg, activeforeground=BG,
                relief="flat", padx=14, pady=6, cursor="hand2",
            )

        self._btn_start = _btn("▶  Start", self._start_monitoring, GREEN)
        self._btn_start.pack(side="left", padx=(12, 4), pady=8)

        self._btn_stop = _btn("■  Stop", self._stop_monitoring, RED)
        self._btn_stop.pack(side="left", padx=4, pady=8)
        self._btn_stop.configure(state="disabled")

        _btn("⚙  Thresholds", self._open_threshold_dialog).pack(
            side="left", padx=4, pady=8,
        )
        _btn("↓  Export", self._export_csv).pack(side="left", padx=4, pady=8)
        _btn("✕  Exit", self._on_close, RED).pack(side="right", padx=12, pady=8)

        self._thresh_lbl = tk.Label(bar, font=FONT_S, bg=PANEL, fg=DIM)
        self._thresh_lbl.pack(side="left", padx=8)
        self._refresh_thresh_label()

    # ── Monitoring lifecycle ───────────────────────────────────────────────────
    def _start_monitoring(self) -> None:
        if self._loop and self._loop.running:
            return
        self._loop = MonitorLoop(
            thresholds=self._thresholds,
            csv_logger=self._csv_logger,
            interval=self._interval,
            disk_path=self._disk_path,
            on_snapshot=lambda s: self.after(0, self._on_snapshot, s),
            on_alert=lambda s: self.after(0, self._on_alert, s),
            notify_desktop=True,
        )
        self._loop.start()
        self._btn_start.configure(state="disabled")
        self._btn_stop.configure(state="normal")
        self._status_lbl.configure(text="● MONITORING", fg=GREEN)
        log.info("GUI: monitoring started")

    def _stop_monitoring(self) -> None:
        if self._loop:
            self._loop.stop()
        self._btn_start.configure(state="normal")
        self._btn_stop.configure(state="disabled")
        self._status_lbl.configure(text="● STOPPED", fg=YELLOW)
        log.info("GUI: monitoring stopped")

    # ── Callbacks (always on the main thread via after()) ─────────────────────
    def _on_snapshot(self, snap: ResourceSnapshot) -> None:
        self._ts_lbl.configure(text=snap.timestamp)
        self._g_cpu.set_value(snap.cpu_percent)
        self._g_ram.set_value(snap.ram_percent)
        self._g_disk.set_value(snap.disk_percent)
        self._sp_cpu.push(snap.cpu_percent)
        self._sp_ram.push(snap.ram_percent)
        self._sp_disk.push(snap.disk_percent)

    def _on_alert(self, snap: ResourceSnapshot) -> None:
        self._alert_feed.push(snap)

    # ── Threshold editor ──────────────────────────────────────────────────────
    def _open_threshold_dialog(self) -> None:
        dlg = ThresholdDialog(self, self._thresholds)
        if dlg.result is None:
            return
        self._thresholds = dlg.result
        # Hot-swap into running loop (if any)
        if self._loop:
            self._loop.update_thresholds(self._thresholds)
        # Update gauge tick marks
        self._g_cpu.update_threshold(self._thresholds.cpu)
        self._g_ram.update_threshold(self._thresholds.ram)
        self._g_disk.update_threshold(self._thresholds.disk)
        self._refresh_thresh_label()
        log.info(
            "Thresholds updated — cpu=%.0f  ram=%.0f  disk=%.0f",
            self._thresholds.cpu, self._thresholds.ram, self._thresholds.disk,
        )

    def _refresh_thresh_label(self) -> None:
        t = self._thresholds
        self._thresh_lbl.configure(
            text=f"CPU ≥{t.cpu:.0f}%   RAM ≥{t.ram:.0f}%   Disk ≥{t.disk:.0f}%"
        )

    # ── Export ────────────────────────────────────────────────────────────────
    def _export_csv(self) -> None:
        rows = self._csv_logger.read_last(1000)
        if not rows:
            messagebox.showinfo(
                "Export", "No log data to export yet.", parent=self,
            )
            return
        out = self._csv_logger.path.parent / "sysmon_export.txt"
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(f"{APP_NAME} v{APP_VERSION}  —  Log Export\n")
            fh.write("=" * 70 + "\n\n")
            fh.write(
                f"  {'Timestamp':<22}  {'CPU%':>6}  {'RAM%':>6}  {'Disk%':>6}  Alerts\n"
            )
            fh.write("  " + "─" * 60 + "\n")
            for snap in rows:
                fh.write(
                    f"  {snap.timestamp:<22}  "
                    f"{snap.cpu_percent:>5.1f}%  "
                    f"{snap.ram_percent:>5.1f}%  "
                    f"{snap.disk_percent:>5.1f}%  "
                    f"{snap.alert_flags or '—'}\n"
                )
            fh.write(f"\n  Total entries: {len(rows)}\n")
        messagebox.showinfo(
            "Export", f"Saved {len(rows)} rows\n→ {out}", parent=self,
        )

    # ── Tab change ────────────────────────────────────────────────────────────
    def _on_tab_changed(self, _event: tk.Event) -> None:
        selected = self._notebook.index(self._notebook.select())
        if selected == 1:
            self._log_tab.refresh()

    # ── Window close ──────────────────────────────────────────────────────────
    def _on_close(self) -> None:
        if self._loop and self._loop.running:
            self._loop.stop()
        self.destroy()


# ── Entry point ────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        prog="sysmon-gui",
        description=f"{APP_NAME} v{APP_VERSION} — GUI dashboard",
    )
    parser.add_argument(
        "--interval", type=float, default=3.0, metavar="SEC",
        help="seconds between samples (default: 3.0)",
    )
    parser.add_argument(
        "--disk", default="/", metavar="PATH",
        help="disk mount point to monitor (default: /)",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="enable debug-level logging",
    )
    args = parser.parse_args()

    configure_logging(logging.DEBUG if args.debug else logging.WARNING)
    app = SysMonApp(interval=args.interval, disk_path=args.disk)
    app.mainloop()


if __name__ == "__main__":
    main()
