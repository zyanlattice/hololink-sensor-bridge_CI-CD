#!/usr/bin/env python3
"""
Multi-mode camera verification script for IMX258.
Runs verify_camera_imx258.py across multiple camera modes sequentially.
"""

import argparse
import logging
import os
from pathlib import Path
import subprocess
import sys
import time
import terminal_print_formating as tpf

# Camera modes to test in sequence
TEST_MODES = [0, 1, 0, 0, 1]

# Find the verify_camera_imx258.py script
def find_camera_script():
    """
    Find verify_camera_imx258.py in the CI_CD/scripts/ folder.
    Searches upward from current file to find CI_CD root, then looks in scripts/.
    """
    current_file = Path(__file__).resolve()
    
    # Search upward for CI_CD folder
    for parent in [current_file.parent] + list(current_file.parents):
        # Check if we're in CI_CD or a subfolder contains scripts/
        scripts_dir = parent / "scripts"
        if scripts_dir.exists() and scripts_dir.is_dir():
            camera_script = scripts_dir / "verify_camera_imx258.py"
            if camera_script.exists():
                return str(camera_script)
    
    # Fallback: assume script is in same directory as this file
    fallback = current_file.parent / "verify_camera_imx258.py"
    if fallback.exists():
        return str(fallback)
    
    raise FileNotFoundError("Could not find verify_camera_imx258.py in CI_CD/scripts/ folder")

def run_mode(mode, holoviz=False, camera_ip="192.168.0.2", camera_id=0):
    """
    Run verification for a single camera mode.
    
    Args:
        mode: Camera mode to test
        holoviz: Whether to run with holoviz
        camera_ip: IP address of camera
        camera_id: Camera index
    
    Returns:
        Tuple of (success: bool, message: str)
    """
    logging.info(f"{'='*80}")
    logging.info(f"Starting verification for Camera Mode: {mode}")
    logging.info(f"{'='*80}")
    
    # Find the camera script dynamically
    try:
        camera_script = find_camera_script()
    except FileNotFoundError as e:
        logging.error(str(e))
        return False, str(e)
    
    cmd = [
        sys.executable,  # Use same Python interpreter as current process
        camera_script,
        "--camera-mode", str(mode),
        "--camera-ip", camera_ip,
        "--camera-id", str(camera_id),
        "--frame-limit", "300",
        "--timeout", "15",
        "--min-fps", "25.0",
    ]
    
    if holoviz:
        cmd.append("--holoviz")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        
        # Check if verification passed (exit code 0)
        if result.returncode == 0:
            logging.info(f"Mode {mode}: PASSED")
            return True, f"Mode {mode} verification passed"
        else:
            logging.error(f"Mode {mode}: FAILED")
            logging.error(f"STDOUT: {result.stdout}")
            logging.error(f"STDERR: {result.stderr}")
            return False, f"Mode {mode} verification failed"
    
    except subprocess.TimeoutExpired:
        logging.error(f"Mode {mode}: TIMEOUT (exceeded 120s)")
        return False, f"Mode {mode} verification timed out"
    
    except Exception as e:
        logging.error(f"Mode {mode}: ERROR - {str(e)}")
        return False, f"Mode {mode} error: {str(e)}"


def main() -> tuple[bool, str, dict]:
    """Run multi-mode camera verification.
    
    Returns:
        Tuple of (success: bool, message: str, metrics: dict)
    """
    parser = argparse.ArgumentParser(
        description="Run IMX258 camera verification across multiple modes"
    )
    parser.add_argument(
        "--holoviz",
        action="store_true",
        help="Run with holoviz visualization"
    )
    parser.add_argument(
        "--camera-ip",
        type=str,
        default="192.168.0.2",
        help="Hololink device IP"
    )
    parser.add_argument(
        "--camera-id",
        type=int,
        default=0,
        choices=[0, 1],
        help="Camera index"
    )
    
    args = parser.parse_args()
    
    # Initialize metrics
    metrics = {
        "test_modes": TEST_MODES,
        "modes_tested": 0,
        "modes_passed": 0,
        "modes_failed": 0,
        "holoviz_enabled": args.holoviz,
        "camera_ip": args.camera_ip,
        "camera_id": args.camera_id,
        "total_elapsed_time_seconds": 0.0,
        "mode_results": [],
        "mode_timings_seconds": {},
    }
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Print header
    print(tpf.header_footer(90, "MULTI-MODE CAMERA VERIFICATION"))
    
    logging.info(f"Testing camera modes: {TEST_MODES}")
    logging.info(f"Holoviz mode: {'ENABLED' if args.holoviz else 'DISABLED'}")
    logging.info(f"Camera IP: {args.camera_ip}, Camera ID: {args.camera_id}")
    
    results = []
    start_time = time.time()
    
    for idx, mode in enumerate(TEST_MODES, 1):
        logging.info(f"\n[{idx}/{len(TEST_MODES)}] Running mode {mode}...")
        
        mode_start = time.time()
        success, message = run_mode(
            mode,
            holoviz=args.holoviz,
            camera_ip=args.camera_ip,
            camera_id=args.camera_id
        )
        mode_elapsed = time.time() - mode_start
        
        results.append({
            "mode": mode,
            "success": success,
            "message": message,
            "elapsed_seconds": round(mode_elapsed, 2)
        })
        
        # Track in metrics
        metrics["modes_tested"] += 1
        if success:
            metrics["modes_passed"] += 1
        else:
            metrics["modes_failed"] += 1
        metrics["mode_timings_seconds"][f"mode_{mode}_run_{idx}"] = round(mode_elapsed, 2)
        
        # Brief pause between modes
        if idx < len(TEST_MODES):
            logging.info(f"Waiting 5 seconds before next mode...")
            time.sleep(5)
    
    # Print summary
    elapsed_time = time.time() - start_time
    metrics["total_elapsed_time_seconds"] = round(elapsed_time, 2)
    
    # Store detailed mode results
    for result in results:
        metrics["mode_results"].append({
            "mode": result["mode"],
            "success": result["success"],
            "elapsed_seconds": result.get("elapsed_seconds", 0)
        })
    
    print("\n" + tpf.header_footer(90, "MULTI-MODE VERIFICATION SUMMARY"))
    
    passed = sum(1 for r in results if r["success"])
    total = len(results)
    
    for result in results:
        status = "✓ PASS" if result["success"] else "✗ FAIL"
        elapsed = result.get("elapsed_seconds", 0)
        print(f"{status}: {result['message']} ({elapsed:.2f}s)")
    
    print("\n" + "="*90)
    print(f"Results: {passed}/{total} modes passed")
    print(f"Total time: {elapsed_time:.2f}s")
    print("="*90 + "\n")
    
    # Print metrics
    print(f"📊 Metrics: {metrics}")
    
    # Return results
    if passed == total:
        logging.info("All modes passed!")
        return True, f"Multi-mode test passed: {passed}/{total} modes", metrics
    else:
        logging.error(f"{total - passed} mode(s) failed!")
        return False, f"Multi-mode test failed: {passed}/{total} modes passed", metrics


if __name__ == "__main__":
    success, message, metrics = main()
    sys.exit(0 if success else 1)
