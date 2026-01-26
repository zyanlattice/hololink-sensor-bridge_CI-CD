#!/usr/bin/env python3
"""
Multi-mode camera verification script for IMX258.
Runs verify_camera_imx258.py across multiple camera modes sequentially.
"""

import argparse
import logging
import subprocess
import sys
import time
import terminal_print_formating as tpf

# Camera modes to test in sequence
TEST_MODES = [4, 5, 5, 4, 5]

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
    
    cmd = [
        "python3", "verify_camera_imx258.py",
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


def main():
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
        
        success, message = run_mode(
            mode,
            holoviz=args.holoviz,
            camera_ip=args.camera_ip,
            camera_id=args.camera_id
        )
        
        results.append({
            "mode": mode,
            "success": success,
            "message": message
        })
        
        # Brief pause between modes
        if idx < len(TEST_MODES):
            logging.info(f"Waiting 5 seconds before next mode...")
            time.sleep(5)
    
    # Print summary
    elapsed_time = time.time() - start_time
    
    print("\n" + tpf.header_footer(90, "MULTI-MODE VERIFICATION SUMMARY"))
    
    passed = sum(1 for r in results if r["success"])
    total = len(results)
    
    for result in results:
        status = "✓ PASS" if result["success"] else "✗ FAIL"
        print(f"{status}: {result['message']}")
    
    print("\n" + "="*90)
    print(f"Results: {passed}/{total} modes passed")
    print(f"Total time: {elapsed_time:.2f}s")
    print("="*90 + "\n")
    
    # Exit with appropriate code
    if passed == total:
        logging.info("All modes passed!")
        sys.exit(0)
    else:
        logging.error(f"{total - passed} mode(s) failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
