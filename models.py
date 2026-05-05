"""
models.py
=========
Pure-data types shared across the entire application.
No I/O, no side-effects — only dataclasses and a helper enum.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List


class AlertKind(Enum):
    """Which resource triggered an alert."""
    CPU  = "cpu"
    RAM  = "ram"
    DISK = "disk"


@dataclass(frozen=True)
class Thresholds:
    """
    Alert threshold configuration (immutable).

    All values are percentages in the closed interval [1, 99].
    Being frozen means it can be shared across threads without a lock.
    """
    cpu:  float = 80.0
    ram:  float = 80.0
    disk: float = 90.0

    def __post_init__(self) -> None:
        for name, val in (("cpu", self.cpu), ("ram", self.ram), ("disk", self.disk)):
            if not (1.0 <= val <= 99.0):
                raise ValueError(
                    f"Threshold '{name}' must be in [1, 99], got {val!r}"
                )

    def replace(self, **kwargs: float) -> "Thresholds":
        """Return a *new* Thresholds with the specified fields overridden."""
        current = {"cpu": self.cpu, "ram": self.ram, "disk": self.disk}
        current.update(kwargs)
        return Thresholds(**current)


@dataclass
class ResourceSnapshot:
    """
    One point-in-time reading of all monitored resources.

    Attributes
    ----------
    timestamp    : human-readable string, e.g. "2026-05-04 12:00:00"
    cpu_percent  : 0.0 – 100.0
    ram_percent  : 0.0 – 100.0
    ram_used_gb  : gigabytes in use
    ram_total_gb : total installed RAM in gigabytes
    disk_percent : 0.0 – 100.0
    disk_used_gb : gigabytes in use
    disk_total_gb: total partition size in gigabytes
    alerts       : AlertKind values whose thresholds were exceeded
    """

    timestamp:     str
    cpu_percent:   float
    ram_percent:   float
    ram_used_gb:   float
    ram_total_gb:  float
    disk_percent:  float
    disk_used_gb:  float
    disk_total_gb: float
    alerts:        List[AlertKind] = field(default_factory=list)

    # ── Derived properties ────────────────────────────────────────────────────
    @property
    def has_alerts(self) -> bool:
        return bool(self.alerts)

    @property
    def alert_flags(self) -> str:
        """Comma-separated alert kinds, e.g. 'cpu,ram'.  Empty string if none."""
        return ",".join(a.value for a in self.alerts)

    # ── CSV serialisation ─────────────────────────────────────────────────────
    def to_csv_row(self) -> dict:
        """Return a flat dict ready for csv.DictWriter (matches CSV_FIELDS)."""
        return {
            "timestamp":     self.timestamp,
            "cpu_percent":   round(self.cpu_percent,  2),
            "ram_percent":   round(self.ram_percent,  2),
            "ram_used_gb":   round(self.ram_used_gb,  3),
            "ram_total_gb":  round(self.ram_total_gb, 3),
            "disk_percent":  round(self.disk_percent, 2),
            "disk_used_gb":  round(self.disk_used_gb, 3),
            "disk_total_gb": round(self.disk_total_gb, 3),
            "alert_flags":   self.alert_flags,
        }

    @classmethod
    def from_csv_row(cls, row: dict) -> "ResourceSnapshot":
        """Re-hydrate a snapshot from a csv.DictReader row dict."""
        flags_raw = row.get("alert_flags", "")
        alerts = [AlertKind(f) for f in flags_raw.split(",") if f.strip()]
        return cls(
            timestamp=row["timestamp"],
            cpu_percent=float(row["cpu_percent"]),
            ram_percent=float(row["ram_percent"]),
            ram_used_gb=float(row["ram_used_gb"]),
            ram_total_gb=float(row["ram_total_gb"]),
            disk_percent=float(row["disk_percent"]),
            disk_used_gb=float(row["disk_used_gb"]),
            disk_total_gb=float(row["disk_total_gb"]),
            alerts=alerts,
        )
