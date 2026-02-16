"""
Pytest configuration and shared fixtures for Hololink Sensor Bridge verification tests.
"""

import pytest
import os
import sys
from pathlib import Path
import json
from datetime import datetime

# Import json_helper for structured test reporting from Reporting_JSON_SQL folder
try:
    # Add parent directory to sys.path to access Reporting_JSON_SQL
    reporting_dir = Path(__file__).parent.parent / "Reporting_JSON_SQL"
    if str(reporting_dir) not in sys.path:
        sys.path.insert(0, str(reporting_dir))
    
    from json_helper import RunReport, TestEntry, MetricRegistry, Artifact
    JSON_HELPER_AVAILABLE = True
except ImportError as e:
    JSON_HELPER_AVAILABLE = False
    print(f"Warning: json_helper.py not found in Reporting_JSON_SQL, using simple JSON reporting. Error: {e}")


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "hardware: tests that require physical Hololink device"
    )
    config.addinivalue_line(
        "markers", "camera: tests that require IMX258 camera"
    )
    config.addinivalue_line(
        "markers", "slow: tests that take significant time (>5 minutes)"
    )
    config.addinivalue_line(
        "markers", "network: tests that require network connectivity"
    )
    config.addinivalue_line(
        "markers", "docker: tests that require Docker container"
    )


@pytest.fixture(scope="session")
def scripts_dir():
    """Root directory containing verify scripts."""
    # This conftest is in WIP_pytest/, scripts are in ../scripts/
    return Path(__file__).parent.parent / "scripts"


@pytest.fixture(scope="session", autouse=True)
def add_scripts_to_path(scripts_dir):
    """Add scripts directory to Python path so imports work."""
    sys.path.insert(0, str(scripts_dir))
    yield
    sys.path.remove(str(scripts_dir))


@pytest.fixture(scope="session")
def workspace_root():
    """Root directory of holoscan-sensor-bridge workspace."""
    return os.environ.get("WORKSPACE_ROOT", "/home/lattice/HSB/holoscan-sensor-bridge")


@pytest.fixture(scope="session")
def ci_cd_root():
    """Root directory of CI/CD scripts."""
    return Path(__file__).parent.parent


@pytest.fixture(scope="session")
def hololink_device_ip():
    """
    Hololink device IP address.
    Can be overridden via environment variable HOLOLINK_IP.
    """
    return os.environ.get("HOLOLINK_IP", "192.168.0.2")


@pytest.fixture(scope="session")
def camera_id():
    """
    Camera ID (0 or 1).
    Can be overridden via environment variable CAMERA_ID.
    """
    return int(os.environ.get("CAMERA_ID", "0"))


@pytest.fixture(scope="session")
def bitstream_path():
    """
    Path to bitstream file for verification.
    Can be overridden via environment variable BITSTREAM_PATH.
    """
    return os.environ.get("BITSTREAM_PATH", None)


@pytest.fixture(scope="session")
def bitstream_version():
    """
    Expected bitstream version (hex or decimal).
    Can be overridden via environment variable BITSTREAM_VERSION.
    """
    return os.environ.get("BITSTREAM_VERSION", None)


@pytest.fixture(scope="session")
def bitstream_datecode():
    """
    Expected bitstream datecode (hex or decimal).
    Can be overridden via environment variable BITSTREAM_DATECODE.
    """
    return os.environ.get("BITSTREAM_DATECODE", None)


@pytest.fixture(scope="session")
def expected_md5():
    """
    Expected MD5 checksum for bitstream.
    Can be overridden via environment variable BITSTREAM_MD5.
    """
    return os.environ.get("BITSTREAM_MD5", None)


@pytest.fixture(scope="session")
def device_type():
    """
    Device type: cpnx1, cpnx10, avant10, or avant25.
    Can be overridden via environment variable DEVICE_TYPE.
    """
    return os.environ.get("DEVICE_TYPE", "cpnx10")


