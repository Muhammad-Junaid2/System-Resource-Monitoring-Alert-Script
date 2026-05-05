"""
monitor.py
==========
Core monitoring engine.

Responsibilities
----------------
* Read CPU / RAM / Disk metrics via psutil.
* Evaluate alert thresholds and annotate each snapshot.
* Persist snapshots to a rotating CSV log.
* Drive a threaded monitoring loop with a clean stop mechanism.
* Optionally fire desktop notifications via plyer (graceful degradation).

This module has NO tkinter / CLI dependency — it is pure business logic
and is safe to import from any front-end.
"""

from __future__ import annotations

import csv
import datetime
import logging
import os
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable, Optional

import psutil

from constants import (
    APP_LOG, CPU_INTERVAL, CSV_FIELDS, DEFAULT_INTERVAL,
    LOG_BACKUP_COUNT, LOG_DIR, LOG_FILE, LOG_ROTATE_BYTES,
)
from models import AlertKind, ResourceSnapshot, Thresholds

# ── Module-level logger ────────────────────────────────────────────────────────
log = logging.getLogger(__name__)


# ── Logging bootstrap (call once from any entry point) ────────────────────────
def configure_logging(level: int = logging.INFO) -> None:
    """
    Set up rotating-file + console logging.
    Safe to call multiple times — handlers are only added once.
    """
    root = logging.getLogger()
    if root.handlers:
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = RotatingFileHandler(
        APP_LOG,
        maxBytes=LOG_ROTATE_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)

    root.setLevel(level)
    root.addHandler(fh)
    root.addHandler(ch)


# ── Low-level resource readers ─────────────────────────────────────────────────
def _read_cpu() -> float:
    """Return CPU usage %.  Blocks for CPU_INTERVAL seconds (psutil design)."""
    try:
        return psutil.cpu_percent(interval=CPU_INTERVAL)
    except Exception:
        log.exception("Failed to read CPU usage")
        return 0.0


def _read_ram() -> tuple[float, float, float]:
    """Return (percent, used_gb, total_gb) for virtual memory."""
    try:
        m  = psutil.virtual_memory()
        gb = 1024 ** 3
        return m.percent, m.used / gb, m.total / gb
    except Exception:
        log.exception("Failed to read RAM usage")
        return 0.0, 0.0, 0.0


def _read_disk(path: str = "/") -> tuple[float, float, float]:
    """Return (percent, used_gb, total_gb) for the disk at *path*."""
    # Windows root is C:\\ not /
    if os.name == "nt" and path == "/":
        path = "C:\\"
    try:
        d  = psutil.disk_usage(path)
        gb = 1024 ** 3
        return d.percent, d.used / gb, d.total / gb
    except PermissionError:
        log.warning("Permission denied reading disk at %s", path)
        return 0.0, 0.0, 0.0
    except Exception:
        log.exception("Failed to read disk usage for %s", path)
        return 0.0, 0.0, 0.0


# ── Snapshot factory ───────────────────────────────────────────────────────────
def take_snapshot(thresholds: Thresholds, disk_path: str = "/") -> ResourceSnapshot:
    """
    Sample all resources and return a fully-annotated ResourceSnapshot.

    The CPU read blocks for CPU_INTERVAL seconds by design — psutil needs
    a reference window to produce a meaningful percentage.
    """
    cpu                           = _read_cpu()
    ram_pct, ram_used, ram_tot    = _read_ram()
    disk_pct, disk_used, disk_tot = _read_disk(disk_path)

    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    alerts: list[AlertKind] = []
    if cpu      >= thresholds.cpu:  alerts.append(AlertKind.CPU)
    if ram_pct  >= thresholds.ram:  alerts.append(AlertKind.RAM)
    if disk_pct >= thresholds.disk: alerts.append(AlertKind.DISK)

    snap = ResourceSnapshot(
        timestamp=ts,
        cpu_percent=cpu,
        ram_percent=ram_pct,
        ram_used_gb=ram_used,
        ram_total_gb=ram_tot,
        disk_percent=disk_pct,
        disk_used_gb=disk_used,
        disk_total_gb=disk_tot,
        alerts=alerts,
    )
    log.debug(
        "Snapshot: CPU=%.1f%%  RAM=%.1f%%  Disk=%.1f%%  alerts=%s",
        cpu, ram_pct, disk_pct, snap.alert_flags or "none",
    )
    return snap


