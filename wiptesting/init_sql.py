
# scripts/init_db.py
import sqlite3, os
os.makedirs("db", exist_ok=True)

schema = """
PRAGMA journal_mode=WAL;

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
  error_message TEXT,
  tags TEXT,
  FOREIGN KEY(run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS metrics (
  metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT,
  test_id INTEGER,
  name TEXT,
  value REAL,
  unit TEXT,
  scope TEXT,           -- 'run' or 'test'
  meta TEXT,
  FOREIGN KEY(run_id) REFERENCES runs(run_id),
  FOREIGN KEY(test_id) REFERENCES tests(test_id)
);

CREATE TABLE IF NOT EXISTS artifacts (
  artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT,
  test_id INTEGER,
  type TEXT,          -- 'log','png','mp4','json','parquet'
  path TEXT,
  label TEXT,
  FOREIGN KEY(run_id) REFERENCES runs(run_id),
  FOREIGN KEY(test_id) REFERENCES tests(test_id)
);
"""

con = sqlite3.connect("db/results.sqlite")
con.executescript(schema)
con.commit()
con.close()
print("Initialized db/results.sqlite")
