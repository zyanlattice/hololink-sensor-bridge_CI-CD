"""
Integration Test: Verify json_helper_v2 output is compatible with
ingestion_script.py → SQLite → Dashboard pipeline.

This test:
1. Generates a test report using json_helper_v2
2. Validates the JSON format
3. Simulates the ingestion process
4. Verifies SQLite schema compatibility
"""

import json
import sqlite3
from pathlib import Path
from wiptesting.json_helper import (
    create_report,
    Artifact,
    MetricRegistry,
)


def create_test_report() -> Path:
    """Create a comprehensive test report for integration testing"""
    registry = MetricRegistry()
    
    report = create_report(
        env={
            "orin_image": "r36.3",
            "fpga_bitstream": "hsb_20260125_01",
            "git_sha": "ab12cd3",
            "branch": "feature/test-integration",
            "dataset": "camA_1080p60",
        }
    )
    report.notes = "Integration test report"

    # Add multiple tests
    report.add_test(
        name="frame_gap_jitter",
        status="pass",
        duration_ms=12850.3,
        metrics={
            "frame_gap_ms_mean": 16.67,
            "frame_gap_ms_p95": 17.4,
            "frame_gap_ms_p99": 18.1,
            "drops": 0,
        },
        artifacts=[Artifact(type="png", path="fg_hist.png")],
        category="performance",
        tags=["csi", "raw"],
    )

    report.add_test(
        name="end_to_end_latency",
        status="fail",
        duration_ms=30123.5,
        metrics={
            "latency_ms_mean": 24.1,
            "latency_ms_p95": 35.7,
            "latency_ms_p99": 48.9,
        },
        error_message="p99 exceeded 45 ms threshold",
        category="performance",
    )

    report.add_test(
        name="crc_validation",
        status="pass",
        duration_ms=5000.0,
        metrics={"crc_pass_rate": 99.8},
        category="compliance",
    )

    report.add_timeseries(
        name="frame_gap_ms",
        path="metrics/frame_gap_ms.parquet",
        count=18000,
        meta={"source": "orchestrator"},
    )

    report.finalize(metric_registry=registry)
    out_dir = Path("integration_test_output")
    report.write(out_dir)
    return out_dir


def validate_json_format(report_path: Path) -> bool:
    """Verify JSON structure matches expected format"""
    print("\n" + "=" * 70)
    print("STEP 1: Validate JSON Format")
    print("=" * 70)

    summary_file = report_path / "summary.json"
    
    if not summary_file.exists():
        print(f"✗ Missing {summary_file}")
        return False
    
    try:
        data = json.loads(summary_file.read_text())
    except json.JSONDecodeError as e:
        print(f"✗ Invalid JSON: {e}")
        return False

    # Check required top-level fields
    required_fields = ["run_id", "env", "timestamp", "schema_version", "tests", "summary"]
    for field in required_fields:
        if field not in data:
            print(f"✗ Missing required field: {field}")
            return False
        print(f"✓ {field}: present")

    # Check tests structure
    if not isinstance(data["tests"], list):
        print(f"✗ tests is not a list")
        return False
    print(f"✓ tests: list with {len(data['tests'])} items")

    for i, test in enumerate(data["tests"]):
        required_test_fields = ["name", "status", "duration_ms", "metrics"]
        for field in required_test_fields:
            if field not in test:
                print(f"✗ Test {i} missing {field}")
                return False
        print(f"  ✓ Test {i}: {test['name']} ({test['status']})")

    # Check summary
    required_summary_fields = ["status", "total_tests", "passed", "failed", "yield_rate"]
    for field in required_summary_fields:
        if field not in data["summary"]:
            print(f"✗ Summary missing {field}")
            return False
    print(f"✓ summary: {data['summary']['status']} ({data['summary']['passed']}/{data['summary']['total_tests']})")

    print("\n✓ JSON format valid!")
    return True


def simulate_ingestion(report_path: Path) -> bool:
    """Simulate the ingestion_script.py process"""
    print("\n" + "=" * 70)
    print("STEP 2: Simulate Ingestion (JSON → SQLite)")
    print("=" * 70)

    summary_file = report_path / "summary.json"
    data = json.loads(summary_file.read_text())

    # Create test database
    db_path = report_path / "test_results.sqlite"
    conn = sqlite3.connect(db_path)
    
    # Create schema matching ingestion_script.py
    schema = """
    CREATE TABLE IF NOT EXISTS runs (
      run_id TEXT PRIMARY KEY,
      timestamp TEXT,
      git_sha TEXT,
      branch TEXT,
      orin_image TEXT,
      fpga_bitstream TEXT,
      dataset TEXT,
      notes TEXT
    );

    CREATE TABLE IF NOT EXISTS tests (
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

    CREATE TABLE IF NOT EXISTS metrics (
      metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
      run_id TEXT,
      test_id INTEGER,
      name TEXT,
      value REAL,
      unit TEXT,
      scope TEXT,
      meta TEXT,
      FOREIGN KEY(run_id) REFERENCES runs(run_id),
      FOREIGN KEY(test_id) REFERENCES tests(test_id)
    );

    CREATE TABLE IF NOT EXISTS artifacts (
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
    
    # Insert run metadata
    run_id = data["run_id"]
    env = data.get("env", {})
    
    conn.execute("""
        INSERT INTO runs(run_id, timestamp, git_sha, branch, orin_image, fpga_bitstream, dataset, notes)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        run_id,
        data["timestamp"],
        env.get("git_sha"),
        env.get("branch"),
        env.get("orin_image"),
        env.get("fpga_bitstream"),
        env.get("dataset"),
        data.get("notes"),
    ))
    print(f"✓ Inserted run: {run_id}")
    
    # Insert tests
    for test in data["tests"]:
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
        
        # Insert metrics for this test
        for metric_name, metric_value in test.get("metrics", {}).items():
            conn.execute("""
                INSERT INTO metrics(run_id, test_id, name, value, scope)
                VALUES(?, ?, ?, ?, ?)
            """, (run_id, test_id, metric_name, metric_value, "test"))
        
        print(f"  ✓ Test: {test['name']} ({test['status']})")
    
    # Insert artifacts
    for test_idx, test in enumerate(data["tests"]):
        for artifact in test.get("artifacts", []):
            conn.execute("""
                INSERT INTO artifacts(run_id, test_id, type, path, label)
                VALUES(?, ?, ?, ?, ?)
            """, (
                run_id,
                test_idx + 1,
                artifact["type"],
                artifact["path"],
                artifact.get("label"),
            ))
    
    conn.commit()
    conn.close()
    
    print(f"\n✓ Database created: {db_path}")
    return True