@pytest.fixture(scope="session")
def host_interface():
    """
    Host interface number (1-4).
    Can be overridden via environment variable HOST_INTERFACE.
    """
    return int(os.environ.get("HOST_INTERFACE", "1"))


@pytest.fixture(scope="session")
def camera_mode(device_type):
    """
    Camera mode based on device type.
    - cpnx1: mode 1 (1920x1080 @ 30fps)
    - all others: mode 0 (1920x1080 @ 60fps)
    Can be overridden via environment variable CAMERA_MODE.
    """
    if os.environ.get("CAMERA_MODE"):
        return int(os.environ.get("CAMERA_MODE"))
    
    # Special case: cpnx1 uses mode 1
    if device_type and device_type.lower() == "cpnx1":
        return 1
    
    # Default: mode 0
    return 0


@pytest.fixture(scope="session")
def test_report_dir(ci_cd_root):
    """Directory to store test reports and logs."""
    report_dir = ci_cd_root / "test_reports"
    report_dir.mkdir(exist_ok=True)
    return report_dir


@pytest.fixture(scope="session")
def test_session_id():
    """Unique ID for this test session."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


@pytest.fixture(scope="session")
def test_results_file(save_dir, test_session_id):
    """JSON file to store simplified test results."""
    results_file = save_dir / f"test_results_simple_{test_session_id}.json"
    return results_file


@pytest.fixture(scope="session")
def run_report(save_dir, test_session_id, hololink_device_ip, device_type, bitstream_version, bitstream_datecode, request):
    """
    Session-level RunReport instance for json_helper.py structured reporting.
    This collects all tests and writes the final JSON report at session end.
    Always active - generates test_results_{session_id}.json.
    """
    if not JSON_HELPER_AVAILABLE:
        yield None
        return
    
    try:
        # Create run report with environment metadata
        report = RunReport(
            run_id=f"pytest_{test_session_id}",
            env={
                "hololink_ip": hololink_device_ip,
                "device_type": device_type or "unknown",
                "bitstream_version": bitstream_version or "unknown",
                "bitstream_datecode": bitstream_datecode or "unknown",
                "python_version": sys.version,
                "platform": sys.platform,
                "host_platform": os.environ.get("HOST_PLATFORM", "unknown"),
                "camera_model": os.environ.get("CAMERA_MODEL", "imx258"),
                "git_sha": os.environ.get("GIT_SHA", None),
                "branch": os.environ.get("GIT_BRANCH", None)
            }
        )
        # Store in session for hook access
        request.config._run_report = report
    except Exception as e:
        print(f"\nWarning: Failed to initialize RunReport: {e}")
        yield None
        return
    
    yield report
    
    # At session end, finalize and write report
    try:
        report.finalize()
        output_path = save_dir / f"test_results_{test_session_id}.json"
        report.write(save_dir, filename=output_path.name)
        print(f"\n✓ Structured JSON report: {output_path}")
    except Exception as e:
        print(f"\n✗ Failed to write structured report: {e}")


@pytest.fixture(scope="session")
def save_dir(ci_cd_root):
    """
    Directory for saving test artifacts (images, logs, etc).
    Uses TEST_LOG_DIR from run_tests.sh if available, otherwise creates one.
    """
    # Try to get from environment (set by run_tests.sh)
    log_dir = os.environ.get("TEST_LOG_DIR")
    
    if log_dir:
        save_path = Path(log_dir)
    else:
        # Fallback: create in test_reports/logs_TIMESTAMP at CI_CD root
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = ci_cd_root / "test_reports" / f"logs_{timestamp}"
    
    save_path.mkdir(parents=True, exist_ok=True)
    return save_path


@pytest.fixture(scope="function")
def record_test_result(test_results_file, request):
    """
    Fixture to record test results.
    Generates simplified backup test_results_simple.json and adds to structured report.
    Usage: call record_test_result(result_dict) in test.
    """
    # Get run_report if available
    run_report = None
    try:
        run_report = request.getfixturevalue('run_report')
        print(f"[DEBUG] Successfully got run_report fixture: {run_report}")
    except Exception as e:
        print(f"[DEBUG] Failed to get run_report fixture: {e}")
        import traceback
        traceback.print_exc()
    
    def _record(result: dict):
        print(f"\n[DEBUG] record_test_result called for test: {request.node.name}")
        print(f"[DEBUG] test_results_file: {test_results_file}")
        print(f"[DEBUG] JSON_HELPER_AVAILABLE: {JSON_HELPER_AVAILABLE}")
        print(f"[DEBUG] run_report: {run_report}")
        
        # Extract key info
        test_name = request.node.name
        test_file = str(request.node.path.name) if hasattr(request.node, 'path') else str(request.node.fspath.basename)
        success = result.get("success", False)
        
        # Check if test has xfail marker
        has_xfail = request.node.get_closest_marker('xfail') is not None
        
        # Determine status (xfail tests that fail should be recorded as "xfail", not "fail")
        if success:
            status = "pass"
        elif has_xfail:
            status = "xfail"
        else:
            status = "fail"
        
        message = result.get("message", status.upper())
        
        # Simplified backup test_results_simple.json (Option A)
        try:
            if test_results_file.exists():
                with open(test_results_file, 'r') as f:
                    results = json.load(f)
            else:
                results = {
                    "run_id": f"pytest_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    "timestamp": datetime.now().isoformat(),
                    "tests": []
                }
            
            # Simple standardized entry for backup
            backup_entry = {
                "test_name": f"{test_file}::{test_name}",
                "test_file": test_file,
                "timestamp": datetime.now().isoformat(),
                "status": status,
                "duration_ms": result.get("duration_ms", 0.0),
                "success": success,
                "message": message
            }
            
            results["tests"].append(backup_entry)
            
            with open(test_results_file, 'w') as f:
                json.dump(results, f, indent=2)
            
            print(f"✓ Test result recorded to {test_results_file}")
            
        except Exception as e:
            print(f"✗ Failed to record backup JSON: {e}")
            import traceback
            traceback.print_exc()
        
        # Add to structured report with full detail
        if not JSON_HELPER_AVAILABLE:
            print(f"[DEBUG] JSON_HELPER not available, skipping structured report")
            return
            
        if not run_report:
            print(f"[DEBUG] run_report is None, skipping structured report")
            return
            
        try:
            print(f"[DEBUG] Adding to structured report...")
            # Extract metrics from stats field
            metrics = result.get("stats", {})
            
            # Determine category and tags from test name/file
            category = result.get("category", "functional")
            tags = result.get("tags", [])
            
            # Auto-categorize if not provided
            if category == "functional":
                if "camera" in test_file.lower():
                    category = "camera"
                elif "apb" in test_file.lower() or "register" in test_file.lower():
                    category = "hardware_verification"
                elif "eth" in test_file.lower() or "udp" in test_file.lower():
                    category = "network"
                elif "ptp" in test_file.lower():
                    category = "timing"
                elif "sample_app" in test_file.lower():
                    category = "sample_applications"
                elif "device" in test_file.lower() or "holo" in test_file.lower():
                    category = "system_integration"
                elif "latency" in test_file.lower() or "performance" in test_file.lower():
                    category = "performance"
            
            print(f"[DEBUG] Adding test to structured report: name={test_name}, status={status}, category={category}")
            
            # Extract artifacts if provided
            artifacts = result.get("artifacts", [])
            
            # Add test to structured report
            run_report.add_test(
                name=test_name,
                status=status,
                duration_ms=result.get("duration_ms", 0.0),
                metrics=metrics,
                error_message=message if status == "fail" else None,
                artifacts=artifacts,
                category=category,
                tags=tags
            )
            
            print(f"[DEBUG] TestEntry created successfully with {len(artifacts)} artifacts")
            
            # Mark that this test has been recorded (to avoid duplicate in hook)
            request.node._result_recorded = True
            
            print(f"✓ Test added to structured report")
        except Exception as e:
            print(f"✗ Failed to add test to structured report: {e}")
            import traceback
            traceback.print_exc()
    
    return _record


# Pytest hooks for enhanced reporting

@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Hook to automatically capture all test results including xfail and add to structured report."""
    outcome = yield
    report = outcome.get_result()
    
    # Only process test call phase (not setup/teardown)
    if report.when == "call":
        # Get run_report from config if available
        run_report = getattr(item.session.config, '_run_report', None)
        
        if not run_report or not JSON_HELPER_AVAILABLE:
            return
        
        # Check if test already recorded via record_test_result fixture
        # (to avoid duplicates for tests that explicitly call record_test_result)
        if hasattr(item, '_result_recorded'):
            return
        
        # Auto-record tests that don't explicitly call record_test_result
        try:
            # Determine status
            # Note: xfail with strict=True shows as failed but has wasxfail attribute
            if report.passed:
                status = "pass"
            elif report.failed:
                # Check if this is an xfail test (can be failed with strict=True)
                status = "xfail" if hasattr(report, 'wasxfail') else "fail"
            elif report.skipped:
                # Check if this is an xpassed test (xfail that passed unexpectedly)
                status = "xfail" if hasattr(report, 'wasxfail') else "skip"
            else:
                status = "unknown"
            
            test_name = item.name
            test_file = str(item.path.name) if hasattr(item, 'path') else str(item.fspath.basename)
            
            # Auto-categorize
            category = "functional"
            if "camera" in test_file.lower():
                category = "camera"
            elif "apb" in test_file.lower() or "register" in test_file.lower():
                category = "hardware_verification"
            elif "eth" in test_file.lower() or "udp" in test_file.lower():
                category = "network"
            elif "ptp" in test_file.lower():
                category = "timing"
            elif "sample_app" in test_file.lower():
                category = "sample_applications"
            elif "device" in test_file.lower() or "holo" in test_file.lower():
                category = "system_integration"
            elif "latency" in test_file.lower() or "performance" in test_file.lower():
                category = "performance"
            
            # Add test to structured report
            run_report.add_test(
                name=test_name,
                status=status,
                duration_ms=report.duration * 1000,
                metrics={},
                error_message=str(report.longrepr) if report.failed else None,
                category=category,
                tags=[]
            )
                
        except Exception as e:
            print(f"Warning: Failed to auto-record test to structured report: {e}")


