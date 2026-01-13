"""
Pytest tests for bitstream programming workflow.

Tests the complete bitstream programming process via Docker container.
"""

import pytest
import subprocess
import sys
from pathlib import Path


@pytest.mark.docker
def test_docker_wrapper_dry_run(
    docker_available,
    hololink_device_ip,
    bitstream_config
):
    """
    Test Docker wrapper in dry-run mode (just validates command building).
    This is a fast smoke test that doesn't require hardware.
    """
    
    #test_dir = Path(__file__).parent
    docker_wrapper = "/home/lattice/HSB/CI_CD/program_bitstream_docker.py"
    
    cmd = [
        sys.executable,
        str(docker_wrapper),
        "--version", bitstream_config["version"],
        "--bitstream-path", bitstream_config["path"],
        "--peer-ip", hololink_device_ip,
        "--dry-run"
    ]
    
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=30
    )
    
    print(result.stdout)
    
    assert result.returncode == 0, f"Dry run failed: {result.stderr}"
    assert "DRY RUN" in result.stdout, "Dry run output not found"
    assert "docker run" in result.stdout.lower(), "Docker command not in output"
    

@pytest.mark.docker
@pytest.mark.hardware
@pytest.mark.slow
def test_full_bitstream_programming_workflow(
    docker_available,
    hololink_device_ip,
    bitstream_config,
    max_saves,
    test_output_parser,
    cleanup_manifest_files,
    caplog
):
    """
    Test complete bitstream programming workflow via Docker.
    
    This test:
    1. Validates Docker is available
    2. Runs program_bitstream_docker.py which orchestrates Docker
    3. Docker container runs bitstream_programmer_wrapper.py
    4. Validates all steps completed successfully
    """
    
    # Get path to program_bitstream_docker.py (parent directory)
    #test_dir = Path(__file__).parent
    docker_wrapper = "/home/lattice/HSB/CI_CD/program_bitstream_docker.py"
    
    assert Path(docker_wrapper).exists(), f"Docker wrapper not found: {docker_wrapper}"
    
    # Build command
    cmd = [
        sys.executable,
        str(docker_wrapper),
        "--version", bitstream_config["version"],
        "--bitstream-path", bitstream_config["path"],
        "--peer-ip", hololink_device_ip,
        "--max-saves", str(max_saves),
    ]
    
    if bitstream_config["md5"]:
        cmd.extend(["--md5", bitstream_config["md5"]])
    
    print(f"\nRunning command: {' '.join(cmd)}")
    
    # Run the Docker wrapper
    # This will output everything to stdout/stderr which pytest will capture
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=3600  # 1 hour timeout for full programming cycle
    )
    
    # Print output for pytest logs (visible with -s flag)
    print("\n" + "=" * 90)
    print("STDOUT:")
    print("=" * 90)
    print(result.stdout)
    
    if result.stderr:
        print("\n" + "=" * 90)
        print("STDERR:")
        print("=" * 90)
        print(result.stderr)
    
    # Parse output to extract test results
    results = test_output_parser(result.stdout, result.stderr)
    
    # Assert exit code
    assert result.returncode == 0, (
        f"Bitstream programming failed with exit code {result.returncode}\n"
        f"See output above for details"
    )
    
    # Assert individual steps if we can parse them
    if "overall_success" in results:
        assert results["overall_success"], "Overall workflow did not report success"
    
    # Individual step assertions (if parseable)
    if results["docker_ok"] is not None:
        assert results["docker_ok"], "Docker check failed"
    if results["bitstream_ok"] is not None:
        assert results["bitstream_ok"], "Bitstream validation failed"
    if results["fpga_ok"] is not None:
        assert results["fpga_ok"], "FPGA UUID detection failed"
    if results["manifest_ok"] is not None:
        assert results["manifest_ok"], "Manifest generation failed"
    if results["program_ok"] is not None:
        assert results["program_ok"], "Bitstream programming failed"
    if results["powercycle_ok"] is not None:
        assert results["powercycle_ok"], "Power cycle failed"
    if results["ethspeed_ok"] is not None:
        assert results["ethspeed_ok"], "Ethernet speed check failed"
    if results["camera_ok"] is not None:
        assert results["camera_ok"], "Camera verification failed"


