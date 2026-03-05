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

def detect_workspace_root() -> str:
    """
    Auto-detect workspace root based on current script location or common paths.
    
    Priority:
    1. Derive from current script location (e.g., /home/thor/HSB/CI_CD/eth_program_bitstream -> /home/thor/HSB/holoscan-sensor-bridge)
    2. Check common paths: /home/lattice, /home/orin, /home/thor
    """
    # Try to derive from current script location
    # Script is at: /home/{user}/HSB/CI_CD/eth_program_bitstream/eth_prog_docker_wrapper.py
    # Target is:    /home/{user}/HSB/holoscan-sensor-bridge
    script_path = Path(__file__).resolve()
    try:
        # Go up: eth_prog_docker_wrapper.py -> eth_program_bitstream -> CI_CD -> HSB
        hsb_dir = script_path.parent.parent.parent
        workspace = hsb_dir / "holoscan-sensor-bridge"
        if workspace.exists():
            return str(workspace)
    except:
        pass
    
    # Fallback: Check common user home directories
    possible_users = ["lattice", "orin", "thor"]
    for user in possible_users:
        workspace = Path(f"/home/{user}/HSB/holoscan-sensor-bridge")
        if workspace.exists():
            return str(workspace)
    
    # Default fallback (will likely fail but provides clear error)
    return "/home/lattice/HSB/holoscan-sensor-bridge"

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
    parser.add_argument("--workspace-root", type=str, default=None, help="Root directory of the holoscan-sensor-bridge workspace (auto-detected if not specified)")
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
        print("Enabling X11 access control (xhost +)...")
        try:
            result = subprocess.run(["xhost", "+"], check=False, capture_output=True, text=True)
            if result.returncode == 0:
                print("✓ X11 access control enabled\n")
            else:
                print(f"Warning: xhost command returned code {result.returncode}\n")
        except FileNotFoundError:
            print("Warning: xhost not found, X11 forwarding may not work\n")


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
    # Extract home directory dynamically from workspace_root
    # e.g., /home/orin/HSB/holoscan-sensor-bridge -> /home/orin
    home_dir = str(Path(workspace_root).parent.parent)
    
    volumes = [
        (workspace_root, workspace_root),
        (home_dir, home_dir),
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
    # Find CI_CD directory dynamically based on workspace root
    ci_cd_path = str(Path(workspace_root).parent / "CI_CD" / "eth_program_bitstream")
    
    python_cmd = (
        f"cd {ci_cd_path} && "
        f"python3 -u eth_prog.py "
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
    
    # Auto-detect workspace root if not provided
    if args.workspace_root is None:
        args.workspace_root = detect_workspace_root()
        print(f"Auto-detected workspace root: {args.workspace_root}")
    
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
