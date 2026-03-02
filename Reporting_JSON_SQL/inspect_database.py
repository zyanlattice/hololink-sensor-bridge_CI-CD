#!/usr/bin/env python3
"""
Quick database inspector - view SQLite contents without sqlite3 CLI
"""

import sqlite3
import json
from pathlib import Path

def format_row(headers, row, col_widths):
    """Format a single row with proper spacing"""
    parts = []
    for i, (header, val) in enumerate(zip(headers, row)):
        width = col_widths[i]
        val_str = str(val) if val is not None else "NULL"
        parts.append(val_str.ljust(width))
    return " | ".join(parts)

def print_table(headers, rows):
    """Print a simple formatted table"""
    if not rows:
        print("(empty)")
        return
    
    # Calculate column widths
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(val)) if val is not None else 4)
    
    # Print header
    header_line = " | ".join(h.ljust(w) for h, w in zip(headers, col_widths))
    sep_line = "-+-".join("-" * w for w in col_widths)
    print(header_line)
    print(sep_line)
    
    # Print rows
    for row in rows:
        print(format_row(headers, row, col_widths))

db_file = Path("db") / "results.sqlite"

if not db_file.exists():
    print(f"ERROR: {db_file} not found")
    print("\nRun this first:")
    print("  python init_sql.py")
    print("  python ingestion_script.py results/")
    exit(1)

conn = sqlite3.connect(db_file)
conn.row_factory = sqlite3.Row

print(f"\nDatabase: {db_file}")
print(f"Size: {db_file.stat().st_size:,} bytes")
print("\n" + "="*80)

# Show runs
print("\n[RUNS TABLE]")
runs = conn.execute("SELECT * FROM runs").fetchall()
if runs:
    headers = list(runs[0].keys())
    rows = [list(row) for row in runs]
    print_table(headers, rows)
else:
    print("(empty)")

# Show tests
print("\n[TESTS TABLE]")
tests = conn.execute("SELECT test_id, run_id, name, status, duration_ms, category FROM tests").fetchall()
if tests:
    headers = ["test_id", "run_id", "name", "status", "duration_ms", "category"]
    rows = [list(row) for row in tests]
    print_table(headers, rows)
else:
    print("(empty)")

# Show metrics
print("\n[METRICS TABLE]")
metrics = conn.execute("""
    SELECT metric_id, name, value
    FROM metrics
    ORDER BY test_id, name
""").fetchall()
if metrics:
    headers = ["metric_id", "name", "value"]
    rows = [list(row) for row in metrics]
    print_table(headers, rows)
else:
    print("(empty)")

# Show artifacts
print("\n[ARTIFACTS TABLE]")
artifacts = conn.execute("SELECT artifact_id, type, path, label FROM artifacts").fetchall()
if artifacts:
    headers = ["artifact_id", "type", "path", "label"]
    rows = [list(row) for row in artifacts]
    print_table(headers, rows)
else:
    print("(empty)")

# Summary stats
print("\n" + "="*80)
print("[SUMMARY STATISTICS]")
stats = conn.execute("""
    SELECT 
        (SELECT COUNT(*) FROM runs) as total_runs,
        (SELECT COUNT(*) FROM tests) as total_tests,
        (SELECT COUNT(*) FROM metrics) as total_metrics,
        (SELECT COUNT(*) FROM artifacts) as total_artifacts
""").fetchone()
d = dict(stats)
print(f"  Total Runs: {d['total_runs']}")
print(f"  Total Tests: {d['total_tests']}")
print(f"  Total Metrics: {d['total_metrics']}")
print(f"  Total Artifacts: {d['total_artifacts']}")

# Test summary
summary = conn.execute("""
    SELECT 
        COUNT(*) as total,
        SUM(CASE WHEN status='pass' THEN 1 ELSE 0 END) as passed,
        SUM(CASE WHEN status='fail' THEN 1 ELSE 0 END) as failed,
        ROUND(100.0 * SUM(CASE WHEN status='pass' THEN 1 ELSE 0 END) / COUNT(*), 1) as yield_pct
    FROM tests
""").fetchone()
d = dict(summary)
print(f"\n[TEST SUMMARY]")
print(f"  Total Tests: {d['total']}")
print(f"  Passed: {d['passed']}")
print(f"  Failed: {d['failed']}")
print(f"  Yield Rate: {d['yield_pct']}%")

conn.close()
print("\n" + "="*80 + "\n")
