"""
constants.py
============
Centralised application-wide constants and default configuration values.
All tuneable values live here — nothing is magic-numbered elsewhere.
"""

from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────────
BASE_DIR: Path = Path(__file__).resolve().parent
LOG_DIR:  Path = BASE_DIR / "logs"
LOG_FILE: Path = LOG_DIR  / "sysmon.csv"
APP_LOG:  Path = LOG_DIR  / "sysmon.log"

# ── Application metadata ───────────────────────────────────────────────────────
APP_NAME    = "SysMon"
APP_VERSION = "2.0.0"

# ── Monitoring defaults ────────────────────────────────────────────────────────
DEFAULT_INTERVAL: float = 3.0        # seconds between each sample
CPU_INTERVAL:     float = 1.0        # psutil cpu_percent blocking interval
HISTORY_POINTS:   int   = 60         # sparkline ring-buffer length
LOG_ROTATE_BYTES: int   = 5_242_880  # 5 MB — rotate log after this size
LOG_BACKUP_COUNT: int   = 3          # number of rotated CSV back-ups to keep

# ── Default alert thresholds (%) ──────────────────────────────────────────────
DEFAULT_CPU_THRESHOLD:  float = 80.0
DEFAULT_RAM_THRESHOLD:  float = 80.0
DEFAULT_DISK_THRESHOLD: float = 90.0
THRESHOLD_MIN: float = 1.0
THRESHOLD_MAX: float = 99.0

# ── CSV column names (order matters — matches DictWriter fieldnames) ───────────
CSV_FIELDS: tuple[str, ...] = (
    "timestamp",
    "cpu_percent",
    "ram_percent",
    "ram_used_gb",
    "ram_total_gb",
    "disk_percent",
    "disk_used_gb",
    "disk_total_gb",
    "alert_flags",        # comma-separated list, e.g. "cpu,ram"
)

# ── GUI palette (hex strings + tk font tuples) ─────────────────────────────────
GUI: dict = {
    "BG":      "#0B0E1A",
    "PANEL":   "#111523",
    "BORDER":  "#1C2138",
    "ACCENT":  "#00D4FF",
    "ACCENT2": "#7B61FF",
    "GREEN":   "#00E676",
    "YELLOW":  "#FFD740",
    "RED":     "#FF4444",
    "TEXT":    "#D8E0F0",
    "DIM":     "#404868",
    "FONT_H":  ("Consolas", 11, "bold"),
    "FONT_M":  ("Consolas", 10),
    "FONT_S":  ("Consolas", 9),
}

# ── CLI ANSI escape codes ──────────────────────────────────────────────────────
ANSI: dict[str, str] = {
    "RESET":  "\033[0m",
    "BOLD":   "\033[1m",
    "DIM":    "\033[2m",
    "RED":    "\033[91m",
    "YELLOW": "\033[93m",
    "GREEN":  "\033[92m",
    "CYAN":   "\033[96m",
}
