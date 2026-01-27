#!/usr/bin/env python3
"""
COMPLETE WALKTHROUGH: JSON to SQLite to Dashboard

Shows the entire data flow from json_helper_v2 output through to dashboard
"""

import json
import sqlite3
from pathlib import Path

print("\n" + "="*80)
print("COMPLETE DATA FLOW WALKTHROUGH: JSON -> SQLite -> Dashboard")
print("="*80)

# STAGE 1: Read the JSON Report
print("\n\n[STAGE 1] JSON REPORT FROM json_helper_v2")
print("-"*80)

json_file = Path("example_pattern1/summary.json")
if not json_file.exists():
    print(f"ERROR: {json_file} not found")
    print("Run: python example_usage.py")
    exit(1)

json_data = json.loads(json_file.read_text())

print(f"File: {json_file}")
print(f"Size: {json_file.stat().st_size} bytes")
print(f"\nJSON contains:")
print(f"  - run_id: {json_data['run_id']}")
print(f"  - timestamp: {json_data['timestamp']}")
print(f"  - tests: {len(json_data['tests'])} test(s)")
print(f"  - summary.status: {json_data['summary']['status']}")
print(f"  - summary.yield_rate: {json_data['summary']['yield_rate']}")
print(f"\nFull JSON content:")
print("-"*80)
print(json.dumps(json_data, indent=2))
print("-"*80)


# STAGE 2: Ingestion - JSON to SQLite
print("\n\n[STAGE 2] INGESTION SCRIPT: JSON to SQLite")
print("-"*80)

print("What happens in ingestion_script.py:")
print("  1. Parse JSON file")
print("  2. Create SQLite tables (runs, tests, metrics, artifacts)")
print("  3. Insert run metadata")
print("  4. Insert test results")
print("  5. Extract and insert metrics")
print("  6. Store artifact references")

db_path = Path("walkthrough_demo.sqlite")
if db_path.exists():
    db_path.unlink()

conn = sqlite3.connect(db_path)

# Create schema
schema = """
CREATE TABLE runs (
  run_id TEXT PRIMARY KEY,
  timestamp TEXT,
  git_sha TEXT,
  branch TEXT,
  orin_image TEXT,
  fpga_bitstream TEXT,
  dataset TEXT,
  notes TEXT
);

CREATE TABLE tests (
  test_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT,
  name TEXT,
  status TEXT,
  duration_ms REAL,
  category TEXT,
  tags TEXT,
  error_message TEXT,
  FOREIGN KEY(run_id) REFERENCES runs(run_id)
);

CREATE TABLE metrics (
  metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT,
  test_id INTEGER,
  name TEXT,
  value REAL,
  unit TEXT,
  scope TEXT,
  FOREIGN KEY(run_id) REFERENCES runs(run_id),
  FOREIGN KEY(test_id) REFERENCES tests(test_id)
);

CREATE TABLE artifacts (
  artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT,
  test_id INTEGER,
  type TEXT,
  path TEXT,
  label TEXT,
  FOREIGN KEY(run_id) REFERENCES runs(run_id),
  FOREIGN KEY(test_id) REFERENCES tests(test_id)
);
"""

conn.executescript(schema)
print("\n[OK] Created tables: runs, tests, metrics, artifacts")

# Insert run data
run_id = json_data["run_id"]
env = json_data["env"]

print(f"\n[OK] Inserted run metadata:")
print(f"  - run_id: {run_id}")
print(f"  - orin_image: {env.get('orin_image')}")
print(f"  - fpga_bitstream: {env.get('fpga_bitstream')}")

conn.execute("""
    INSERT INTO runs(run_id, timestamp, git_sha, branch, orin_image, fpga_bitstream, dataset, notes)
    VALUES(?, ?, ?, ?, ?, ?, ?, ?)
""", (
    run_id,
    json_data["timestamp"],
    env.get("git_sha"),
    env.get("branch"),
    env.get("orin_image"),
    env.get("fpga_bitstream"),
    env.get("dataset"),
    json_data.get("notes"),
))

