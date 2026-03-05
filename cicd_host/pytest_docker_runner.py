#!/usr/bin/env python3
"""
Remote Docker Pytest Runner
Runs pytest inside Docker container on remote host (Orin/Thor) from Windows PC.

Usage:
    python pytest_docker_runner.py --host-type orin --device cpnx1 --version 0x2511 --datecode 0x01053446
    python pytest_docker_runner.py --host-type thor --device cpnx10 --version 0x2511 --datecode 0x01053446 --hololink-ip 192.168.0.2
    python pytest_docker_runner.py --host-type orin --device avant10 --version 0x2511 --datecode 0x01053446 --config custom_conf.yaml -m "hardware" --verbose
"""

import argparse
import sys
import yaml
from pathlib import Path
from typing import Dict, Optional, Tuple
import subprocess
import json
from datetime import datetime


def load_config(config_path: str = None) -> Dict:
    """Load configuration from YAML file."""
    if config_path is None:
        config_path = Path(__file__).parent / "config.yaml"
    else:
        config_path = Path(config_path)
    
    if not config_path.exists():
        print(f"Error: Config file not found: {config_path}")
        print(f"Please ensure the config file exists and try again.")
        sys.exit(1)
    
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Run pytest in Docker container on remote host",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument("--host-type", type=str, required=True, 
                       choices=['orin', 'thor'],
                       help="Host type to connect to (orin or thor)")
    parser.add_argument("--config", type=str, default=None,
                       help="Path to config YAML file (default: config.yaml)")
    
    # Test configuration
    parser.add_argument("--hololink-ip", type=str, default=None,
                       help="Hololink device IP address (overrides config default)")
    parser.add_argument("--device", "--device-type", type=str, required=True,
                       help="Device type (cpnx1, cpnx10, avant10, avant25)")
    parser.add_argument("--version", type=str, required=True,
                       help="Bitstream version")
    parser.add_argument("--datecode", type=str, required=True,
                       help="Bitstream datecode")
    parser.add_argument("--camera-id", type=int, default=None,
                       help="Camera ID (default from config)")
    
    # Pytest options
    parser.add_argument("-m", "--markers", type=str, default="",
                       help="Pytest markers (e.g., 'hardware', 'not slow')")
    parser.add_argument("-t", "--tests", type=str, default="",
                       help="Specific test files to run (space-separated)")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Verbose output")
    parser.add_argument("--dry-run", action="store_true",
                       help="Print SSH command without executing")
    
    # Results
    parser.add_argument("--local-results-dir", type=str, default=None,
                       help="Local directory to copy results to (default: ./test_reports)")
    
    return parser.parse_args()


