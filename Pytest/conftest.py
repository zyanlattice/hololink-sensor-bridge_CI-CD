"""
Pytest configuration and shared fixtures for Hololink Sensor Bridge verification tests.
"""

import pytest
import os
import sys
from pathlib import Path
import json
from datetime import datetime


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
def test_results_file(test_report_dir, test_session_id):
    """JSON file to store detailed test results."""
    results_file = test_report_dir / f"test_results_{test_session_id}.json"
    return results_file


@pytest.fixture(scope="function")
def record_test_result(test_results_file, request):
    """
    Fixture to record test results to JSON file.
    Usage: call record_test_result(result_dict) in test.
    """
    def _record(result: dict):
        # Load existing results
        if test_results_file.exists():
            with open(test_results_file, 'r') as f:
                results = json.load(f)
        else:
            results = {"tests": []}
        
        # Add test metadata
        result.update({
            "test_name": request.node.name,
            "test_file": request.node.fspath.basename,
            "timestamp": datetime.now().isoformat(),
        })
        
        results["tests"].append(result)
        
        # Save updated results
        with open(test_results_file, 'w') as f:
            json.dump(results, f, indent=2)
    
    return _record


# Pytest hooks for enhanced reporting

def pytest_runtest_makereport(item, call):
    """Hook to capture test outcomes."""
    if call.when == "call":
        # Store test outcome in item for later access
        item.test_outcome = call.excinfo is None


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