# ── CSV persistence ────────────────────────────────────────────────────────────
class CsvLogger:
    """
    Thread-safe, append-only CSV logger with size-based log rotation.

    Parameters
    ----------
    path         : destination CSV file (created on first write)
    max_bytes    : rotate when the file exceeds this size (0 = never)
    backup_count : how many rotated files to keep
    """

    def __init__(
        self,
        path: Path = LOG_FILE,
        max_bytes: int = LOG_ROTATE_BYTES,
        backup_count: int = LOG_BACKUP_COUNT,
    ) -> None:
        self._path         = path
        self._max_bytes    = max_bytes
        self._backup_count = backup_count
        self._lock         = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        log.info("CsvLogger ready → %s", path)

    # ── Public API ─────────────────────────────────────────────────────────────
    def write(self, snap: ResourceSnapshot) -> None:
        """Append one snapshot row.  Thread-safe."""
        with self._lock:
            self._maybe_rotate()
            write_header = (
                not self._path.exists() or self._path.stat().st_size == 0
            )
            try:
                with open(self._path, "a", newline="", encoding="utf-8") as fh:
                    writer = csv.DictWriter(
                        fh, fieldnames=CSV_FIELDS, extrasaction="ignore"
                    )
                    if write_header:
                        writer.writeheader()
                    writer.writerow(snap.to_csv_row())
            except OSError:
                log.exception("Failed to write CSV row to %s", self._path)

    def read_last(self, n: int = 100) -> list[ResourceSnapshot]:
        """Return the most-recent *n* snapshots, oldest-first."""
        if not self._path.exists():
            return []
        try:
            with open(self._path, newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
        except OSError:
            log.exception("Failed to read CSV log %s", self._path)
            return []

        results: list[ResourceSnapshot] = []
        for row in rows[-n:]:
            try:
                results.append(ResourceSnapshot.from_csv_row(row))
            except (KeyError, ValueError):
                log.warning("Skipped malformed CSV row: %s", row)
        return results

    @property
    def path(self) -> Path:
        return self._path

    # ── Internal ───────────────────────────────────────────────────────────────
    def _maybe_rotate(self) -> None:
        """Rename the current file when it exceeds the size limit."""
        if self._max_bytes <= 0:
            return
        if not self._path.exists() or self._path.stat().st_size < self._max_bytes:
            return

        # Shift existing back-ups  (.2 → .3,  .1 → .2)
        for i in range(self._backup_count - 1, 0, -1):
            src = self._path.with_suffix(f".{i}.csv")
            dst = self._path.with_suffix(f".{i + 1}.csv")
            if src.exists():
                src.replace(dst)

        # Move current file → .1.csv
        rotated = self._path.with_suffix(".1.csv")
        self._path.replace(rotated)
        log.info("CSV rotated → %s", rotated)


# ── Desktop notification (optional) ───────────────────────────────────────────
def _notify(title: str, message: str) -> None:
    """Fire a desktop notification.  Silently skipped if plyer is absent."""
    try:
        from plyer import notification  # type: ignore[import]
        notification.notify(
            title=title, message=message,
            timeout=6, app_name="SysMon",
        )
    except Exception:
        pass  # plyer missing or platform unsupported — not critical


# ── Monitor loop ───────────────────────────────────────────────────────────────
class MonitorLoop:
    """
    Continuous sampling loop running on a daemon background thread.

    Usage
    -----
    ::

        loop = MonitorLoop(
            thresholds   = Thresholds(),
            csv_logger   = CsvLogger(),
            on_snapshot  = my_ui_update_fn,   # called with ResourceSnapshot
            on_alert     = my_alert_fn,        # called with ResourceSnapshot
        )
        loop.start()
        ...
        loop.stop()   # blocks until the thread exits cleanly

    Thread safety
    -------------
    * Callbacks are fired from the monitor thread.
    * GUI callbacks MUST use ``widget.after(0, fn, snap)`` to hop to the
      main thread — tkinter is not thread-safe.
    * ``update_thresholds()`` may be called from any thread.
    """

    def __init__(
        self,
        thresholds:     Thresholds,
        csv_logger:     CsvLogger,
        interval:       float = DEFAULT_INTERVAL,
        disk_path:      str   = "/",
        on_snapshot:    Optional[Callable[[ResourceSnapshot], None]] = None,
        on_alert:       Optional[Callable[[ResourceSnapshot], None]] = None,
        notify_desktop: bool  = True,
    ) -> None:
        # Clamp interval so it's always longer than the CPU blocking read
        self._thresholds     = thresholds
        self._csv_logger     = csv_logger
        self._interval       = max(interval, CPU_INTERVAL + 0.5)
        self._disk_path      = disk_path
        self._on_snapshot    = on_snapshot
        self._on_alert       = on_alert
        self._notify_desktop = notify_desktop
        self._stop_event     = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ── Thread-safe threshold hot-swap ────────────────────────────────────────
    def update_thresholds(self, thresholds: Thresholds) -> None:
        """Replace thresholds atomically.  Safe to call from any thread."""
        self._thresholds = thresholds

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    def start(self) -> None:
        """Start the background thread (no-op if already running)."""
        if self._thread and self._thread.is_alive():
            log.warning("MonitorLoop.start() called while already running — ignored")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name="SysMonLoop", daemon=True
        )
        self._thread.start()
        log.info("Monitor loop started (interval=%.1fs  disk=%s)",
                 self._interval, self._disk_path)

    def stop(self, timeout: float = 6.0) -> None:
        """Signal the loop to stop and block until the thread exits."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                log.warning("Monitor thread did not exit within %.1fs", timeout)
        log.info("Monitor loop stopped")

    @property
    def running(self) -> bool:
        """True while the background thread is alive and not stopping."""
        return bool(
            self._thread
            and self._thread.is_alive()
            and not self._stop_event.is_set()
        )

    # ── Main loop ──────────────────────────────────────────────────────────────
    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                snap = take_snapshot(self._thresholds, self._disk_path)
                self._csv_logger.write(snap)

                if self._on_snapshot:
                    self._on_snapshot(snap)

                if snap.has_alerts:
                    if self._on_alert:
                        self._on_alert(snap)
                    if self._notify_desktop:
                        lines = []
                        if AlertKind.CPU  in snap.alerts:
                            lines.append(f"CPU  {snap.cpu_percent:.1f}%")
                        if AlertKind.RAM  in snap.alerts:
                            lines.append(f"RAM  {snap.ram_percent:.1f}%")
                        if AlertKind.DISK in snap.alerts:
                            lines.append(f"Disk {snap.disk_percent:.1f}%")
                        _notify("SysMon Alert", "\n".join(lines))

            except Exception:
                log.exception("Unexpected error in monitor loop — continuing")

            # Sleep in small ticks so the stop event is honoured promptly
            deadline = time.monotonic() + self._interval - CPU_INTERVAL
            while time.monotonic() < deadline:
                if self._stop_event.is_set():
                    return
                time.sleep(0.1)