def build_docker_command(
    config: Dict,
    host_type: str,
    args: argparse.Namespace
) -> str:
    """Build the Docker run command that executes run_tests.sh (non-interactive, for scripting)."""
    
    host_config = config['hosts'][host_type]
    pytest_config = config['pytest']
    defaults = config['defaults']
    
    workspace_root = host_config['workspace_root']
    username = host_config['username']
    
    # Use values from args or fall back to config defaults
    hololink_ip = args.hololink_ip or defaults['hololink_ip']
    device_type = args.device  # Required argument, no fallback needed
    camera_id = args.camera_id if args.camera_id is not None else defaults['camera_id']
    
    # Build run_tests.sh command with arguments
    run_tests_cmd = "./run_tests.sh"
    run_tests_cmd += f" --device {device_type}"
    run_tests_cmd += f" --version {args.version}"
    run_tests_cmd += f" --datecode {args.datecode}"
    
    # Add pytest markers if specified
    pytest_markers = args.markers or pytest_config['default_markers']
    if pytest_markers:
        run_tests_cmd += f" -m '{pytest_markers}'"
    
    # Add specific test files if specified
    if args.tests:
        run_tests_cmd += f" -t '{args.tests}'"
    
    # Add verbosity
    if args.verbose:
        run_tests_cmd += " -vv"
    
    # Add HTML report generation
    run_tests_cmd += " --html"
    
    # Command to run run_tests.sh using docker (mimics demo.sh but without -it flags)
    docker_cmd = f"""
cd {workspace_root}

# Grant Docker access to local X server (for GUI display on Orin's monitor)
export DISPLAY=:1
export XAUTHORITY=/home/{username}/.Xauthority
echo "Using DISPLAY=:1"

# Allow X11 connections for Docker
xhost + 2>&1 | grep -q "access control disabled" && echo "X11 access granted" || echo "WARNING: xhost + failed - run 'xhost +' manually on Orin desktop terminal"

# Read VERSION file
VERSION=$(cat VERSION)

# Remove old container if it exists
docker rm -f pytest_runner 2>/dev/null || true

# Run docker without -it flags (for non-interactive/scripted use)
# DISPLAY makes GUI appear on Orin's physical monitor
docker run --rm --net host --gpus all --runtime=nvidia --shm-size=1gb --privileged \\
  --name pytest_runner \\
  -v {workspace_root}:{workspace_root} \\
  -v /home/{username}:/home/{username} \\
  -v /sys/bus/pci/devices:/sys/bus/pci/devices \\
  -v /sys/kernel/mm/hugepages:/sys/kernel/mm/hugepages \\
  -v /dev:/dev \\
  -v /tmp/.X11-unix:/tmp/.X11-unix \\
  -v /tmp/argus_socket:/tmp/argus_socket \\
  -v /sys/devices:/sys/devices \\
  -v /var/nvidia/nvcam/settings:/var/nvidia/nvcam/settings \\
  -w {workspace_root}/../CI_CD/Pytest \\
  -e NVIDIA_DRIVER_CAPABILITIES=graphics,video,compute,utility,display \\
  -e NVIDIA_VISIBLE_DEVICES=all \\
  -e DISPLAY=:1 \\
  -e XDG_RUNTIME_DIR=/tmp \\
  -e enableRawReprocess=2 \\
  hololink-demo:$VERSION \\
  bash -c "{run_tests_cmd}"

# Copy results to home directory for easy retrieval
# Create test_reports directory if it doesn't exist
mkdir -p /home/{username}/test_reports

# Find the latest logs folder and copy it (preserving its original name)
LATEST_LOG=$(ls -td {workspace_root}/../CI_CD/test_reports/logs_* 2>/dev/null | head -1)
if [ -n "$LATEST_LOG" ]; then
  LOG_BASENAME=$(basename "$LATEST_LOG")
  cp -r "$LATEST_LOG" /home/{username}/test_reports/"$LOG_BASENAME"
  echo "Results saved to: /home/{username}/test_reports/$LOG_BASENAME"
else
  echo "No test results found"
fi
"""
    
    return docker_cmd.strip()


def build_ssh_command(
    config: Dict,
    host_type: str,
    remote_command: str
) -> list:
    """Build SSH command to execute on remote host."""
    
    host_config = config['hosts'][host_type]
    hostname = host_config['hostname']
    username = host_config['username']
    ssh_key = host_config.get('ssh_key')
    
    # Use key-based or interactive SSH (cross-platform, works on Windows)
    # Allows password prompt if key auth fails
    # StrictHostKeyChecking=accept-new auto-accepts new host keys
    if ssh_key:
        # Use specific SSH key
        ssh_cmd = [
            "ssh",
            "-i", ssh_key,
            "-o", "StrictHostKeyChecking=accept-new",
            f"{username}@{hostname}",
            remote_command
        ]
    else:
        # Use default SSH key from ~/.ssh/ or fall back to password
        ssh_cmd = [
            "ssh",
            "-o", "StrictHostKeyChecking=accept-new",
            f"{username}@{hostname}",
            remote_command
        ]
    
    return ssh_cmd



def copy_results_from_remote(
    config: Dict,
    host_type: str,
    remote_results_dir: str,
    local_results_dir: str
) -> bool:
    """Copy test results from remote host to local directory."""
    
    host_config = config['hosts'][host_type]
    hostname = host_config['hostname']
    username = host_config['username']
    ssh_key = host_config.get('ssh_key')
    
    # Use home directory path (~/ expands to user's home on remote)
    remote_path = f"{username}@{hostname}:~/{remote_results_dir}"
    
    # Create local directory
    local_path = Path(local_results_dir)
    local_path.mkdir(parents=True, exist_ok=True)
    
    print(f"\nCopying results from {remote_path} to {local_path}/...")
    
    # Build scp command (cross-platform, works on Windows)
    # Allows password prompt if key auth fails
    if ssh_key:
        scp_cmd = [
            "scp", "-r",
            "-i", ssh_key,
            "-o", "StrictHostKeyChecking=accept-new",
            remote_path,
            str(local_path)
        ]
    else:
        scp_cmd = [
            "scp", "-r",
            "-o", "StrictHostKeyChecking=accept-new",
            remote_path,
            str(local_path)
        ]
    
    try:
        result = subprocess.run(scp_cmd, check=False)
        if result.returncode == 0:
            print(f"✓ Results copied successfully to {local_path}/{remote_results_dir}")
            return True
        else:
            print(f"✗ Failed to copy results (exit code: {result.returncode})")
            return False
    except Exception as e:
        print(f"✗ Error copying results: {e}")
        return False


