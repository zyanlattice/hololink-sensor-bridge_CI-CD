# HSB Test Framework: JSON Helper v2.0

**Everything you need to run tests and view results in a dashboard.**

---

## Requirements

### Python Version
- **Python 3.8+** (tested on 3.8, 3.9, 3.10)

### Required Libraries
```bash
pip install streamlit pandas plotly
```

**Dependencies:**
- `streamlit` - Dashboard web interface (required)
- `pandas` - Data manipulation for dashboard (required)
- `plotly` - Interactive charts in dashboard (required)
- `sqlite3` - Database engine ✅ **Built into Python** (no install needed)
- `json`, `pathlib`, `xml.etree.ElementTree` - ✅ **Built into Python**

### Quick Install

#### Option 1: Virtual Environment (Recommended for Linux/Ubuntu)
```bash
# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate  # Linux/Mac
# OR
venv\Scripts\activate  # Windows

# Install dependencies
pip install streamlit pandas plotly

# Verify installation
python -c "import streamlit, pandas, plotly, sqlite3; print('✓ All dependencies installed')"

# When done, deactivate
deactivate
```

#### Option 2: Direct Install (Windows or systems without externally-managed-environment)
```bash
pip install streamlit pandas plotly
```

#### Option 3: Using pipx (for standalone tool installation)
```bash
# Install pipx first (if not installed)
sudo apt install pipx  # Ubuntu/Debian
pipx ensurepath

# Install streamlit as standalone tool
pipx install streamlit

# Note: You'll still need pandas and plotly in your environment
```

**Verify Installation:**
```bash
python -c "import streamlit, pandas, plotly, sqlite3; print('✓ All dependencies installed')"
```

**⚠️ Linux/Ubuntu Users:** If you see `externally-managed-environment` error, use Option 1 (virtual environment) above.

---

## Quick Start (60 seconds)

```bash
# 1. Run test (creates JSON)
python my_test.py
# OR for pytest integration:
pytest  # Creates test_reports/logs_YYYYMMDD_HHMMSS/test_results_*.json

# 2. Setup database (one-time)
python init_sql.py

# 3. Ingest results - provide path to folder or file
python ingestion_script.py results/
# OR for pytest:
python ingestion_script.py ../test_reports/logs_20260212_143022

# 4. View dashboard - Choose one:
python start_dashboard.py          # Python way (Ctrl+C to stop)
# OR
streamlit run local_browser_dashboard.py  # Direct way

# Opens http://localhost:8501
```

---

## What is json_helper_v2?

A **flexible, generic test reporting framework** for the Orin + FPGA HSB system.

**Key Features:**
- ✅ Generate structured JSON test reports
- ✅ Support arbitrary metrics (frame gap, CRC, power, thermal, etc.)
- ✅ Track artifacts (plots, logs, images)
- ✅ Organize by test category and tags
- ✅ Automatic yield rate calculation
- ✅ Export to SQLite database
- ✅ Visualize in Streamlit dashboard

**No vendor lock-in.** JSON is portable, searchable, archivable.

---

## Architecture: Test → JSON → Database → Dashboard

```
Your Test Script (my_test.py) OR Pytest Suite
    ↓ uses json_helper_v2
JSON Report (results/summary.json OR test_results_*.json)
    ↓ ingested by (YOU PROVIDE PATH)
SQLite Database (db/results.sqlite) ← Data persists here
    ↓ queried by
Streamlit Dashboard (http://localhost:8501)
    ↓
Your Web Browser
```

