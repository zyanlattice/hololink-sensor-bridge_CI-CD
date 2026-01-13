"""
Pytest configuration and shared fixtures for bitstream programming tests.
"""

import pytest
import os
from pathlib import Path


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "docker: tests that require Docker container"
    )
    config.addinivalue_line(
        "markers", "hardware: tests that require physical Hololink device"
    )
    config.addinivalue_line(
        "markers", "slow: tests that take significant time (>5 minutes)"
    )


@pytest.fixture(scope="session")
def workspace_root():
    """Root directory of holoscan-sensor-bridge workspace."""
    return "/home/lattice/HSB/holoscan-sensor-bridge"


@pytest.fixture(scope="session")
def ci_cd_root():
    """Root directory of CI/CD scripts."""
    return "/home/lattice/HSB/CI_CD"


@pytest.fixture(scope="session")
def hololink_device_ip():
    """
    Hololink device IP address.
    Can be overridden via environment variable HOLOLINK_IP.
    """
    return os.environ.get("HOLOLINK_IP", "192.168.0.2")


@pytest.fixture(scope="session")
def bitstream_config():
    """
    Bitstream configuration from environment or defaults.
    Expected environment variables:
    - BITSTREAM_PATH: path to .bit file
    - BITSTREAM_VERSION: version string
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
