#!/usr/bin/env python3
"""
Simple Test Example - Start Here!

This is a minimal example of how to write a test using json_helper_v2.
Replace the test logic with your actual test code.
"""

from json_helper import create_report, Artifact
from pathlib import Path
import time


def main():
    """Run a simple test and generate JSON report"""
    
    # Step 1: Create a report with environment metadata
    report = create_report(env={
        "orin_image": "r36.3",
        "fpga_bitstream": "hsb_20260125_01",
        "git_sha": "abc123",
        "branch": "main",
        "dataset": "camA_1080p60"
    })
    
    # Step 2: Run your test and measure
    print("Running test...")
    start = time.time()
    
    # ======= YOUR TEST CODE HERE =======
    # Example: frame gap jitter measurement
    frame_gap_mean = 16.67
    frame_gap_p95 = 17.4
    frame_gap_p99 = 18.1
    drops = 0
    
    # Determine pass/fail based on thresholds
    test_passed = frame_gap_p99 <= 18.0
    # ====================================
    
    duration_ms = (time.time() - start) * 1000
    
    # Step 3: Record test result
    report.add_test(
        name="frame_gap_jitter",
        status="pass" if test_passed else "fail",
        duration_ms=duration_ms,
        metrics={
            "frame_gap_ms_mean": frame_gap_mean,
            "frame_gap_ms_p95": frame_gap_p95,
            "frame_gap_ms_p99": frame_gap_p99,
            "drops": drops,
        },
        artifacts=[
            Artifact(
                type="png",
                path="frames/frame_gap_histogram.png",
                label="Frame Gap Distribution"
            )
        ],
        category="performance",
        tags=["csi", "raw"]
    )
    
    # Step 4: Save to JSON
    report.finalize()
    report.write(Path("results"))
    
    print(f"✓ Test complete!")
    print(f"  Status: {report.summary['status']}")
    print(f"  Duration: {duration_ms:.0f}ms")
    print(f"  JSON saved to: results/summary.json")
    print()
    print("Next steps:")
    print("  1. python ingestion_script.py results/")
    print("  2. streamlit run local_browser_dashboard.py")
    print("  3. Open http://localhost:8501")


if __name__ == "__main__":
    main()