**Key Points:**
- 📁 **JSON files** are temporary (archived in test_reports/ or results/)
- 💾 **SQLite database** (`db/results.sqlite`) stores ALL data permanently
- 🔄 **Each ingestion ADDS to database** (doesn't overwrite previous runs)
- 📊 **Dashboard reads from database** (not JSON files)

---

## How to Write a Test

### Minimal Example

```python
from json_helper_v2 import create_report, Artifact
from pathlib import Path

# 1. Create report with environment info
report = create_report(env={
    "orin_image": "r36.3",
    "fpga_bitstream": "hsb_20260125_01",
    "git_sha": "abc123",
    "branch": "main",
    "dataset": "camA_1080p60"
})

# 2. Run your test and measure results
frame_gap_mean = 16.67
test_passed = frame_gap_mean <= 18.0

# 3. Record test result
report.add_test(
    name="frame_gap_jitter",
    status="pass" if test_passed else "fail",
    duration_ms=12000,
    metrics={
        "frame_gap_ms_mean": frame_gap_mean,
        "frame_gap_ms_p95": 17.4,
    },
    category="performance",
    tags=["csi", "raw"]
)

# 4. Save to JSON
report.finalize()
report.write(Path("results"))
```

**That's it!** See `my_test.py` for a complete working example.

---

## Test Categories

Organize your tests by category (used for dashboard grouping):

| Category | Use Case | Examples |
|----------|----------|----------|
| `performance` | Speed, throughput, latency | frame_gap, throughput, latency |
| `compliance` | Standards, specs, correctness | CRC, data_integrity, format_check |
| `stability` | Long-running, stress tests | thermal_stability, memory_leak |
| `networking` | Ethernet, PTP, packets | eth_speed, ptp_sync, packet_loss |
| `resource-monitoring` | Power, thermal, memory | power_avg, temp_max, mem_usage |

---

## Running Tests

### Single Test (Standalone Script)

```bash
python my_test.py
python ingestion_script.py results/
```

Dashboard shows:
- Total Tests: 1
- Status: pass/fail
- Metrics and artifacts

### Single Test (Pytest Integration)

```bash
pytest test_my_feature.py
# Creates: test_reports/logs_20260212_143022/test_results_20260212_143022.json
python ingestion_script.py ../test_reports/logs_20260212_143022
```

**Note:** You must provide the specific folder path - ingestion doesn't auto-detect latest folder.

### Test Suite (Multiple Tests)

```python
# my_test_suite.py
from json_helper_v2 import create_report

report = create_report(env={...})

report.add_test(name="test_1", status="pass", duration_ms=5000, metrics={...})
report.add_test(name="test_2", status="fail", duration_ms=3000, metrics={...})
report.add_test(name="test_3", status="pass", duration_ms=7000, metrics={...})

report.finalize()
report.write(Path("results"))
```

```bash
python my_test_suite.py
python ingestion_script.py results/
```

Dashboard shows:
- Total Tests: 3
- Passed: 2, Failed: 1
- Yield Rate: 66.7%

### Iterative Testing

```bash
# First iteration
python my_test.py
python ingestion_script.py results/
# Open dashboard

# Modify test, FPGA bitstream, or Orin software...

# Second iteration (re-run test)
python my_test.py
python ingestion_script.py results/
# Refresh browser (Cmd+R)
# Dashboard shows trend across 2 runs

# Third iteration
python my_test.pyJSON file:
- **Standalone tests:** `results/summary.json`
- **Pytest integration:** `test_reports/logs_YYYYMMDD_HHMMSS/test_results_YYYYMMDD_HHMMSS.json`

Example structure
python ingestion_script.py results/
# Refresh browser
# Dashboard shows trend line across 3 runs
```

---

## Understanding the JSON Report

Each test run generates one `results/summary.json`:

```json
{
  "run_id": "2026-01-26_17-37-35_local",
  "env": {
    "orin_image": "r36.3",
    "fpga_bitstream": "hsb_20260125_01"
  },
  "timestamp": "2026-01-26T09:37:35.863147+00:00",
  "tests": [
    {
      "name": "frame_gap_jitter",
      "status": "fail",
      "duration_ms": 12000,
      "metrics": {
        "frame_gap_ms_mean": 16.67,
        "frame_gap_ms_p95": 17.4
      },
      "artifacts": [
        {
          "type": "png",
          "path": "frames/frame_gap_histogram.png",
          "label": "Frame Gap Distribution"
        }
      ],
      "category": "performance",
      "tags": ["csi", "raw"]
    }
  ],
  "summary": {
    "total_tests": 1,
    "passed": 0,
    "failed": 1,
    "yield_rate": 0.0
  }
}
```

**Location:** `Reporting_JSON_SQL/db/results.sqlite`

**Persistence:** ✅ Data is **permanent** - stored until you manually delete the `db/` folder.

**Growth:** Each ingestion **adds** new runs to the database (doesn't overwrite).

After ingestion, data is organized

## Understanding the Database

After ingestion, data is in 4 SQLite tables:

### `runs` Table
One row per test run with environment metadata.

```
run_id | timestamp | orin_image | fpga_bitstream | git_sha | branch | dataset
-------+-----------+------------+----------------+---------+--------+--------
```

### `tests` Table
One row per test with status and duration.

```
test_id | run_id | name | status | duration_ms | category | error_message
--------+--------+------+--------+-------------+----------+---------------
```

### `metrics` Table
One row per metric per test.

```
metric_id | test_id | name | value | unit | scope
----------+---------+------+-------+------+-------
```

### `artifacts` Table
One row per artifact (images, logs, data files).

```
artifact_id | test_id | type | path | label | meta
------------+---------+------+------+-------+------
```

**View the database:**
```bash
python inspect_database.py
```

---

## Understanding the Dashboard

### KPI Row
```
┌──────────────┬──────────────┬──────────────┬──────────────┐
│ Total Runs   │ Total Tests  │ Passed       │ Yield Rate   │
│ 3            │ 9            │ 7            │ 77.8%        │
└──────────────┴──────────────┴──────────────┴──────────────┘
```

### Charts
- **Yield Over Time:** Line chart by build/bitstream
- **Metric Trends:** Metric values across runs

### Drilldown
- **Run Selector:** View specific run details
- **Test Results Table:** Name, status, duration, error
- **Metric Explorer:** Filter and view metrics by type
- **Artifacts:** PNG images, plot (Standalone)
```bash
python my_test.py
python ingestion_script.py results/
# Refresh browser
```
**Time:** ~2 seconds

### Workflow A2: Debug Single Test (Pytest)
```bash
pytest test_my_feature.py -v
# Note the output folder: test_reports/logs_20260212_143022
python ingestion_script.py ../test_reports/logs_20260212_143022
# Refresh browser
```
**Time:** ~5 A: Debug Single Test
```bash
python my_test.py
python ingestion_script.py results/
# Refresh browser
```
**Time:** ~2 seconds

### Workflow B: Run Full Test Suite
```bash
python test_suite.py
python ingestion_script.py results/
# Refresh browser
```
**Time:** Depends on test duration

### Workflow C: Compare Builds
```bash
# Build A
git checkout build_a
python test_suite.py
python ingestion_script.py results/

# Build B
git checkout build_b
python test_suite.py
python ingestion_script.py results/

# View comparison
streamlit run local_browser_dashboard.py
```

Dashboard shows:
- Yield rate by build
- Metrics side-by-side
- Performance delta

### Workflow D: Reset & Start Fresh
```bash
rm -r results/ db/
python init_sql.py
```

---

## File Reference

## File Reference

### Core Scripts (7 files - Everything you need)

| File | Purpose |
|------|---------|
| `json_helper.py` | Generate JSON reports from test results |
| `init_sql.py` | Initialize SQLite database (one-time setup) |
| `ingestion_script.py` | Import JSON reports into SQLite database |
| `inspect_database.py` | View database contents and verify data |
| `local_browser_dashboard.py` | Streamlit dashboard visualization |
| `start_dashboard.py` | Dashboard launcher with graceful Ctrl+C stop |
| `my_test.py` | **Your test template** - copy and modify for your tests |

### Data Directories (Auto-created)

| Directory | Purpose |
|-----------|---------|
| `results/` | JSON reports generated by your tests |
| `db/` | SQLite database (results.sqlite) |

---

## Advanced: Custom Metrics

Define metrics with units and scope:

```python
from json_helper_v2 import MetricRegistry, MetricScope

registry = MetricRegistry()
registry.register(
    name="power_avg_w",
    unit="watts",
    scope=MetricScope.RUN,
    description="Average power consumption"
)

report.add_test(
    name="power_test",
    metrics={"power_avg_w": 5.2},
    category="resource-monitoring"
)
report.finalize(metric_registry=registry)
```

---

## Advanced: Artifacts & Timeseries

### Artifacts (Images, Logs)

```python
report.add_test(
    name="frame_gap_jitter",
    artifacts=[
        Artifact(
            type="png",
            path="frames/frame_gap_histogram.png",
            label="Frame Gap Distribution",
            meta={"width": 800, "height": 600}
        ),
        Artifact(
            type="log",
            path="logs/test.log",
            label="Test Log"
        )
    ]
)
```

### Timeseries Data (Large Files)

```python
report.add_timeseries(
    name="frame_gap_ms",
    path="metrics/frame_gap_ms.parquet",
    count=18000,
    meta={"source": "orchestrator", "unit": "ms"}
)
```

Dashboard can later fetch these files for deep dives.

---

## Troubleshooting

### "externally-managed-environment" Error (Linux/Ubuntu)

**Error Message:**
```
error: externally-managed-environment
× This environment is externally managed
```

**Solution:** Use a virtual environment (Python 3.11+ security feature):

```bash
# 1. Create virtual environment (one-time)
python3 -m venv venv

# 2. Activate it (every terminal session)
source venv/bin/activate

# 3. Install packages
pip install streamlit pandas plotly

# 4. Run your scripts normally
python init_sql.py
python ingestion_script.py results/
python start_dashboard.py

# 5. Deactivate when done
deactivate
```

**Why this happens:** Modern Linux distributions (Ubuntu 23.04+, Debian 12+) use PEP 668 to prevent system Python corruption. Virtual environments are the recommended solution.

**Alternative (NOT recommended):** `pip install --break-system-packages` can damage your system Python.

---

### "   Artifact(
            type="png",
            path="frames/frame_gap_histogram.png",
            label="Frame Gap Distribution",
            meta={"width": 800, "height": 600}
        ),
        Artifact(
            type="log",
            path="logs/test.log",
            label="Test Log"
        )
    ]
)
```

### Timeseries Data (Large Files)

```python
report.add_timeseries(
    name="frame_gap_ms",
    path="metrics/frame_gap_ms.parquet",
    count=18000,
    meta={"source": "orchestrator", "unit": "ms"}
)
```

Dashboard can later fetch these files for deep dives.

---

## Troubleshooting

### "Dashboard shows no data"
```bash
# Check if data was ingested
python inspect_database.py

