
# scripts/ingest_results.py
"""
Flexible ingestion script that handles:
1. Direct JSON file path (structured_report.json)
2. Directory path (searches for structured_report.json, test_results.json, or legacy format)
"""
import json, sqlite3, pathlib
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

def ensure_schema(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS runs (
      run_id TEXT PRIMARY KEY, timestamp TEXT, git_sha TEXT, branch TEXT,
      orin_image TEXT, fpga_bitstream TEXT, dataset TEXT, operator_graph_version TEXT, notes TEXT,
      env TEXT, schema_version TEXT
    );
    CREATE TABLE IF NOT EXISTS tests (
      test_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, name TEXT,
      status TEXT, duration_ms REAL, category TEXT, tags TEXT, error_message TEXT
    );
    CREATE TABLE IF NOT EXISTS metrics (
      metric_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, test_id INTEGER,
      name TEXT, value REAL, unit TEXT, scope TEXT, meta TEXT
    );
    CREATE TABLE IF NOT EXISTS artifacts (
      artifact_id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, test_id INTEGER,
      type TEXT, path TEXT, label TEXT
    );
    """)
    conn.commit()

def ingest_structured_report(json_path: pathlib.Path, conn):
    """Ingest new structured_report.json format"""
    data = json.loads(json_path.read_text())
    
    run_id = data.get("run_id", json_path.stem)
    timestamp = data.get("timestamp", datetime.now(timezone.utc).isoformat())
    env = data.get("env", {})
    
    # Insert run metadata
    conn.execute("""INSERT OR REPLACE INTO runs(
                    run_id, timestamp, git_sha, branch, orin_image, fpga_bitstream,
                    dataset, operator_graph_version, notes, env, schema_version)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                 (run_id, timestamp,
                  env.get("git_sha"), env.get("branch"),
                  env.get("host_platform"), env.get("bitstream_version"),
                  None, env.get("operator_graph_version"),
                  data.get("notes"),
                  json.dumps(env),
                  data.get("schema_version")))
    
    # Insert tests
    for test in data.get("tests", []):
        cursor = conn.execute("""INSERT INTO tests(
                                 run_id, name, status, duration_ms, category, tags, error_message)
                                 VALUES(?,?,?,?,?,?,?)""",
                             (run_id,
                              test.get("name"),
                              test.get("status"),
                              test.get("duration_ms", 0.0),
                              test.get("category"),
                              json.dumps(test.get("tags", [])),
                              test.get("error_message")))
        
        test_id = cursor.lastrowid
        
        # Insert test-level metrics
        for metric_name, metric_value in test.get("metrics", {}).items():
            if isinstance(metric_value, dict):
                conn.execute("""INSERT INTO metrics(
                                run_id, test_id, name, value, unit, scope, meta)
                                VALUES(?,?,?,?,?,?,?)""",
                           (run_id, test_id, metric_name,
                            metric_value.get("value"), metric_value.get("unit"),
                            "test", json.dumps(metric_value)))
            elif isinstance(metric_value, (list, tuple)):
                # Store list/array as JSON in meta, use first value or None for value column
                first_val = metric_value[0] if metric_value else None
                conn.execute("""INSERT INTO metrics(
                                run_id, test_id, name, value, unit, scope, meta)
                                VALUES(?,?,?,?,?,?,?)""",
                           (run_id, test_id, metric_name, first_val,
                            None, "test", json.dumps({"array": metric_value})))
            else:
                # Simple scalar value
                conn.execute("""INSERT INTO metrics(
                                run_id, test_id, name, value, unit, scope, meta)
                                VALUES(?,?,?,?,?,?,?)""",
                           (run_id, test_id, metric_name, metric_value,
                            None, "test", None))
        
        # Insert artifacts
        for artifact in test.get("artifacts", []):
            conn.execute("""INSERT INTO artifacts(
                            run_id, test_id, type, path, label)
                            VALUES(?,?,?,?,?)""",
                       (run_id, test_id,
                        artifact.get("type"),
                        artifact.get("path"),
                        artifact.get("label")))
    
    conn.commit()
    print(f"✓ Ingested structured report: {run_id} ({len(data.get('tests', []))} tests)")

