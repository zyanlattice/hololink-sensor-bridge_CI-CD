"""
Test suite for Holoscan Sensor Bridge example applications.
Tests example Python applications from /home/orin/HSB/holoscan-sensor-bridge/examples
"""

import pytest
import subprocess
import sys
import logging
from pathlib import Path


def find_examples_dir():
    """
    Dynamically find the holoscan-sensor-bridge/examples directory.
    Searches up the directory tree from the current script location.
    """
    # Start from the current script's directory
    current_dir = Path(__file__).resolve().parent
    
    # Search up the directory tree for holoscan-sensor-bridge/examples
    search_dir = current_dir
    for _ in range(5):  # Search up to 5 levels up
        # Try to find holoscan-sensor-bridge/examples from the parent directory
        parent_dir = search_dir.parent
        examples_path = parent_dir / "holoscan-sensor-bridge" / "examples"
        if examples_path.exists() and examples_path.is_dir():
            return examples_path
        search_dir = parent_dir
    
    # Fallback: try common paths if dynamic search fails
    fallback_paths = [
        Path("/home/orin/HSB/holoscan-sensor-bridge/examples"),
        Path("/home/thor/HSB/holoscan-sensor-bridge/examples"),
    ]
    for path in fallback_paths:
        if path.exists() and path.is_dir():
            return path
    
    # Return first fallback path even if it doesn't exist (will fail with clear error)
    return fallback_paths[0]


# Base path for example applications
EXAMPLES_DIR = find_examples_dir()

# Set up logger for this module
logger = logging.getLogger(__name__)


def run_sample_app(
    script_name: str,
    args: list,
    timeout: int = 30,
    expected_return_code: int = 0
) -> tuple[bool, str, str]:
    """
    Helper function to run a sample application and capture its output.
    
    Args:
        script_name: Name of the Python script (e.g., "linux_imx258_player.py")
        args: List of command-line arguments to pass to the script
        timeout: Maximum execution time in seconds
        expected_return_code: Expected return code (0 for success)
    
    Returns:
        Tuple of (success, stdout, stderr)
    """
    script_path = EXAMPLES_DIR / script_name
    
    if not script_path.exists():
        logger.error(f"Script not found: {script_path}")
        return False, "", f"Script not found: {script_path}"
    
    # Build command
    cmd = [sys.executable, str(script_path)] + args
    logger.info(f"Running: {' '.join(cmd)}")
    
    try:
        # Run the application
        # Use errors='replace' to handle non-UTF-8 bytes in output (e.g., binary UUIDs)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',  # Replace invalid UTF-8 bytes with replacement character
            timeout=timeout,
            cwd=str(EXAMPLES_DIR)
        )
        
        # Log the output to pytest's log file
        logger.info(f"=== {script_name} STDOUT ===")
        if result.stdout:
            for line in result.stdout.splitlines():
                logger.info(line)
        else:
            logger.info("(empty)")
            
        logger.info(f"=== {script_name} STDERR ===")
        if result.stderr:
            for line in result.stderr.splitlines():
                logger.info(line)
        else:
            logger.info("(empty)")
        
        logger.info(f"=== {script_name} Exit Code: {result.returncode} ===")
        
        success = (result.returncode == expected_return_code)
        return success, result.stdout, result.stderr
        
    except subprocess.TimeoutExpired as e:
        logger.error(f"Timeout after {timeout}s")
        return False, e.stdout.decode() if e.stdout else "", f"Timeout after {timeout}s"
    except Exception as e:
        logger.error(f"Exception: {str(e)}")
        return False, "", f"Exception: {str(e)}"