# Check results directory
ls -la results/
```

**Solution:** Run `python ingestion_script.py results/`

---

### "sqlite3.OperationalError: table runs has no column named..."

If you get a schema mismatch error:

```bash
# Delete old database
rm -r db/

# Recreate with correct schema
python init_sql.py

# Try ingestion again
python ingestion_script.py results/
```

**What happened:** The schema was updated. Old database is incompatible. Delete and reinitialize.

---

### "Test appears but metrics don't"
```bash
python -m json.tool results/summary.json
```

**Make sure:**
1. `report.finalize()` was called before `write()`
2. Metrics dict is not empty
3. `report.write(Path("results"))` was called

---

### "Dashboard updates slowly"
Streamlit caches data. Force refresh:
1. Edit `local_browser_dashboard.py` (add/remove space)
2. Save file
3. Dashboard auto-reloads

Or restart:
```bash
python start_dashboard.py
# Press Ctrl+C to stop cleanly
```

---

### "Can't stop dashboard with Ctrl+C"
Use the wrapper script instead:
```bash
# Python wrapper (better signal handling)
python start_dashboard.py

# Now Ctrl+C will stop it cleanly
```

On Windows with `streamlit run`, you can also:
- Use `dashboard.bat` to run in a separate window
- Close that window to stop the dashboard

### "Can't connect to dashboard"
```bash
# Check if Streamlit is running
lsof -i :8501

