
# scripts/ingest_results.py
import json, sqlite3, pathlib
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

def ensure_schema(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS runs (
      run_id TEXT PRIMARY KEY, timestamp TEXT, git_sha TEXT, branch TEXT,
      orin_image TEXT, fpga_bitstream TEXT, dataset TEXT, operator_graph_version TEXT, notes TEXT
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

def ingest_run(run_dir: str, conn):
    run = pathlib.Path(run_dir)
    run_id = run.name
    # Minimal run metadata
    meta = {"run_id": run_id, "timestamp": datetime.now(timezone.utc).isoformat()}
    # Load summary.json if present
    summary = {}
    if (run / "summary.json").exists():
        summary = json.loads((run / "summary.json").read_text())

    conn.execute("""INSERT OR REPLACE INTO runs(run_id, timestamp, git_sha, branch,
                    orin_image, fpga_bitstream, dataset, operator_graph_version, notes)
                    VALUES(?,?,?,?,?,?,?,?,?)""",
                 (run_id, meta["timestamp"],
                  summary.get("git_sha"), summary.get("branch"),
                  summary.get("orin_image"), summary.get("fpga_bitstream"),
                  summary.get("dataset"), summary.get("operator_graph_version"),
                  summary.get("notes")))
    # Parse JUnit
    junit = run / "junit.xml"
    if junit.exists():
        tree = ET.parse(junit)
        for case in tree.findall(".//testcase"):
            name = case.attrib.get("classname", "") + "::" + case.attrib.get("name", "")
            duration = float(case.attrib.get("time", 0.0)) * 1000
            failure = case.find("failure")
            status = "fail" if failure is not None else "pass"
            err = failure.attrib.get("message", "") if failure is not None else None
            conn.execute("""INSERT INTO tests(run_id,name,status,duration_ms,category,tags,error_message)
                            VALUES(?,?,?,?,?,?,?)""",
                         (run_id, name, status, duration, None, None, err))
    # Store run-level metrics
    for k, v in summary.get("metrics", {}).items():
        conn.execute("""INSERT INTO metrics(run_id,test_id,name,value,unit,scope,meta)
                        VALUES(?,?,?,?,?,?,?)""",
                     (run_id, None, k, v["value"], v.get("unit"), "run", json.dumps(v.get("meta", {}))))
    conn.commit()

if __name__ == "__main__":
    import sys
    db = sqlite3.connect("db/results.sqlite")
    ensure_schema(db)
    for rd in sys.argv[1:]:
        ingest_run(rd, db)
    db.close()