# Insert tests and metrics
print(f"\n[OK] Inserted tests and metrics:")
for test in json_data["tests"]:
    cursor = conn.execute("""
        INSERT INTO tests(run_id, name, status, duration_ms, category, tags, error_message)
        VALUES(?, ?, ?, ?, ?, ?, ?)
    """, (
        run_id,
        test["name"],
        test["status"],
        test["duration_ms"],
        test.get("category"),
        ",".join(test.get("tags", [])) or None,
        test.get("error_message"),
    ))
    test_id = cursor.lastrowid
    
    print(f"  Test: {test['name']} ({test['status']})")
    
    for metric_name, metric_value in test.get("metrics", {}).items():
        print(f"    - {metric_name} = {metric_value}")
        conn.execute("""
            INSERT INTO metrics(run_id, test_id, name, value, scope)
            VALUES(?, ?, ?, ?, ?)
        """, (run_id, test_id, metric_name, metric_value, "test"))
    
    for artifact in test.get("artifacts", []):
        conn.execute("""
            INSERT INTO artifacts(run_id, test_id, type, path, label)
            VALUES(?, ?, ?, ?, ?)
        """, (run_id, test_id, artifact["type"], artifact["path"], artifact.get("label")))

conn.commit()
print(f"\n[OK] Database saved: {db_path}")


# STAGE 3: View the Database
print("\n\n[STAGE 3] VIEW SQLITE DATABASE CONTENTS")
print("-"*80)

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

print("\n[TABLE: runs]")
runs = conn.execute("SELECT * FROM runs").fetchall()
for run in runs:
    d = dict(run)
    print(f"  run_id: {d['run_id']}")
    print(f"  timestamp: {d['timestamp']}")
    print(f"  orin_image: {d['orin_image']}")
    print(f"  fpga_bitstream: {d['fpga_bitstream']}")
    print(f"  git_sha: {d['git_sha']}")

print("\n[TABLE: tests]")
tests = conn.execute("SELECT test_id, name, status, duration_ms, category FROM tests").fetchall()
for test in tests:
    d = dict(test)
    print(f"  {d['name']} (status={d['status']}, duration={d['duration_ms']}ms, category={d['category']})")

print("\n[TABLE: metrics]")
metrics = conn.execute("""
    SELECT m.name, m.value, t.name as test_name
    FROM metrics m JOIN tests t ON m.test_id = t.test_id
    ORDER BY t.name, m.name
""").fetchall()
for m in metrics:
    d = dict(m)
    print(f"  {d['test_name']}: {d['name']} = {d['value']}")

print("\n[TABLE: artifacts]")
artifacts = conn.execute("""
    SELECT a.type, a.path, t.name
    FROM artifacts a JOIN tests t ON a.test_id = t.test_id
""").fetchall()
for a in artifacts:
    d = dict(a)
    print(f"  {d['name']}: {d['type']} -> {d['path']}")


# STAGE 4: Dashboard Queries
print("\n\n[STAGE 4] DASHBOARD QUERIES")
print("-"*80)

# KPI query
print("\n[Query 1] KPI Summary:")
kpi = conn.execute("""
    SELECT 
        COUNT(*) as total_tests,
        SUM(CASE WHEN status='pass' THEN 1 ELSE 0 END) as passed,
        SUM(CASE WHEN status='fail' THEN 1 ELSE 0 END) as failed,
        ROUND(100.0 * SUM(CASE WHEN status='pass' THEN 1 ELSE 0 END) / COUNT(*), 1) as yield_pct
    FROM tests
""").fetchone()
d = dict(kpi)
print(f"  Total Tests: {d['total_tests']}")
print(f"  Passed: {d['passed']}")
print(f"  Failed: {d['failed']}")
print(f"  Yield: {d['yield_pct']}%")

# Test details
print("\n[Query 2] Test Results Table:")
tests = conn.execute("""
    SELECT name, status, duration_ms, category FROM tests ORDER BY test_id
""").fetchall()
for t in tests:
    d = dict(t)
    icon = "[PASS]" if d['status'] == 'pass' else "[FAIL]"
    print(f"  {icon} {d['name']:30s} {d['duration_ms']:8.1f}ms ({d['category']})")

# Metrics details
print("\n[Query 3] Metric Values:")
metrics = conn.execute("""
    SELECT t.name as test, m.name as metric, m.value
    FROM metrics m JOIN tests t ON m.test_id = t.test_id
    ORDER BY t.name, m.name
""").fetchall()
for m in metrics:
    d = dict(m)
    print(f"  {d['test']:25s} > {d['metric']:20s} = {d['value']}")