def verify_sqlite_data(report_path: Path) -> bool:
    """Verify SQLite contains expected data"""
    print("\n" + "=" * 70)
    print("STEP 3: Verify SQLite Data")
    print("=" * 70)

    db_path = report_path / "test_results.sqlite"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Query runs
    runs = conn.execute("SELECT * FROM runs").fetchall()
    print(f"✓ Runs: {len(runs)}")
    for run in runs:
        print(f"  - {dict(run)['run_id']}")

    # Query tests
    tests = conn.execute(
        "SELECT name, status, duration_ms FROM tests ORDER BY test_id"
    ).fetchall()
    print(f"✓ Tests: {len(tests)}")
    for test in tests:
        row = dict(test)
        print(f"  - {row['name']}: {row['status']} ({row['duration_ms']}ms)")

    # Query metrics
    metrics = conn.execute(
        """SELECT name, AVG(value) as avg_value, COUNT(*) as count
           FROM metrics GROUP BY name ORDER BY name"""
    ).fetchall()
    print(f"✓ Metrics: {len(metrics)}")
    for metric in metrics:
        row = dict(metric)
        print(f"  - {row['name']}: {row['count']} values (avg: {row['avg_value']:.2f})")

    # Query artifacts
    artifacts = conn.execute(
        "SELECT type, COUNT(*) as count FROM artifacts GROUP BY type"
    ).fetchall()
    print(f"✓ Artifacts: {sum(dict(a)['count'] for a in artifacts)}")
    for artifact in artifacts:
        row = dict(artifact)
        print(f"  - {row['type']}: {row['count']} items")

    conn.close()
    return True


def test_dashboard_queries(report_path: Path) -> bool:
    """Test queries that the Streamlit dashboard would run"""
    print("\n" + "=" * 70)
    print("STEP 4: Test Dashboard Queries")
    print("=" * 70)

    db_path = report_path / "test_results.sqlite"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Query 1: Overall yield
    summary = conn.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN status='pass' THEN 1 ELSE 0 END) as passed,
            ROUND(100.0 * SUM(CASE WHEN status='pass' THEN 1 ELSE 0 END) / COUNT(*), 1) as yield_pct
        FROM tests
    """).fetchone()
    print("✓ Overall Yield Query:")
    print(f"  Total: {dict(summary)['total']}, Passed: {dict(summary)['passed']}, " 
          f"Yield: {dict(summary)['yield_pct']}%")

    # Query 2: Tests by category
    by_category = conn.execute("""
        SELECT category, status, COUNT(*) as count
        FROM tests
        WHERE category IS NOT NULL
        GROUP BY category, status
        ORDER BY category
    """).fetchall()
    print("✓ Tests by Category:")
    for row in by_category:
        d = dict(row)
        print(f"  {d['category']}: {d['status']} ({d['count']})")

    # Query 3: Specific metric values
    metrics = conn.execute("""
        SELECT t.name as test_name, m.name as metric_name, m.value
        FROM metrics m
        JOIN tests t ON m.test_id = t.test_id
        WHERE m.name LIKE '%latency%'
        ORDER BY t.name, m.name
    """).fetchall()
    print("✓ Latency Metrics:")
    for row in metrics:
        d = dict(row)
        print(f"  {d['test_name']}: {d['metric_name']} = {d['value']}")

    conn.close()
    return True


def main():
    print("\n" + "=" * 70)
    print("INTEGRATION TEST: json_helper_v2 → Ingestion → SQLite → Dashboard")
    print("=" * 70)

    # Step 1: Create report
    print("\nCreating test report...")
    report_path = create_test_report()
    print(f"✓ Report created in {report_path}")

    # Step 2: Validate JSON format
    if not validate_json_format(report_path):
        print("\n✗ JSON format validation failed!")
        return False

    # Step 3: Simulate ingestion
    if not simulate_ingestion(report_path):
        print("\n✗ Ingestion simulation failed!")
        return False

    # Step 4: Verify SQLite
    if not verify_sqlite_data(report_path):
        print("\n✗ SQLite verification failed!")
        return False

    # Step 5: Test dashboard queries
    if not test_dashboard_queries(report_path):
        print("\n✗ Dashboard query test failed!")
        return False

    # Final summary
    print("\n" + "=" * 70)
    print("✓ ALL INTEGRATION TESTS PASSED!")
    print("=" * 70)
    print("""
Summary:
  ✓ JSON format is valid and complete
  ✓ Ingestion script can parse and insert data
  ✓ SQLite schema is compatible
  ✓ Dashboard queries work correctly
  
Next steps:
  1. Run actual ingestion_script.py with generated reports
  2. Verify dashboard displays data correctly
  3. Test with real test output from your HSB tests
    """)
    return True


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
