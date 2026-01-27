# HSB Test Framework: JSON Helper v2.0

**Everything you need to run tests and view results in a dashboard.**

---

## Quick Start (60 seconds)

```bash
# 1. Run test (creates JSON)
python my_test.py

# 2. Setup database (one-time)
python init_sql.py

# 3. Ingest results
python ingestion_script.py results/

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
Your Test Script (my_test.py)
    ↓ uses json_helper_v2
JSON Report (results/summary.json)
    ↓ ingested by
SQLite Database (db/results.sqlite)
    ↓ queried by
Streamlit Dashboard (http://localhost:8501)
    ↓
Your Web Browser
```

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

### Single Test

```bash
python my_test.py
python ingestion_script.py results/
```

Dashboard shows:
- Total Tests: 1
- Status: pass/fail
- Metrics and artifacts

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
python my_test.py
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

---

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
- **Artifacts:** PNG images, plots, histograms

---

## Common Workflows

### Workflow A: Debug Single Test
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

```python
report.finalize(metric_registry=None)  # Calculates summary stats
```

### report.write()

```python
report.write(Path("results"))  # Writes JSON to results/summary.json
```

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