conn.close()


# STAGE 5: What the Dashboard Shows
print("\n\n[STAGE 5] STREAMLIT DASHBOARD VISUALIZATION")
print("-"*80)

print("""
In your web browser (localhost:8501), you would see:

+-- HSB Test Dashboard -----------------------------------+
|                                                         |
| [KPI Cards Row]                                         |
| +-------+  +-------+  +-------+  +-------+             |
| |Total  |  |Passed |  |Failed |  |Yield  |             |
| |Tests  |  |Tests  |  |Tests  |  |Rate   |             |
| |1      |  |0      |  |1      |  |0.0%   |             |
| +-------+  +-------+  +-------+  +-------+             |
|                                                         |
| [Line Chart: Yield Over Time]                           |
| Yield %                                                 |
| 100 |                                                   |
|  50 |    *                                              |
|   0 |----+----+----+----+                               |
|     Jan26 Jan27 Jan28 Jan29                             |
|                                                         |
| [Run Selector Dropdown]                                 |
| Select Run: [2026-01-26_17-37-35_local ▼]             |
|                                                         |
| [Test Results Table]                                    |
| Name                Status   Duration    Category       |
| frame_gap_jitter    FAIL     12000.0ms   performance   |
|                                                         |
| [Metrics Comparison]                                    |
| Select Metric: [frame_gap_ms_mean ▼]                  |
| (Shows value: 16.67)                                   |
|                                                         |
| [Artifacts]                                             |
| Images for frame_gap_jitter:                            |
|   - Frame Gap Distribution                              |
|     (frames/frame_gap_histogram.png)                    |
|                                                         |
+-------------------------------------------------+-------+
""")


# STAGE 6: Complete Summary
print("\n\n[STAGE 6] COMPLETE DATA FLOW SUMMARY")
print("-"*80)

print("""
HERE IS THE ENTIRE JOURNEY:

1. YOUR TEST SCRIPT
   - Runs the frame_gap_jitter test
   - Measures metrics (gap_ms_mean, p95, p99, drops)
   - Calls json_helper_v2

2. json_helper_v2 CREATES REPORT
   - report.add_test(name, status, metrics)
   - report.finalize() [calculates summary]
   - report.write() [saves example_pattern1/summary.json]

3. JSON REPORT IS CREATED
   - File: example_pattern1/summary.json
   - Contains: run_id, timestamp, tests, metrics, summary
   - Ready for ingestion!

4. ingestion_script.py PROCESSES JSON
   - Reads the JSON file
   - Creates SQLite database
   - Inserts all data into tables

5. SQLITE DATABASE STORES DATA
   - runs table (1 row): The test run metadata
   - tests table (1 row): The frame_gap_jitter test
   - metrics table (4 rows): Each metric (gap_mean, p95, p99, drops)
   - artifacts table (1 row): The histogram PNG reference

6. local_browser_dashboard.py QUERIES DATABASE
   - Query 1: COUNT(*) FROM tests -> 1
   - Query 2: SUM(CASE WHEN status='pass') -> 0
   - Query 3: ROUND(100 * passed / total) -> 0%
   - Shows test results, metrics, charts

7. YOUR BROWSER DISPLAYS DASHBOARD
   - KPI cards show: 1 total, 0 passed, 1 failed, 0% yield
   - Test table shows: frame_gap_jitter [FAIL]
   - Metric shows: frame_gap_ms_mean = 16.67
   - Image shows: Frame Gap Histogram

KEY INSIGHT:
    Once you run report.finalize() and report.write(),
    the rest is AUTOMATIC!
    
    JSON -> Database -> Dashboard
    
    No manual steps, no data entry, no copy-paste!
    All automatic ingestion!
""")

print(f"\nFiles in this demo:")
print(f"  - {db_path} (SQLite database)")
print(f"  - example_pattern1/summary.json (JSON report)")
print("\nYou can inspect the database:")
print(f"  sqlite3 {db_path}")
print("\nOr view the JSON:")
print(f"  cat example_pattern1/summary.json | python -m json.tool")
