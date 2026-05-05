#!/usr/bin/env python3
"""
cli.py
======
Command-line interface for SysMon.

Usage
-----
    python cli.py [--interval SECONDS] [--disk PATH] [--debug]

Menu
----
    [1]  Start Monitoring
    [2]  Set Thresholds
    [3]  View Logs
    [4]  Graph  (requires matplotlib)
    [5]  Export Logs to TXT
    [6]  Exit
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

# Ensure the package root is on sys.path regardless of cwd
sys.path.insert(0, str(Path(__file__).resolve().parent))

from constants import ANSI, APP_NAME, APP_VERSION, LOG_FILE
from models import AlertKind, ResourceSnapshot, Thresholds
from monitor import CsvLogger, MonitorLoop, configure_logging

log = logging.getLogger(__name__)

# Unpack ANSI codes for convenience
RESET  = ANSI["RESET"]
BOLD   = ANSI["BOLD"]
DIM    = ANSI["DIM"]
RED    = ANSI["RED"]
YELLOW = ANSI["YELLOW"]
GREEN  = ANSI["GREEN"]
CYAN   = ANSI["CYAN"]


# ── Terminal helpers ───────────────────────────────────────────────────────────
def _clr() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def _color(value: float, warn_pct: float, danger_pct: float) -> str:
    if value >= danger_pct:
        return RED
    if value >= warn_pct:
        return YELLOW
    return GREEN


def _bar(pct: float, width: int = 32) -> str:
    filled = min(int(pct / 100 * width), width)
    return "█" * filled + "░" * (width - filled)


def _fmt_gb(used: float, total: float) -> str:
    return f"{used:.2f}/{total:.2f} GB"


# ── Header banner (built once) ─────────────────────────────────────────────────
_HEADER = (
    f"{CYAN}{BOLD}"
    "╔══════════════════════════════════════════════════════════╗\n"
    f"║        ⚡  {APP_NAME}  v{APP_VERSION}  —  System Monitor           ║\n"
    "╚══════════════════════════════════════════════════════════╝"
    f"{RESET}"
)


# ── Live snapshot display ──────────────────────────────────────────────────────
def _render(snap: ResourceSnapshot, thresh: Thresholds) -> None:
    """Render one snapshot to the terminal (clears the screen first)."""
    _clr()
    print(_HEADER)
    print(f"  {DIM}Updated : {snap.timestamp}{RESET}\n")

    def _row(label: str, pct: float, warn: float, danger: float,
             extra: str = "") -> None:
        c = _color(pct, warn, danger)
        suffix = f"  {DIM}{extra}{RESET}" if extra else ""
        print(
            f"  {BOLD}{label:<10}{RESET}"
            f"{c}{pct:6.1f}%{RESET}  "
            f"[{c}{_bar(pct)}{RESET}]"
            f"{suffix}"
        )

    _row("CPU     ", snap.cpu_percent,
         thresh.cpu  * 0.75, thresh.cpu)
    _row("RAM     ", snap.ram_percent,
         thresh.ram  * 0.75, thresh.ram,
         _fmt_gb(snap.ram_used_gb, snap.ram_total_gb))
    _row("DISK    ", snap.disk_percent,
         thresh.disk * 0.75, thresh.disk,
         _fmt_gb(snap.disk_used_gb, snap.disk_total_gb))

    print(
        f"\n  {DIM}Thresholds — "
        f"CPU ≥{thresh.cpu:.0f}%  "
        f"RAM ≥{thresh.ram:.0f}%  "
        f"Disk ≥{thresh.disk:.0f}%{RESET}"
    )

    if snap.has_alerts:
        sep = f"  {RED}{BOLD}{'─' * 56}{RESET}"
        print(sep)
        for kind in snap.alerts:
            label  = kind.value.upper()
            pct    = getattr(snap, f"{kind.value}_percent")
            limit  = getattr(thresh, kind.value)
            print(f"  {RED}  ⚠  {label} ALERT: {pct:.1f}% ≥ {limit:.0f}%{RESET}")
        print(sep)

    print(f"\n  {DIM}Press Ctrl+C to return to menu{RESET}")


# ── Action: Start Monitoring ───────────────────────────────────────────────────
def action_start(
    thresh_holder: list[Thresholds],
    csv_logger: CsvLogger,
    interval: float,
    disk_path: str,
) -> None:
    """
    Launch a MonitorLoop, render each snapshot live, block until Ctrl+C.

    A mutable list is used as a simple shared cell so the (frozen)
    Thresholds object can be swapped while monitoring is running.
    """
    loop = MonitorLoop(
        thresholds=thresh_holder[0],
        csv_logger=csv_logger,
        interval=interval,
        disk_path=disk_path,
        on_snapshot=lambda s: _render(s, thresh_holder[0]),
    )
    loop.start()
    try:
        while loop.running:
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        loop.stop()

    print(f"\n  {GREEN}Monitoring stopped.{RESET}")
    time.sleep(0.8)


# ── Action: Set Thresholds ─────────────────────────────────────────────────────
def action_set_thresholds(thresh_holder: list[Thresholds]) -> None:
    cur = thresh_holder[0]
    print(f"\n{CYAN}{BOLD}  ─── Set Alert Thresholds ───{RESET}")
    updates: dict[str, float] = {}

    for key, cur_val in (("cpu", cur.cpu), ("ram", cur.ram), ("disk", cur.disk)):
        while True:
            raw = input(
                f"  {key.upper()} threshold %  (current: {cur_val:.0f}%)  "
                "[Enter to keep]: "
            ).strip()
            if not raw:
                break
            try:
                val = float(raw)
                if 1.0 <= val <= 99.0:
                    updates[key] = val
                    break
                print(f"  {YELLOW}Value must be between 1 and 99.{RESET}")
            except ValueError:
                print(f"  {RED}Invalid input — please enter a number.{RESET}")

    thresh_holder[0] = cur.replace(**updates)
    t = thresh_holder[0]
    print(
        f"\n  {GREEN}Thresholds saved — "
        f"CPU ≥{t.cpu:.0f}%  RAM ≥{t.ram:.0f}%  Disk ≥{t.disk:.0f}%{RESET}"
    )
    time.sleep(1.2)


# ── Action: View Logs ──────────────────────────────────────────────────────────
def action_view_logs(csv_logger: CsvLogger, n: int = 25) -> None:
    rows = csv_logger.read_last(n)
    _clr()
    print(_HEADER)

    if not rows:
        print(
            f"\n  {YELLOW}No log entries found. "
            f"Start monitoring to create data.{RESET}\n"
        )
        input("  Press Enter to continue...")
        return

    print(f"  {BOLD}Last {len(rows)} entries{RESET}  {DIM}({csv_logger.path}){RESET}\n")
    hdr = f"  {'Timestamp':<22}  {'CPU%':>6}  {'RAM%':>6}  {'Disk%':>6}  Alerts"
    print(f"{CYAN}{hdr}{RESET}")
    print(f"  {'─' * 60}")

    for snap in rows:
        cc = _color(snap.cpu_percent,  60, 80)
        rc = _color(snap.ram_percent,  60, 80)
        dc = _color(snap.disk_percent, 70, 90)
        alert_str = (
            f"{RED}⚠ {snap.alert_flags}{RESET}"
            if snap.has_alerts
            else f"{DIM}—{RESET}"
        )
        print(
            f"  {snap.timestamp:<22}  "
            f"{cc}{snap.cpu_percent:>5.1f}%{RESET}  "
            f"{rc}{snap.ram_percent:>5.1f}%{RESET}  "
            f"{dc}{snap.disk_percent:>5.1f}%{RESET}  "
            f"{alert_str}"
        )

    print(f"\n  {DIM}Log file: {csv_logger.path}{RESET}")
    input("\n  Press Enter to continue...")


# ── Action: Graph ──────────────────────────────────────────────────────────────
def action_graph(csv_logger: CsvLogger) -> None:
    try:
        import datetime as dt

        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
    except ImportError:
        print(f"\n  {RED}matplotlib is not installed.{RESET}")
        print(f"  Run:  {CYAN}pip install matplotlib{RESET}")
        time.sleep(2)
        return

    rows = csv_logger.read_last(120)
    if len(rows) < 2:
        print(f"\n  {YELLOW}Not enough data to plot. Run monitoring first.{RESET}")
        time.sleep(2)
        return

    times     = [dt.datetime.strptime(r.timestamp, "%Y-%m-%d %H:%M:%S") for r in rows]
    cpu_vals  = [r.cpu_percent  for r in rows]
    ram_vals  = [r.ram_percent  for r in rows]
    disk_vals = [r.disk_percent for r in rows]

    fig, axes = plt.subplots(3, 1, figsize=(12, 7), sharex=True)
    fig.suptitle(f"{APP_NAME} v{APP_VERSION}  —  Resource History",
                 fontsize=13, fontweight="bold")
    fig.patch.set_facecolor("#0B0E1A")

    for ax, vals, color, ylabel in (
        (axes[0], cpu_vals,  "#00D4FF", "CPU %"),
        (axes[1], ram_vals,  "#00E676", "RAM %"),
        (axes[2], disk_vals, "#FFD740", "Disk %"),
    ):
        ax.set_facecolor("#111523")
        ax.plot(times, vals, color=color, linewidth=1.4, antialiased=True)
        ax.fill_between(times, vals, alpha=0.15, color=color)
        ax.set_ylabel(ylabel, color="#D8E0F0", fontsize=9)
        ax.tick_params(colors="#404868")
        ax.set_ylim(0, 105)
        ax.axhline(80, color="#FF4444", linewidth=0.7, linestyle="--", alpha=0.6)
        for spine in ax.spines.values():
            spine.set_edgecolor("#1C2138")
        ax.yaxis.label.set_color("#D8E0F0")

    axes[2].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.autofmt_xdate(rotation=30)
    plt.tight_layout()
    plt.show()


# ── Action: Export TXT ─────────────────────────────────────────────────────────
def action_export_txt(csv_logger: CsvLogger) -> None:
    rows = csv_logger.read_last(1000)
    if not rows:
        print(f"\n  {YELLOW}No data to export.{RESET}")
        time.sleep(1.5)
        return

    export_path = csv_logger.path.parent / "sysmon_export.txt"
    with open(export_path, "w", encoding="utf-8") as fh:
        fh.write(f"{APP_NAME} v{APP_VERSION}  —  Log Export\n")
        fh.write("=" * 70 + "\n\n")
        fh.write(f"  {'Timestamp':<22}  {'CPU%':>6}  {'RAM%':>6}  {'Disk%':>6}  Alerts\n")
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

    print(f"\n  {GREEN}Exported {len(rows)} rows → {export_path}{RESET}")
    time.sleep(1.5)


# ── Main menu ──────────────────────────────────────────────────────────────────
_MENU = [
    ("1", "Start Monitoring"),
    ("2", "Set Thresholds"),
    ("3", "View Logs"),
    ("4", "Graph  (requires matplotlib)"),
    ("5", "Export Logs to TXT"),
    ("6", "Exit"),
]


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="sysmon-cli",
        description=f"{APP_NAME} v{APP_VERSION} — System Resource Monitor (CLI)",
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
    log.info("CLI starting — interval=%.1fs  disk=%s", args.interval, args.disk)

    csv_logger    = CsvLogger()
    thresh_holder = [Thresholds()]   # mutable cell wrapping immutable Thresholds

    while True:
        _clr()
        print(_HEADER)
        t = thresh_holder[0]
        print(
            f"\n  {DIM}Thresholds — "
            f"CPU ≥{t.cpu:.0f}%  "
            f"RAM ≥{t.ram:.0f}%  "
            f"Disk ≥{t.disk:.0f}%{RESET}\n"
        )
        for key, label in _MENU:
            print(f"  {CYAN}[{key}]{RESET}  {label}")
        print()

        choice = input("  Select an option: ").strip()

        if choice == "1":
            action_start(thresh_holder, csv_logger, args.interval, args.disk)
        elif choice == "2":
            action_set_thresholds(thresh_holder)
        elif choice == "3":
            action_view_logs(csv_logger)
        elif choice == "4":
            action_graph(csv_logger)
        elif choice == "5":
            action_export_txt(csv_logger)
        elif choice == "6":
            print(f"\n  {GREEN}Goodbye!{RESET}\n")
            sys.exit(0)
        else:
            print(f"  {RED}Invalid choice — please enter 1–6.{RESET}")
            time.sleep(0.9)


if __name__ == "__main__":
    main()