def main() -> int:
    """Main entry point."""
    args = parse_args()
    
    # Load configuration
    print(f"Loading configuration for host type: {args.host_type}...")
    config = load_config(args.config)
    
    if args.host_type not in config['hosts']:
        print(f"Error: Host type '{args.host_type}' not found in config")
        return 1
    
    host_config = config['hosts'][args.host_type]
    
    # Print configuration
    print("\n" + "=" * 90)
    print("REMOTE PYTEST EXECUTION CONFIGURATION")
    print("=" * 90)
    print(f"Host Type:       {args.host_type}")
    print(f"Hostname:        {host_config['hostname']}")
    print(f"Username:        {host_config['username']}")
    print(f"Workspace:       {host_config['workspace_root']}")
    print(f"Hololink IP:     {args.hololink_ip or config['defaults']['hololink_ip']}")
    print(f"Device Type:     {args.device}")
    print(f"Version:         {args.version}")
    print(f"Datecode:        {args.datecode}")
    print(f"Pytest Markers:  {args.markers or config['pytest']['default_markers'] or '<none>'}")
    print("=" * 90)
    print("GUI Mode: holoviz windows will display on Orin/Thor's physical monitor")
    print("          (Ensure Orin/Thor is logged in to desktop with monitor connected)")
    print("=" * 90 + "\n")
    
    # Build Docker command
    docker_cmd = build_docker_command(config, args.host_type, args)
    
    if args.dry_run:
        print("=" * 90)
        print("DRY RUN - Docker command that would be executed on remote host:")
        print("=" * 90)
        print(docker_cmd)
        print("=" * 90 + "\n")
        return 0
    
    # Build SSH command
    ssh_cmd = build_ssh_command(config, args.host_type, docker_cmd)
    
    print("=" * 90)
    print("Executing pytest in Docker on remote host...")
    print("=" * 90 + "\n")
    
    # Execute SSH command with real-time output
    try:
        result = subprocess.run(ssh_cmd, check=False)
        exit_code = result.returncode
    except KeyboardInterrupt:
        print("\n\nInterrupted by user (Ctrl+C)")
        return 130
    except Exception as e:
        print(f"\nError executing SSH command: {e}")
        return 1
    
    # Find the latest test results folder on remote host
    find_results_cmd = f"ls -td /home/{host_config['username']}/test_reports/logs_* 2>/dev/null | head -1 | xargs basename 2>/dev/null || echo 'NONE'"
    find_ssh_cmd = build_ssh_command(config, args.host_type, find_results_cmd)
    
    try:
        find_result = subprocess.run(find_ssh_cmd, check=False, capture_output=True, text=True)
        folder_name = find_result.stdout.strip()
        
        if folder_name and folder_name != "NONE":
            remote_results_dir = f"test_reports/{folder_name}"
        else:
            print("Warning: Could not find results folder on remote host")
            remote_results_dir = None
    except Exception as e:
        print(f"Warning: Could not determine results folder: {e}")
        remote_results_dir = None
    
    # Copy results to local directory (use parent folder's test_reports)
    if remote_results_dir:
        local_results_dir = args.local_results_dir or str(Path(__file__).parent.parent / "test_reports")
        copy_results_from_remote(config, args.host_type, remote_results_dir, local_results_dir)
    
    # Print summary
    print("\n" + "=" * 90)
    if exit_code == 0:
        print("✓ Pytest execution completed successfully")
    else:
        print(f"✗ Pytest execution failed with exit code: {exit_code}")
    print("=" * 90 + "\n")
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