def ingest_legacy_run(run_dir: pathlib.Path, conn):
    """Ingest legacy summary.json + junit.xml format"""
    run_id = run_dir.name
    meta = {"run_id": run_id, "timestamp": datetime.now(timezone.utc).isoformat()}
    
    # Load summary.json if present
    summary = {}
    if (run_dir / "summary.json").exists():
        summary = json.loads((run_dir / "summary.json").read_text())

    conn.execute("""INSERT OR REPLACE INTO runs(
                    run_id, timestamp, git_sha, branch, orin_image, fpga_bitstream,
                    dataset, operator_graph_version, notes, env, schema_version)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                 (run_id, meta["timestamp"],
                  summary.get("git_sha"), summary.get("branch"),
                  summary.get("orin_image"), summary.get("fpga_bitstream"),
                  summary.get("dataset"), summary.get("operator_graph_version"),
                  summary.get("notes"), None, "legacy"))
    
    # Parse JUnit
    junit = run_dir / "junit.xml"
    if junit.exists():
        tree = ET.parse(junit)
        for case in tree.findall(".//testcase"):
            name = case.attrib.get("classname", "") + "::" + case.attrib.get("name", "")
            duration = float(case.attrib.get("time", 0.0)) * 1000
            failure = case.find("failure")
            status = "fail" if failure is not None else "pass"
            err = failure.attrib.get("message", "") if failure is not None else None
            conn.execute("""INSERT INTO tests(
                            run_id, name, status, duration_ms, category, tags, error_message)
                            VALUES(?,?,?,?,?,?,?)""",
                         (run_id, name, status, duration, None, None, err))
    
    # Store run-level metrics
    for k, v in summary.get("metrics", {}).items():
        conn.execute("""INSERT INTO metrics(
                        run_id, test_id, name, value, unit, scope, meta)
                        VALUES(?,?,?,?,?,?,?)""",
                     (run_id, None, k, v["value"], v.get("unit"), "run",
                      json.dumps(v.get("meta", {}))))
    
    conn.commit()
    print(f"✓ Ingested legacy run: {run_id}")

def ingest_path(path_str: str, conn):
    """
    Flexible ingestion that handles:
    - Direct JSON file path (test_results.json or test_results_*.json)
    - Directory path (searches for test_results.json first, then legacy format)
    """
    path = pathlib.Path(path_str)
    
    if not path.exists():
        print(f"✗ Path does not exist: {path}")
        return
    
    # Case 1: Direct JSON file
    if path.is_file() and path.suffix == ".json":
        # Check for structured format (not "simple" variant)
        if "test_results" in path.name and "simple" not in path.name:
            ingest_structured_report(path, conn)
        elif "test_results_simple" in path.name:
            print(f"⚠ test_results_simple.json format is a backup only, using structured version instead")
        else:
            print(f"⚠ Unknown JSON format: {path.name}")
        return
    
    # Case 2: Directory - search for JSON files
    if path.is_dir():
        # Priority 1: test_results.json (non-simple variant)
        test_results = path / "test_results.json"
        if test_results.exists():
            ingest_structured_report(test_results, conn)
            return
        
        # Priority 2: Look for test_results_*.json (excluding simple variant)
        test_result_files = [f for f in path.glob("test_results_*.json") if "simple" not in f.name]
        if test_result_files:
            for report in test_result_files:
                ingest_structured_report(report, conn)
            return
        
        # Priority 3: Look in subdirectories for test_results_*.json
        test_result_files = [f for f in path.glob("**/test_results_*.json") if "simple" not in f.name]
        if test_result_files:
            for report in test_result_files:
                ingest_structured_report(report, conn)
            return
        
        # Priority 4: Legacy format (summary.json + junit.xml)
        if (path / "summary.json").exists() or (path / "junit.xml").exists():
            ingest_legacy_run(path, conn)
            return
        
        print(f"⚠ No recognized test results found in: {path}")
        return
    
    print(f"✗ Invalid path type: {path}")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python ingestion_script.py <path1> [path2] ...")
        print("  Supports:")
        print("    - Direct JSON file: test_results_YYYYMMDD_HHMMSS.json")
        print("    - Directory with test_results_*.json")
        print("    - Directory with legacy summary.json + junit.xml")
        sys.exit(1)
    
    db = sqlite3.connect("db/results.sqlite")
    ensure_schema(db)
    
    for path_str in sys.argv[1:]:
        print(f"\nProcessing: {path_str}")
        ingest_path(path_str, db)
    
    db.close()
    print("\n✓ Ingestion complete")
