#!/usr/bin/env python3
"""
Cross-platform Docker wrapper for bitstream programming.
Replaces Program_Bitstream.sh with pure Python for Windows/Linux/Jenkins compatibility.
"""

import argparse
import os
import sys
import subprocess
import platform
from pathlib import Path
from typing import List, Optional

# Add parent scripts directory to path for imports
_script_dir = Path(__file__).parent.parent / "eth_program_bitstream"
sys.path.insert(0, str(_script_dir))

def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Programme bitstream to FPGA via Docker container",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument("--version", type=str, required=True, help="Bitstream version")
    parser.add_argument("--bitstream-path", type=str, required=True, help="Path to the bitstream file")
    parser.add_argument("--peer-ip", type=str, required=True, help="Hololink device IP address")
    parser.add_argument("--md5", type=str, default="", help="Bitstream MD5 checksum (optional)")
    parser.add_argument("--manifest", type=str, default="", help="Manifest file name (optional)")
    parser.add_argument("--max-saves", type=int, default=1, help="Maximum number of images to save during verification (0 = no images)")
    parser.add_argument("--workspace-root", type=str, default="/home/lattice/HSB/holoscan-sensor-bridge", help="Root directory of the holoscan-sensor-bridge workspace")
    parser.add_argument("--dry-run", action="store_true", help="Print Docker command without executing")
    
    return parser.parse_args()