@pytest.mark.hardware
def test_imx258_player(hololink_device_ip, camera_id, record_test_result):
    """
    Test linux_imx258_player.py - Basic IMX258 camera player with Holoviz display.
    
    This test runs the IMX258 player application for a short duration to verify:
    - Camera initialization
    - Frame capture and display
    - Application startup and shutdown
    """
    # Application parameters (linux_imx258_player.py uses different arg names)
    args = [
        "--camera", str(camera_id),  # Uses --camera not --camera-id
        "--camera-mode", "0",  # Mode 0: 1920x1080 @ 60fps
        "--frame-limit", "200",  # Limit frames to avoid long run time
    ]
    
    # Note: linux_imx258_player.py doesn't accept --camera-ip, uses default 192.168.0.2
    
    # Run the application
    success, stdout, stderr = run_sample_app(
        script_name="linux_imx258_player.py",
        args=args,
        timeout=30
    )
    
    # Check for expected output patterns (linux_imx258_player.py has different output than verify scripts)
    checks = {
        "app_started": "Camera ID" in stdout or "I2C Controller" in stdout,
        "graph_executed": "Graph execution finished" in stderr or "Scheduler finished" in stderr,
        "clean_shutdown": "Destroying context" in stderr,
        # Only fail on actual fatal errors, not warnings or info messages
        "no_fatal_errors": not any(pattern in stderr.lower() for pattern in ["traceback", "fatal", "segmentation fault", "core dumped"])
    }
    
    # Calculate success based on checks
    all_checks_passed = all(checks.values())
    
    # Record results
    message = f"IMX258 Player: {'PASS' if success and all_checks_passed else 'FAIL'}"
    if not success:
        message += f" - App returned non-zero exit code"
    failed_checks = [k for k, v in checks.items() if not v]
    if failed_checks:
        message += f" - Failed checks: {', '.join(failed_checks)}"
        # Debug: Show what triggered no_fatal_errors failure
        if "no_fatal_errors" in failed_checks:
            for pattern in ["traceback", "fatal", "segmentation fault", "core dumped"]:
                if pattern in stderr.lower():
                    message += f" (found '{pattern}' in stderr)"
                    break
    
    # Record results
    message = f"IMX258 Player: {'PASS' if success and all_checks_passed else 'FAIL'}"
    if not success:
        message += f" - App returned non-zero exit code"
    failed_checks = [k for k, v in checks.items() if not v]
    if failed_checks:
        message += f" - Failed checks: {', '.join(failed_checks)}"
    
    record_test_result({
        "success": success and all_checks_passed,
        "message": message,
        "stats": {
            "checks": checks,
            "stdout_length": len(stdout),
            "stderr_length": len(stderr)
        }
    })
    
    # Print output for debugging if failed
    if not (success and all_checks_passed):
        print("\n=== STDOUT ===")
        print(stdout[-1000:] if len(stdout) > 1000 else stdout)
        print("\n=== STDERR ===")
        print(stderr[-1000:] if len(stderr) > 1000 else stderr)
    
    assert success and all_checks_passed, message


# Template for future sample app tests
# Uncomment and modify as needed:

@pytest.mark.hardware
def test_tao_peoplenet(hololink_device_ip, camera_id, record_test_result):
    """
    Test linux_tao_peoplenet_imx258.py - PeopleNet AI inference for person detection.
    
    This test runs the PeopleNet AI model application to verify:
    - TAO PeopleNet model loading
    - Person detection inference on camera frames
    - Visualization of detection results
    """
    args = [
        "--camera", str(camera_id),  # Camera index
        "--camera", "0",  # Mode 0: 1920x1080 @ 60fps
        "--frame-limit", "500"  # 100 frames for inference testing
    ]
    
    # Note: Script likely uses default IP 192.168.0.2
    
    success, stdout, stderr = run_sample_app(
        script_name="linux_tao_peoplenet_imx258.py",
        args=args,
        timeout=120  # Longer timeout for AI model loading and inference
    )
    
    # Check for expected PeopleNet output
    checks = {
        "app_started": "Initializing" in stderr or "Camera ID" in stdout or "I2C Controller" in stdout,
        "graph_executed": "Graph execution finished" in stderr or "Scheduler finished" in stderr,
        "clean_shutdown": "Destroying context" in stderr,
        "no_fatal_errors": not any(pattern in stderr.lower() for pattern in ["traceback", "fatal", "segmentation fault", "core dumped"])
    }
    
    all_checks_passed = all(checks.values())
    message = f"TAO PeopleNet: {'PASS' if success and all_checks_passed else 'FAIL'}"
    if not success:
        message += f" - App returned non-zero exit code"
    failed_checks = [k for k, v in checks.items() if not v]
    if failed_checks:
        message += f" - Failed checks: {', '.join(failed_checks)}"
    
    record_test_result({
        "success": success and all_checks_passed,
        "message": message,
        "stats": {
            "checks": checks,
            "stdout_length": len(stdout),
            "stderr_length": len(stderr)
        }
    })
    
    if not (success and all_checks_passed):
        print("\n=== STDOUT ===")
        print(stdout[-1000:] if len(stdout) > 1000 else stdout)
        print("\n=== STDERR ===")
        print(stderr[-1500:] if len(stderr) > 1500 else stderr)
    
    assert success and all_checks_passed, message