@pytest.fixture(scope="session", autouse=True)
def setup_test_results_file(request, test_results_file):
    """Store test_results_file in config for hook access."""
    request.config._test_results_file = test_results_file
    yield


def pytest_sessionfinish(session, exitstatus):
    """Generate summary report at end of session."""
    report_dir = Path(__file__).parent.parent / "test_reports"
    if not report_dir.exists():
        return
    
    # Find the latest results file
    results_files = list(report_dir.glob("test_results_*.json"))
    if not results_files:
        return
    
    latest_results = max(results_files, key=lambda p: p.stat().st_mtime)
    
    # Generate summary markdown
    with open(latest_results, 'r') as f:
        results = json.load(f)
    
    summary_file = latest_results.with_suffix('.md')
    
    with open(summary_file, 'w') as f:
        f.write("# Hololink Sensor Bridge Test Report\n\n")
        f.write(f"**Session**: {latest_results.stem}\n\n")
        f.write(f"**Exit Status**: {exitstatus}\n\n")
        
        f.write("## Test Results\n\n")
        f.write("| Test | Status | Message |\n")
        f.write("|------|--------|----------|\n")
        
        for test in results.get("tests", []):
            status = "✅ PASS" if test.get("success", False) else "❌ FAIL"
            name = test.get("test_name", "Unknown")
            msg = test.get("message", "")
            f.write(f"| {name} | {status} | {msg} |\n")
        
        f.write("\n## Detailed Results\n\n")
        for test in results.get("tests", []):
            f.write(f"### {test.get('test_name', 'Unknown')}\n\n")
            f.write(f"- **Status**: {'PASS' if test.get('success') else 'FAIL'}\n")
            f.write(f"- **Message**: {test.get('message', 'N/A')}\n")
            if "stats" in test and test["stats"]:
                f.write(f"- **Stats**: {json.dumps(test['stats'], indent=2)}\n")
            f.write("\n")
    """
    - BITSTREAM_MD5: optional MD5 checksum
    """
    config = {
        "path": os.environ.get(
            "BITSTREAM_PATH",
            "/home/lattice/HSB/CI_CD/bitstream/fpga_cpnx_versa_0104_2507.bit"
        ),
        "version": os.environ.get("BITSTREAM_VERSION", "0104_2507"),
        "md5": os.environ.get("BITSTREAM_MD5", ""),
    }
    
    # Validate bitstream file exists
    if not Path(config["path"]).exists():
        pytest.skip(f"Bitstream file not found: {config['path']}")
    
    return config


