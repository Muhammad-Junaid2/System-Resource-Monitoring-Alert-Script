#!/usr/bin/env python3
"""
generate_sample_log.py
======================
Produce a realistic demo CSV log for SysMon.
Run once to populate the log before starting the app.

Usage
-----
    python generate_sample_log.py [--rows N]
"""

from __future__ import annotations

import argparse
import csv
import datetime
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from constants import CSV_FIELDS, LOG_DIR, LOG_FILE


def _random_walk(
    current: float,
    speed: float,
    lo: float,
    hi: float,
    spike_prob: float = 0.05,
    spike_mag: float  = 18.0,
) -> float:
    delta = random.gauss(0, speed)
    if random.random() < spike_prob:
        delta += random.choice([-1, 1]) * random.uniform(spike_mag * 0.5, spike_mag)
    return max(lo, min(hi, current + delta))


def generate(n: int = 60, path: Path = LOG_FILE) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    cpu  = 28.0
    ram  = 45.0
    disk = 63.0
    now  = datetime.datetime.now() - datetime.timedelta(seconds=n * 30)

    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()

        for _ in range(n):
            cpu  = _random_walk(cpu,  speed=6.0, lo=2.0,  hi=98.0)
            ram  = _random_walk(ram,  speed=2.5, lo=20.0, hi=95.0)
            disk = _random_walk(disk, speed=0.4, lo=55.0, hi=95.0)

            alerts = []
            if cpu  >= 80: alerts.append("cpu")
            if ram  >= 80: alerts.append("ram")
            if disk >= 90: alerts.append("disk")

            writer.writerow({
                "timestamp":     now.strftime("%Y-%m-%d %H:%M:%S"),
                "cpu_percent":   round(cpu,  2),
                "ram_percent":   round(ram,  2),
                "ram_used_gb":   round(ram  / 100 * 16.0, 3),
                "ram_total_gb":  16.0,
                "disk_percent":  round(disk, 2),
                "disk_used_gb":  round(disk / 100 * 512.0, 3),
                "disk_total_gb": 512.0,
                "alert_flags":   ",".join(alerts),
            })
            now += datetime.timedelta(seconds=30)

    print(f"✅  {n} rows written → {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate SysMon sample log data")
    parser.add_argument("--rows", type=int, default=60, metavar="N",
                        help="number of rows to generate (default: 60)")
    args = parser.parse_args()
    generate(n=args.rows)