@pytest.mark.hardware
def test_body_pose(hololink_device_ip, camera_id, record_test_result):
    """
    Test linux_body_pose_imx258.py - Body pose detection with AI inference.
    
    This test runs the body pose detection application to verify:
    - AI model loading
    - Body pose inference on camera frames
    - Visualization of detected poses
    """
    args = [
        "--camera", "0",  # Mode 0: 1920x1080 @ 60fps
        "--frame-limit", "500"  # 500 frames for body pose detection
    ]
    
    # Note: Script likely uses default camera settings (192.168.0.2, camera 0)
    
    success, stdout, stderr = run_sample_app(
        script_name="linux_body_pose_estimation_imx258.py",
        args=args,
        timeout=120  # Longer timeout for AI model loading and inference
    )
    
    # Check for expected body pose output
    checks = {
        "app_started": "Initializing" in stderr or "Camera ID" in stdout or "I2C Controller" in stdout,
        "graph_executed": "Graph execution finished" in stderr or "Scheduler finished" in stderr,
        "clean_shutdown": "Destroying context" in stderr,
        "no_fatal_errors": not any(pattern in stderr.lower() for pattern in ["traceback", "fatal", "segmentation fault", "core dumped"])
    }
    
    all_checks_passed = all(checks.values())
    message = f"Body Pose: {'PASS' if success and all_checks_passed else 'FAIL'}"
    if not success:
        message += f" - App returned non-zero exit code"
    failed_checks = [k for k, v in checks.items() if not v]
    if failed_checks:
        message += f" - Failed checks: {', '.join(failed_checks)}"
    
    record_test_result({
        "success": success and all_checks_passed,
        "message": message,
        "stats": {
            "checks": checks,
            "stdout_length": len(stdout),
            "stderr_length": len(stderr)
        }
    })
    
    if not (success and all_checks_passed):
        print("\n=== STDOUT ===")
        print(stdout[-1000:] if len(stdout) > 1000 else stdout)
        print("\n=== STDERR ===")
        print(stderr[-1500:] if len(stderr) > 1500 else stderr)
    
    assert success and all_checks_passed, message


@pytest.mark.hardware  
def test_latency_measurement(hololink_device_ip, camera_id, record_test_result):
    """
    Test linux_imx258_latency.py - Latency measurement and analysis.
    
    This test runs the latency measurement application to verify:
    - Frame timing analysis
    - CPU and operator latency tracking
    - Processing pipeline latency measurement
    """
    args = [
        "--camera-mode", "0",  # Mode 0: 1920x1080 @ 60fps
        "--frame-limit", "200",  # 200 frames for latency analysis
        "--log-level", "20"  # INFO level
    ]
    
    # Note: linux_imx258_latency.py uses --hololink for IP (default 192.168.0.2)
    # Camera index is hardcoded to 0 in the script
    
    success, stdout, stderr = run_sample_app(
        script_name="linux_imx258_latency.py",
        args=args,
        timeout=60  # Longer timeout for 200 frames
    )
    
    # Check for expected latency report output
    checks = {
        "app_started": "Initializing" in stderr or "Calling run" in stderr,
        "latency_report": "Complete report" in stderr,
        "frame_time_measured": "Frame Time" in stderr,
        "latency_metrics": "Latency" in stderr and ("Frame Transfer" in stderr or "Operator" in stderr or "Processing" in stderr),
        "graph_executed": "Graph execution finished" in stderr or any(x in stderr for x in ["Min", "Max", "Avg"]),
        "no_fatal_errors": not any(pattern in stderr.lower() for pattern in ["traceback", "fatal", "segmentation fault", "core dumped"])
    }
    
    all_checks_passed = all(checks.values())
    message = f"Latency Measurement: {'PASS' if success and all_checks_passed else 'FAIL'}"
    if not success:
        message += f" - App returned non-zero exit code"
    failed_checks = [k for k, v in checks.items() if not v]
    if failed_checks:
        message += f" - Failed checks: {', '.join(failed_checks)}"
    
    record_test_result({
        "success": success and all_checks_passed,
        "message": message,
        "stats": {
            "checks": checks,
            "stdout_length": len(stdout),
            "stderr_length": len(stderr)
        }
    })
    
    if not (success and all_checks_passed):
        print("\n=== STDOUT ===")
        print(stdout[-1000:] if len(stdout) > 1000 else stdout)
        print("\n=== STDERR ===")
        print(stderr[-2000:] if len(stderr) > 2000 else stderr)
    
    assert success and all_checks_passed, message