@pytest.fixture(scope="session")
def docker_available():
    """Check if Docker is available."""
    import subprocess
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            check=False
        )
        if result.returncode != 0:
            pytest.skip("Docker is not available or not running")
        return True
    except FileNotFoundError:
        pytest.skip("Docker command not found")


@pytest.fixture(scope="function")
def max_saves():
    """Number of images to save during verification (default 1)."""
    return int(os.environ.get("MAX_SAVES", "1"))


@pytest.fixture(scope="function")
def test_output_parser():
    """
    Helper to parse output from bitstream programming.
    Returns a parser function that extracts success/failure status.
    """
    def parse_output(stdout: str, stderr: str) -> dict:
        """
        Parse output and extract test results.
        
        Returns dict with:
        - docker_ok, bitstream_ok, fpga_ok, manifest_ok,
          program_ok, powercycle_ok, ethspeed_ok, camera_ok
        """
        results = {
            "docker_ok": False,
            "bitstream_ok": False,
            "fpga_ok": False,
            "manifest_ok": False,
            "program_ok": False,
            "powercycle_ok": False,
            "ethspeed_ok": False,
            "camera_ok": False,
        }
        
        # Look for success indicators in output
        combined = stdout + stderr
        
        # Parse the final result line
        if "Docker OK:" in combined:
            parts = combined.split("Docker OK:")[-1].strip()
            # Extract boolean values
            try:
                values = [s.split(":")[-1].strip() for s in parts.split(",")]
                if len(values) >= 8:
                    results["docker_ok"] = values[0].lower() == "true"
                    results["bitstream_ok"] = values[1].lower() == "true"
                    results["fpga_ok"] = values[2].lower() == "true"
                    results["manifest_ok"] = values[3].lower() == "true"
                    results["program_ok"] = values[4].lower() == "true"
                    results["powercycle_ok"] = values[5].lower() == "true"
                    results["ethspeed_ok"] = values[6].lower() == "true"
                    results["camera_ok"] = values[7].lower() == "true"
            except (IndexError, ValueError):
                pass
        
        # Also check for specific success/failure messages
        if "✓ Bitstream programming completed successfully" in combined:
            results["overall_success"] = True
        elif "✗ Bitstream programming failed" in combined:
            results["overall_success"] = False
        
        return results
    
    return parse_output


@pytest.fixture(scope="function")
def cleanup_manifest_files():
    """Cleanup manifest files after test."""
    yield
    # Cleanup after test
    manifest_dir = Path("/home/lattice/HSB/CI_CD/scripts")
    for manifest in manifest_dir.glob("*_manifest.yaml"):
        try:
            manifest.unlink()
        except Exception:
            pass
