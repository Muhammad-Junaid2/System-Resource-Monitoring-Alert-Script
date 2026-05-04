#  SysMon — System Resource Monitor

A real-time CPU, RAM, and Disk monitoring tool with both a **CLI** and **Tkinter GUI** dashboard, alert system, and CSV logging.

---

##  Project Structure

```
sysmon/
├── monitor.py              # Core monitoring engine (psutil)
├── cli.py                  # Command-line interface
├── gui.py                  # Tkinter GUI dashboard
├── generate_sample_log.py  # Generates demo log data
├── logs/
│   └── sysmon_log.csv      # Auto-created log file
└── README.md
```

---

##  Quick Start

### 1. Install dependencies

```bash
pip install psutil matplotlib plyer
```

### 2. Run CLI mode

```bash
python cli.py
```

### 3. Run GUI mode

```bash
python gui.py
```

---

##  Features

###  Resource Monitoring (via `psutil`)
| Metric | Details |
|--------|---------|
| CPU    | Usage % (1-second interval) |
| RAM    | Usage %, Used GB / Total GB |
| Disk   | Usage %, Used GB / Total GB |

###  CLI Interface
- Full-color terminal display with ASCII progress bars
- Real-time refresh every 3 seconds
- Color-coded values: 🟢 Green → 🟡 Yellow → 🔴 Red
- Menu: Start Monitoring / Set Thresholds / View Logs / Exit

###  GUI Dashboard
- Arc gauges for CPU, RAM, Disk
- Scrolling sparkline charts (60-point history)
- Alert feed panel (timestamped alerts)
- Log viewer tab with sortable table
- Threshold editor popup
- Start / Stop controls

###  Alert System
- User-defined thresholds (default: CPU 80%, RAM 80%, Disk 90%)
- Alert messages printed in CLI + shown in GUI alert feed
- Desktop notifications via `plyer` (if supported)

###  Logging
- Auto-creates `logs/sysmon_log.csv`
- Columns: `timestamp, cpu_percent, ram_percent, ram_used_gb, ram_total_gb, disk_percent, disk_used_gb, disk_total_gb`
- Appends every sample (no overwrites)

---

##  CLI Menu Options

```
[1]  Start Monitoring   — live display, Ctrl+C to return
[2]  Set Thresholds     — change CPU / RAM / Disk % limits
[3]  View Logs          — last 20 entries in colour table
[4]  Exit
```

---

##  Screenshots

Run either `cli.py` or `gui.py` to see the live dashboard.

---

## Dependencies

| Library    | Purpose |
|------------|---------|
| `psutil`   | System resource readings |
| `tkinter`  | GUI (built-in with Python) |
| `matplotlib` | Graph visualisation (optional) |
| `plyer`    | Desktop notifications (optional) |

---

##  Log Format (CSV)

```
timestamp,cpu_percent,ram_percent,ram_used_gb,ram_total_gb,disk_percent,disk_used_gb,disk_total_gb
2026-05-04 12:00:00,34.2,61.5,9.84,16.0,72.3,370.3,512.0
```

---

##  Tested On

- Python 3.10+
- Windows 10/11
- macOS 12+
- Ubuntu 22.04

---

##  License

MIT — free to use, modify, and distribute.

## Developed by

Muhammad Junaid# System-Resource-Monitoring-Alert-Script
