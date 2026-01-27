# JSON Helper v2.0 - Quick Reference Card

## One-Liner
```python
from json_helper_v2 import create_report; r = create_report(); r.add_test(...); r.finalize(); r.write(Path("out"))
```

## Basic Template
```python
from pathlib import Path
from json_helper_v2 import create_report, Artifact

# Create
report = create_report(
    env={
        "orin_image": "r36.3",
        "fpga_bitstream": "hsb_20250125_01",
        "git_sha": "abc123",
        "branch": "main",
        "dataset": "camA_1080p60",
    }
)

# Add tests
report.add_test(
    name="test_name",
    status="pass",  # or "fail", "skip", "partial"
    duration_ms=1000.0,
    metrics={"metric1": 42.5, "metric2": 100},
    error_message=None,  # Set if status="fail"
    artifacts=[Artifact(type="png", path="plot.png", label="Plot")],
    category="performance",  # Group for dashboard
    tags=["csi", "raw"],     # Filter tags
)

# Finalize & write
report.finalize()
report.write(Path("results"))  # Creates results/summary.json
```

## Common Patterns

### Single Test (Current Usage)
```python
report.add_test("test", "pass", 1000, metrics={"metric": 1.5})
```

### Multiple Tests (Suite)
```python
for test_name, metrics, duration in test_list:
    report.add_test(name=test_name, status="pass" if metrics["valid"] else "fail", 
                    duration_ms=duration, metrics=metrics)
```

### With Artifacts
```python
report.add_test(..., artifacts=[
    Artifact(type="png", path="plot.png", label="Result Plot"),
    Artifact(type="log", path="test.log", label="Test Log"),
])
```

### With Timeseries
```python
report.add_timeseries("metric_name", "metrics/data.parquet", count=18000, 
                      meta={"unit": "ms"})
```

### With Categories & Tags
```python
report.add_test(..., category="performance", tags=["csi", "1080p60", "raw"])
```

## Test Status Values
- `"pass"` → Test succeeded
- `"fail"` → Test failed (set error_message)
- `"skip"` → Test skipped
- `"partial"` → Some sub-tests passed, some failed

## Common Categories
- `"performance"` - frame_gap, latency, throughput
- `"compliance"` - CRC, data integrity
- `"stability"` - long-running tests
- `"networking"` - Ethernet, PTP
- `"resource-monitoring"` - power, thermal, memory

## Common Artifact Types
```
"log"     → text log files
"png"     → images/plots
"mp4"     → video
"json"    → JSON data
"parquet" → columnar data (recommended for large datasets)
"csv"     → tabular data
```

## After Finalize: Auto-Calculated Fields
```python
report.summary = {
    "status": "pass|fail|partial|skip",
    "total_tests": int,
    "passed": int,
    "failed": int,
    "skipped": int,
    "yield_rate": float (0.0-1.0),
}
```

## Validate Metrics (Optional)
```python
from json_helper_v2 import MetricRegistry

registry = MetricRegistry()  # Pre-registers common metrics
registry.register("my_metric", unit="units", scope="test", 
                  description="My metric")

report.finalize(metric_registry=registry)  # Will validate
```

## Environment Fields (All Optional)
```python
env={
    "orin_image": "r36.3",           # Jetson Orin image version
    "fpga_bitstream": "hsb_20250125", # FPGA bitstream version
    "git_sha": "abc123",              # Git commit
    "branch": "main",                 # Git branch
    "dataset": "camA_1080p60",        # Test dataset
    "operator_graph_version": "1.2.3", # GXF version (optional)
    # Custom fields allowed
}
```

## Output Structure
```json
{
  "run_id": "2026-01-26_13-05-17_abc123",
  "timestamp": "2026-01-26T13:05:17Z",
  "schema_version": "2.0",
  "env": {...},
  "tests": [
    {
      "name": "test_name",
      "status": "pass",
      "duration_ms": 1000.0,
      "metrics": {...},
      "error_message": null,
      "artifacts": [...],
      "category": "performance",
      "tags": [...]
    }
  ],
  "summary": {
    "status": "pass",
    "total_tests": 1,
    "passed": 1,
    "failed": 0,
    "skipped": 0,
    "yield_rate": 1.0
  },
  "timeseries": [...]
}
```

## Scaling to New Metrics
**No code changes needed!** Just add to metrics dict:

```python
# Current test
report.add_test(..., metrics={
    "frame_gap_ms_p99": 18.1,
    "drops": 0,
})

# Add power monitoring (future)
report.add_test(..., metrics={
    "frame_gap_ms_p99": 18.1,
    "drops": 0,
    "power_avg_w": 18.5,      # NEW
    "temp_max_c": 68.4,       # NEW
})

# Add network metrics (future)
report.add_test(..., metrics={
    "frame_gap_ms_p99": 18.1,
    "drops": 0,
    "power_avg_w": 18.5,
    "temp_max_c": 68.4,
    "packet_loss_pct": 0.5,   # NEW
})
```

## Integration Pipeline
```
json_helper_v2 ──→ summary.json ──→ ingestion_script.py ──→ SQLite
                                                           │
                                                    runs, tests,
                                                    metrics tables
                                                           │
                                                    dashboard.py
                                                           │
                                                    Browser
```

## Dashboard-Ready Fields
- `run_id` → Run identifier & grouping
- `timestamp` → Sorting & trending
- `env.fpga_bitstream`, `env.orin_image` → Filtering & comparison
- `tests[].name` → Test identification
- `tests[].status` → Pass/fail coloring
- `tests[].metrics` → Values for charts
- `tests[].category` → Dashboard grouping
- `tests[].tags` → Detailed filtering
- `summary.yield_rate` → KPI cards & trending

## Common Mistakes to Avoid
❌ Forgetting `finalize()`
✅ Always call `report.finalize()` before `write()`

❌ Invalid status value
✅ Use only: "pass", "fail", "skip", "partial"

❌ No error message on failure
✅ Set `error_message="reason"` when status="fail"

❌ Path starting with `/` or `C:\`
✅ Use relative paths: `"frames/plot.png"` not `/tmp/plot.png`

❌ Not using Path object
✅ Always use `Path("results")` for write()

❌ Inconsistent metric names
✅ Use consistent names across runs (lowercase, underscores)

## File Locations
- `json_helper_v2.py` - Core library
- `example_usage.py` - 4 usage patterns
- `test_integration.py` - E2E validation
- `JSON_HELPER_V2_GUIDE.py` - Full user guide
- `README_JSON_HELPER_V2.md` - Implementation summary

## See Also
- `JSON_HELPER_V2_GUIDE.py` - Complete documentation (600+ lines)
- `example_usage.py` - 4 working patterns (400+ lines)
- `test_integration.py` - Full integration test (300+ lines)
- `sample.json` - Example output format