def check_docker_available() -> bool:
    """Check if Docker is available and running."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            check=False
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def get_docker_version(workspace_root: str) -> str:
    """Read VERSION file from workspace."""
    version_file = Path(workspace_root) / "VERSION"
    if not version_file.exists():
        print(f"Warning: VERSION file not found at {version_file}, using 'latest'")
        return "latest"
    
    with open(version_file, 'r') as f:
        return f.read().strip()


def cleanup_existing_container(container_name: str) -> None:
    """Remove existing container if it exists."""
    print(f"Checking for existing container '{container_name}'...")
    
    # Check if container exists
    result = subprocess.run(
        ["docker", "ps", "-a", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        check=False
    )
    
    if container_name in result.stdout.splitlines():
        print(f"Removing existing container: {container_name}")
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            check=False
        )


def enable_xhost() -> None:
    """Enable X11 forwarding (Linux only)."""
    if platform.system() == "Linux":
        try:
            subprocess.run(["xhost", "+"], check=False, capture_output=True)
        except FileNotFoundError:
            print("Warning: xhost not found, X11 forwarding may not work")


def build_docker_command(
    args: argparse.Namespace,
    workspace_root: str,
    docker_version: str,
    container_name: str = "demo_bitstream_prog"
) -> List[str]:
    """Build the Docker run command with all necessary arguments."""
    
    image_name = f"hololink-demo:{docker_version}"
    
    # Base command
    cmd = ["docker", "run"]
    
    # Add -it only if running in interactive terminal (not Jenkins)
    if sys.stdout.isatty():
        cmd.extend(["-it"])
    
    # Standard flags
    cmd.extend([
        "--rm",
        "--net", "host",
        "--gpus", "all",
        "--runtime=nvidia",
        "--shm-size=1gb",
        "--privileged",
        "--name", container_name,
    ])
    
    # Volume mounts
    volumes = [
        (workspace_root, workspace_root),
        ("/home/lattice", "/home/lattice"),
        ("/sys/bus/pci/devices", "/sys/bus/pci/devices"),
        ("/sys/kernel/mm/hugepages", "/sys/kernel/mm/hugepages"),
        ("/dev", "/dev"),
        ("/tmp/.X11-unix", "/tmp/.X11-unix"),
        ("/tmp/argus_socket", "/tmp/argus_socket"),
        ("/sys/devices", "/sys/devices"),
        ("/var/nvidia/nvcam/settings", "/var/nvidia/nvcam/settings"),
    ]
    
    for host_path, container_path in volumes:
        if Path(host_path).exists():
            cmd.extend(["-v", f"{host_path}:{container_path}"])
        else:
            print(f"Warning: Volume {host_path} does not exist, skipping mount")
    
    # Working directory
    cmd.extend(["-w", workspace_root])
    
    # Environment variables
    display = os.environ.get("DISPLAY", ":0")
    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR", "")
    
    env_vars = {
        "NVIDIA_DRIVER_CAPABILITIES": "graphics,video,compute,utility,display",
        "NVIDIA_VISIBLE_DEVICES": "all",
        "DISPLAY": display,
        "XDG_RUNTIME_DIR": xdg_runtime,
        "enableRawReprocess": "2",
    }
    
    for key, value in env_vars.items():
        cmd.extend(["-e", f"{key}={value}"])
    
    # Image name
    cmd.append(image_name)
    
    # Command to run inside container - directly call Python script
    python_cmd = (
        f"cd /home/lattice/HSB/CI_CD/eth_program_bitstream && "
        f"python3 eth_prog_wrapper.py "
        f"--version '{args.version}' "
        f"--bitstream-path '{args.bitstream_path}' "
        f"--peer-ip '{args.peer_ip}' "
        f"--max-saves {args.max_saves}"
    )
    
    if args.md5:
        python_cmd += f" --md5 '{args.md5}'"
    if args.manifest:
        python_cmd += f" --manifest '{args.manifest}'"
    
    cmd.extend(["bash", "-lc", python_cmd])
    
    return cmd


def run_docker_container(cmd: List[str], dry_run: bool = False) -> int:
    """Execute the Docker command and return exit code."""
    
    if dry_run:
        print("\n" + "=" * 90)
        print("DRY RUN - Docker command:")
        print("=" * 90)
        print(" ".join(cmd))
        print("=" * 90 + "\n")
        return 0
    
    print("\n" + "=" * 90)
    print("Invoking Docker container for bitstream programming...")
    print("=" * 90 + "\n")
    
    try:
        result = subprocess.run(cmd, check=False)
        return result.returncode
    except KeyboardInterrupt:
        print("\n\nInterrupted by user (Ctrl+C)")
        return 130
    except Exception as e:
        print(f"\nError running Docker container: {e}")
        return 1


def print_summary(exit_code: int) -> None:
    """Print execution summary."""
    print("\n" + "=" * 90)
    if exit_code == 0:
        print("✓ Bitstream programming completed successfully")
    else:
        print(f"✗ Bitstream programming failed with exit code: {exit_code}")
    print("=" * 90 + "\n")


def main() -> int:
    """Main entry point."""
    args = parse_args()
    
    # Print configuration
    print("\n" + "=" * 90)
    print("BITSTREAM PROGRAMMING CONFIGURATION")
    print("=" * 90)
    print(f"Version:         {args.version}")
    print(f"Bitstream Path:  {args.bitstream_path}")
    print(f"MD5:             {args.md5 if args.md5 else '<not provided>'}")
    print(f"Peer IP:         {args.peer_ip}")
    print(f"Max Saves:       {args.max_saves}")
    print(f"Manifest:        {args.manifest if args.manifest else '<auto-generate>'}")
    print(f"Workspace Root:  {args.workspace_root}")
    print("=" * 90 + "\n")
    
    # Check Docker availability
    if not check_docker_available():
        print("Error: Docker is not available or not running")
        return 1
    
    # Get Docker version
    docker_version = get_docker_version(args.workspace_root)
    print(f"Using Docker image: hololink-demo:{docker_version}\n")
    
    # Enable X11 forwarding (Linux only)
    enable_xhost()
    
    # Cleanup existing container
    container_name = "demo_bitstream_prog"
    cleanup_existing_container(container_name)
    
    # Build Docker command
    cmd = build_docker_command(args, args.workspace_root, docker_version, container_name)
    
    # Run Docker container
    exit_code = run_docker_container(cmd, dry_run=args.dry_run)
    
    # Print summary
    if not args.dry_run:
        print_summary(exit_code)
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