# Use different port
streamlit run local_browser_dashboard.py --server.port 8502
```

Then open: http://localhost:8502

---

## API Reference

### create_report()

```python
report = create_report(
    env={
        "orin_image": "r36.3",
        "fpga_bitstream": "hsb_v1",
        "git_sha": "abc123",
        "branch": "main"
    },
    run_id="optional_custom_id",
    schema_version="2.0"
)
```

### report.add_test()

```python
report.add_test(
    name="test_name",
    status="pass",  # "pass", "fail", "skip", "partial"
    duration_ms=1000.0,
    metrics={"metric1": 10.5, "metric2": 20},
    artifacts=[Artifact(...)],  # Optional
    category="performance",      # Optional
    tags=["tag1", "tag2"],       # Optional
    error_message="..."          # Optional
)
```

### report.add_timeseries()

```python
report.add_timeseries(
    name="timeseries_name",
    path="metrics/data.parquet",
    count=18000,
    meta={"unit": "ms"}
)
```

### report.finalize()

```python (standalone)
python my_test.py

# Run test (pytest)
pytest test_file.py  # Note output folder from pytest

# Setup database (one-time)
python init_sql.py

# Ingest results - MUST provide path
python ingestion_script.py results/                           # Standalone
python ingestion_script.py ../test_reports/logs_20260212_143022  # Pytest

# View database (location: db/results.sqlite)
---

## Quick Commands

```bash
# Run test
python my_test.py

# Setup database (one-time)
python init_sql.py

# Ingest results
python ingestion_script.py results/

# View database
python inspect_database.py

# Start dashboard (with Ctrl+C support)
python start_dashboard.py

# Start dashboard (direct, no easy stop)
streamlit run local_browser_dashboard.py

# View JSON
python -m json.tool results/summary.json

# View walkthrough demo
python complete_walkthrough.py

# Reset everything
rm -r results/ db/
python init_sql.py
```

---

## Example: Frame Gap Test

See `my_test.py` for a complete, working example.

To run:
```bash
python my_test.py
python ingestion_script.py results/
streamlit run local_browser_dashboard.py
```

---

## Status

✅ **Production Ready**
- All core scripts tested
- Integration validated
- Ready for real-world HSB tests

---

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review `example_usage.py` for usage patterns
3. Run `python complete_walkthrough.py` to see the entire flow
4. Inspect the database: `python inspect_database.py`

