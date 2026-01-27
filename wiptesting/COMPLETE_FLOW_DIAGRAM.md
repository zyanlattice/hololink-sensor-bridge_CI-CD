# Complete Data Flow Visualization

## The Journey of Your Test Data: From Test to Dashboard

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│                         YOUR TEST SCRIPT                                    │
│                     (your_test.py or similar)                              │
│                                                                             │
│    1. Run frame_gap_jitter test                                            │
│    2. Collect metrics:                                                     │
│       - frame_gap_ms_mean = 16.67                                          │
│       - frame_gap_ms_p95 = 17.4                                            │
│       - frame_gap_ms_p99 = 18.1                                            │
│       - drops = 0                                                          │
│    3. Determine status: "fail" (because p99 > 18.0)                        │
│                                                                             │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               │ calls
                               │
                               v
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│                         json_helper_v2.py                                   │
│                     (Generic Test Report Library)                          │
│                                                                             │
│    from json_helper_v2 import create_report, Artifact                     │
│                                                                             │
│    report = create_report(env={                                            │
│        "orin_image": "r36.3",                                              │
│        "fpga_bitstream": "hsb_20260125_01",                                │
│        "git_sha": "ab12cd3",                                               │
│        "branch": "main",                                                   │
│        "dataset": "camA_1080p60"                                           │
│    })                                                                       │
│                                                                             │
│    report.add_test(                                                        │
│        name="frame_gap_jitter",                                            │
│        status="fail",                                                      │
│        duration_ms=12000.0,                                                │
│        metrics={                                                           │
│            "frame_gap_ms_mean": 16.67,                                     │
│            "frame_gap_ms_p95": 17.4,                                       │
│            "frame_gap_ms_p99": 18.1,                                       │
│            "drops": 0                                                      │
│        },                                                                  │
│        artifacts=[Artifact(type="png", path="histogram.png")],            │
│        category="performance",                                             │
│        tags=["csi", "raw"]                                                │
│    )                                                                        │
│                                                                             │
│    report.finalize()                 # Calculates summary                 │
│    report.write(Path("results"))     # Saves JSON file                    │
│                                                                             │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               │ creates
                               │
                               v
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│                    example_pattern1/summary.json                           │
│                    (1,320 bytes JSON file)                                 │
│                                                                             │
│    {                                                                       │
│      "run_id": "2026-01-26_17-37-35_local",                               │
│      "timestamp": "2026-01-26T09:37:35.863147+00:00",                     │
│      "env": {                                                              │
│        "orin_image": "r36.3",                                              │
│        "fpga_bitstream": "hsb_20260125_01",                                │
│        "git_sha": "ab12cd3",                                               │
│        "branch": "main",                                                   │
│        "dataset": "camA_1080p60"                                           │
│      },                                                                    │
│      "tests": [                                                            │
│        {                                                                   │
│          "name": "frame_gap_jitter",                                       │
│          "status": "fail",                                                 │
│          "duration_ms": 12000.0,                                           │
│          "metrics": {                                                      │
│            "frame_gap_ms_mean": 16.67,                                     │
│            "frame_gap_ms_p95": 17.4,                                       │
│            "frame_gap_ms_p99": 18.1,                                       │
│            "drops": 0                                                      │
│          },                                                                │
│          "category": "performance",                                        │
│          "tags": ["csi", "raw"]                                            │
│        }                                                                   │
│      ],                                                                    │
│      "summary": {                                                          │
│        "status": "fail",                                                   │
│        "total_tests": 1,                                                   │
│        "passed": 0,                                                        │
│        "failed": 1,                                                        │
│        "yield_rate": 0.0                                                   │
│      }                                                                     │
│    }                                                                       │
│                                                                             │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               │ ingestion_script.py reads
                               │
                               v
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│                    ingestion_script.py                                     │
│            (JSON to SQLite Conversion Script)                             │
│                                                                             │
│    import json                                                             │
│    conn = sqlite3.connect("db/results.sqlite")                             │
│                                                                             │
│    # Parse JSON                                                            │
│    data = json.load(summary.json)                                          │
│                                                                             │
│    # Insert into runs table                                               │
│    conn.execute("INSERT INTO runs VALUES (...)")                           │
│                                                                             │
│    # Insert into tests table                                              │
│    conn.execute("INSERT INTO tests VALUES (...)")                          │
│                                                                             │
│    # Extract metrics and insert                                           │
│    for metric_name, value in metrics.items():                              │
│        conn.execute("INSERT INTO metrics VALUES (...)")                    │
│                                                                             │
│    conn.commit()                                                           │
│                                                                             │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               │ populates
                               │
                               v
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│                    SQLite Database                                         │
│                 (db/results.sqlite file)                                   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────┐           │
│  │ RUNS TABLE                                                  │           │
│  ├─────────────────────────────────────────────────────────────┤           │
│  │ run_id         | 2026-01-26_17-37-35_local                  │           │
│  │ timestamp      | 2026-01-26T09:37:35.863147+00:00           │           │
│  │ orin_image     | r36.3                                       │           │
│  │ fpga_bitstream | hsb_20260125_01                             │           │
│  │ git_sha        | ab12cd3                                     │           │
│  │ branch         | main                                        │           │
│  └─────────────────────────────────────────────────────────────┘           │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────┐           │
│  │ TESTS TABLE                                                 │           │
│  ├─────────────────────────────────────────────────────────────┤           │
│  │ test_id | name                | status | duration_ms       │           │
│  │    1    | frame_gap_jitter     | fail   | 12000.0          │           │
│  └─────────────────────────────────────────────────────────────┘           │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────┐           │
│  │ METRICS TABLE                                               │           │
│  ├─────────────────────────────────────────────────────────────┤           │
│  │ metric_id | test_id | name                 | value          │           │
│  │    1      |    1    | frame_gap_ms_mean    | 16.67          │           │
│  │    2      |    1    | frame_gap_ms_p95     | 17.4           │           │
│  │    3      |    1    | frame_gap_ms_p99     | 18.1           │           │
│  │    4      |    1    | drops                | 0              │           │
│  └─────────────────────────────────────────────────────────────┘           │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────┐           │
│  │ ARTIFACTS TABLE                                             │           │
│  ├─────────────────────────────────────────────────────────────┤           │
│  │ artifact_id | test_id | type | path                         │           │
│  │     1       |    1    | png  | frames/histogram.png         │           │
│  └─────────────────────────────────────────────────────────────┘           │
│                                                                             │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               │ local_browser_dashboard.py
                               │ queries using SQL
                               │
                               v
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│                 local_browser_dashboard.py                                 │
│           (Streamlit Dashboard Application)                               │
│                                                                             │
│    import streamlit as st                                                  │
│    import sqlite3                                                          │
│                                                                             │
│    # Query 1: KPI metrics                                                  │
│    SELECT COUNT(*) as total, SUM(CASE WHEN status='pass'...) as passed     │
│                                                                             │
│    # Query 2: Test details                                                 │
│    SELECT name, status, duration_ms, category FROM tests                   │
│                                                                             │
│    # Query 3: Metric values                                                │
│    SELECT m.name, m.value FROM metrics m JOIN tests t ON ...               │
│                                                                             │
│    # Query 4: Run information                                              │
│    SELECT * FROM runs WHERE run_id = ?                                     │
│                                                                             │
│    # Format for Streamlit display                                          │
│    st.metric("Total Tests", 1)                                             │
│    st.metric("Passed", 0)                                                  │
│    st.metric("Failed", 1)                                                  │
│    st.metric("Yield Rate", "0.0%")                                         │
│                                                                             │
│    st.dataframe(test_results)                                              │
│    st.plotly_chart(yield_trend)                                            │
│                                                                             │
└──────────────────────────────┬──────────────────────────────────────────────┘
                               │
                               │ renders
                               │
                               v
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│                      YOUR WEB BROWSER                                       │
│                  (http://localhost:8501)                                    │
│                                                                             │
│    ╔═════════════════════════════════════════════════════════════════╗    │
│    ║              HSB Test Dashboard                                  ║    │
│    ╠═════════════════════════════════════════════════════════════════╣    │
│    ║                                                                 ║    │
│    ║  [KPI Cards]                                                   ║    │
│    ║  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────────┐                      ║    │
│    ║  │Total │ │Passed│ │Failed│ │  Yield  │                      ║    │
│    ║  │Tests │ │Tests │ │Tests │ │  Rate   │                      ║    │
│    ║  │  1   │ │  0   │ │  1   │ │  0.0%   │                      ║    │
│    ║  └──────┘ └──────┘ └──────┘ └──────────┘                      ║    │
│    ║                                                                 ║    │
│    ║  [Yield Over Time Chart]                                       ║    │
│    ║  Yield %                                                       ║    │
│    ║  100 +                                                         ║    │
│    ║      |                                                         ║    │
│    ║   50 +   *                                                     ║    │
│    ║      |                                                         ║    │
│    ║    0 +---+---+---+---+---+                                    ║    │
│    ║        J26 J27 J28 J29 J30                                    ║    │
│    ║                                                                 ║    │
│    ║  [Run Details]                                                 ║    │
│    ║  Run: 2026-01-26_17-37-35_local                               ║    │
│    ║  Image: r36.3                                                  ║    │
│    ║  Bitstream: hsb_20260125_01                                    ║    │
│    ║                                                                 ║    │
│    ║  [Test Results]                                                ║    │
│    ║  Name                Status    Duration    Category            ║    │
│    ║  frame_gap_jitter    FAIL      12000ms     performance        ║    │
│    ║                                                                 ║    │
│    ║  [Metrics]                                                     ║    │
│    ║  frame_gap_ms_mean: 16.67                                      ║    │
│    ║  frame_gap_ms_p95: 17.4                                        ║    │
│    ║  frame_gap_ms_p99: 18.1                                        ║    │
│    ║                                                                 ║    │
│    ║  [Artifacts]                                                   ║    │
│    ║  [Image] Frame Gap Distribution (histogram.png)                ║    │
│    ║                                                                 ║    │
│    ╚═════════════════════════════════════════════════════════════════╝    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## What You Need to Know

### Step-by-Step Summary

1. **Your Test Script** produces metrics
2. **json_helper_v2** converts metrics to JSON
3. **summary.json** is created (1.3 KB file)
4. **ingestion_script.py** reads JSON
5. **SQLite database** stores structured data
6. **Dashboard queries** the database
7. **Browser** displays the visualization

### Key Points

- **No manual data entry needed** - everything is automatic
- **JSON is the bridge** between your test and the database
- **Database normalizes the data** into separate tables
- **Dashboard just displays** what's in the database
- **All reversible** - you can query the database directly with SQL

### What Happens Automatically

```
json_helper_v2.report.write() 
    → Creates summary.json
    
ingestion_script.py 
    → Reads summary.json
    → Creates/updates SQLite database
    
local_browser_dashboard.py
    → Queries SQLite
    → Displays results
    
Browser
    → Shows dashboard
```

### No Code Needed After write()

Once you call `report.write(Path("results"))`, the rest happens automatically!

The ingestion pipeline reads the JSON and populates the database.
The dashboard automatically queries the database for visualization.

**That's it!** No manual steps, no data copy-paste, no configuration.

## Files Involved

- `example_pattern1/summary.json` - The test report (1.3 KB)
- `db/results.sqlite` - The database (created by ingestion)
- `local_browser_dashboard.py` - The dashboard (queries database)
- `complete_walkthrough.py` - Demo showing the entire flow
