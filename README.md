# ⚡ SysMon — System Resource Monitor  
**Version 2.0.0**

Real-time CPU, RAM, and Disk monitoring with a full-featured **CLI** and **Tkinter GUI** dashboard, configurable alert thresholds, CSV logging with rotation, matplotlib graphs, and desktop notifications.

---

## Project Structure

```
sysmon/
├── constants.py            # All app-wide config & defaults
├── models.py               # Pure data types (Thresholds, ResourceSnapshot, AlertKind)
├── monitor.py              # Core engine: psutil reads, CSV logger, MonitorLoop
├── cli.py                  # Command-line interface
├── gui.py                  # Tkinter GUI dashboard
├── generate_sample_log.py  # Populate demo log data
├── logs/
│   ├── sysmon.csv          # Auto-created CSV data log
│   └── sysmon.log          # Rotating application log
└── README.md
```

---

## Quick Start

### 1. Install dependencies

```bash
pip install psutil matplotlib plyer
```

| Package      | Required | Purpose                         |
|--------------|----------|---------------------------------|
| `psutil`     | ✅ Yes    | System resource readings        |
| `tkinter`    | ✅ Yes    | GUI (bundled with Python)       |
| `matplotlib` | ⚡ Recommended | Sparkline charts in GUI / graph in CLI |
| `plyer`      | Optional  | Desktop notifications           |

### 2. Generate sample data (optional)

```bash
python generate_sample_log.py --rows 120
```

### 3a. Run the CLI

```bash
python cli.py                         # default settings
python cli.py --interval 5 --disk /   # 5-second interval, root disk
python cli.py --debug                 # enable verbose logging
```

### 3b. Run the GUI

```bash
python gui.py
python gui.py --interval 5 --disk C:\\   # Windows example
```

---

## CLI Menu

```
[1]  Start Monitoring       live display — Ctrl+C to return
[2]  Set Thresholds         change CPU / RAM / Disk % limits interactively
[3]  View Logs              colour-coded table of the last 25 entries
[4]  Graph                  matplotlib time-series chart (requires matplotlib)
[5]  Export Logs to TXT     save last 1000 rows to sysmon_export.txt
[6]  Exit
```

**Command-line flags:**

| Flag              | Default | Description                      |
|-------------------|---------|----------------------------------|
| `--interval SEC`  | 3.0     | Seconds between samples          |
| `--disk PATH`     | `/`     | Mount point to monitor           |
| `--debug`         | off     | Enable DEBUG-level log output    |

---

## GUI Features

| Component        | Description                                                  |
|------------------|--------------------------------------------------------------|
| Arc Gauges       | Animated 240° arc per resource with threshold tick-mark      |
| Sparkline Charts | 60-point scrolling history using matplotlib (or Canvas)      |
| Alert Feed       | Timestamped, scrolling alert messages with counter           |
| Log Viewer Tab   | Auto-refreshing Treeview table, newest entry at top          |
| Threshold Dialog | Modal spinbox editor with live validation                    |
| Export Button    | Writes `sysmon_export.txt` with all recent log rows          |
| Status Bar       | Start / Stop / Thresholds / Export / Exit controls           |

---

## Alert System

Default thresholds (all configurable at runtime):

| Resource | Default Threshold |
|----------|------------------|
| CPU      | 80 %             |
| RAM      | 80 %             |
| Disk     | 90 %             |

When any threshold is exceeded:
1. The value turns **red** in both CLI and GUI.
2. The alert is printed (CLI) or appended to the alert feed (GUI).
3. A desktop notification fires if `plyer` is installed.
4. The `alert_flags` column in the CSV is populated (e.g. `cpu,ram`).

---

## Log Format (CSV)

```
timestamp,cpu_percent,ram_percent,ram_used_gb,ram_total_gb,disk_percent,disk_used_gb,disk_total_gb,alert_flags
2026-05-05 12:00:00,34.20,61.50,9.840,16.000,72.30,370.300,512.000,
2026-05-05 12:00:30,82.10,81.20,12.992,16.000,72.40,370.812,512.000,cpu,ram
```

- Logs rotate at **5 MB** with up to **3** backup files (`sysmon.1.csv`, etc.).
- The application log (`sysmon.log`) uses Python's `RotatingFileHandler`.

---

## Architecture

```
cli.py / gui.py
    │
    ├── MonitorLoop (daemon thread)
    │       │
    │       ├── take_snapshot()  →  psutil reads
    │       ├── CsvLogger.write()
    │       ├── on_snapshot callback  →  UI update
    │       └── on_alert callback     →  alert display + desktop notify
    │
    ├── CsvLogger  (thread-safe, size-rotating)
    └── Thresholds (frozen dataclass — safe to share across threads)
```

**Thread safety:** All tkinter widget mutations are dispatched through
`widget.after(0, fn, *args)` so the GUI always runs on the main thread.

---

## Platform Notes

| Platform | Notes                                              |
|----------|----------------------------------------------------|
| Linux    | Works out of the box; disk path defaults to `/`    |
| macOS    | Works; use `/` or a specific mount point           |
| Windows  | Disk path auto-corrects `/` → `C:\\`; use `--disk C:\\` if needed |

---

## Dependencies

```
psutil>=5.9
matplotlib>=3.6   (recommended)
plyer>=2.1        (optional — desktop notifications)
```

Python **3.10+** required (uses built-in `tuple[...]` type hints).

---

## License

MIT — free to use, modify, and distribute.

## Developed by

Muhammad Junaid 
