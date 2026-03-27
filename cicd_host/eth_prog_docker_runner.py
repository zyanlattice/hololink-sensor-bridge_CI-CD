#!/usr/bin/env python3
"""
SSH wrapper for remote bitstream programming via Docker.
Runs eth_prog_docker_wrapper.py on remote Jetson host.
"""

import argparse
import subprocess
import sys
import time
import yaml
from pathlib import Path
from typing import Dict, Tuple

# Add scripts directory to path for imports
scripts_dir = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(scripts_dir))

import control_relay_dll as relay


def load_config(config_path: str = "config.yaml") -> Dict:
    """Load configuration from YAML file."""
    config_file = Path(__file__).parent / config_path
    
    if not config_file.exists():
        print(f"Error: Configuration file not found: {config_file}")
        sys.exit(1)
    
    with open(config_file, 'r') as f:
        return yaml.safe_load(f)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Remote bitstream programming via SSH + Docker",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    # Required arguments
    parser.add_argument("--host-type", type=str, required=True, 
                       choices=['orin', 'thor'],
                       help="Host type to connect to (orin or thor)")
    parser.add_argument("--md5", type=str, required=False, default="", help="Bitstream MD5 checksum (optional)")
    parser.add_argument("--version", type=str, required=True, help="Bitstream version")
    parser.add_argument("--bitstream-path", type=str, required=True, 
                       help="Path to bitstream file (can be local Windows path or just filename)")
    parser.add_argument("--peer-ip", type=str, required=False, default="192.168.0.2", help="Hololink device IP address")
    
    
    # Optional flags
    parser.add_argument("--dry-run", action="store_true",
                       help="Print command without executing")
    
    return parser.parse_args()


def build_remote_command(
    args: argparse.Namespace,
    workspace_root: str,
    username: str
) -> str:
    """Build the command to execute eth_prog_docker_wrapper.py on remote host."""
    
    ci_cd_path = f"{workspace_root}/../CI_CD"
    wrapper_script = f"{ci_cd_path}/eth_program_bitstream/eth_prog_docker_wrapper.py"
    
    # Convert Windows path to Linux path on remote system
    # Extract just the filename from the bitstream path
    bitstream_filename = Path(args.bitstream_path).name
    remote_bitstream_path = f"/home/{username}/HSB/CI_CD/bitstream/{bitstream_filename}"
    
    # Build Python command with -u flag for unbuffered output
    # This ensures output appears in chronological order when run over SSH
    cmd = f"python3 -u {wrapper_script}"
    cmd += f" --version {args.version}"
    cmd += f" --bitstream-path {remote_bitstream_path}"
    cmd += f" --peer-ip {args.peer_ip}"
    cmd += f" --workspace-root {workspace_root}"
    
    return cmd


def build_ssh_command(
    config: Dict,
    host_type: str,
    remote_command: str
) -> Tuple[list, str, str]:
    """Build SSH command to execute remote command."""
    
    if host_type not in config['hosts']:
        print(f"Error: Host type '{host_type}' not found in config")
        sys.exit(1)
    
    host_config = config['hosts'][host_type]
    hostname = host_config['hostname']
    username = host_config['username']
    workspace_root = host_config['workspace_root']
    
    # Build SSH command
    ssh_cmd = [
        "ssh",
        f"{username}@{hostname}",
        remote_command
    ]
    
    return ssh_cmd, hostname, username


def execute_ssh_command(ssh_cmd: list, dry_run: bool = False) -> int:
    """Execute SSH command and return exit code."""
    
    if dry_run:
        print("\n" + "=" * 90)
        print("DRY RUN - SSH command:")
        print("=" * 90)
        print(" ".join(ssh_cmd))
        print("=" * 90 + "\n")
        return 0
    
    print("\n" + "=" * 90)
    print("Executing bitstream programming on remote host...")
    print("=" * 90 + "\n")
    
    try:
        result = subprocess.run(ssh_cmd, check=False)
        return result.returncode
    except KeyboardInterrupt:
        print("\n\nInterrupted by user (Ctrl+C)")
        return 130
    except Exception as e:
        print(f"\nError executing SSH command: {e}")
        return 1


def copy_bitstream_to_remote(
    config: Dict,
    host_type: str,
    local_bitstream_dir: Path,
    dry_run: bool = False
) -> bool:
    """Copy bitstream files from local to remote host."""
    
    host_config = config['hosts'][host_type]
    hostname = host_config['hostname']
    username = host_config['username']
    ssh_key = host_config.get('ssh_key')
    
    # Target directory on remote host
    remote_bitstream_dir = f"/home/{username}/HSB/CI_CD/bitstream"
    remote_path = f"{username}@{hostname}:{remote_bitstream_dir}"
    
    if not local_bitstream_dir.exists():
        print(f"Warning: Local bitstream directory not found: {local_bitstream_dir}")
        return False
    
    print("\n" + "=" * 90)
    print("Copying bitstream files to remote host...")
    print("=" * 90)
    print(f"Local:  {local_bitstream_dir}")
    print(f"Remote: {remote_path}")
    print("=" * 90 + "\n")
    
    if dry_run:
        print("DRY RUN - Would copy bitstream files")
        return True
    
    # Build SCP command to copy entire directory contents (overwrites existing files)
    if ssh_key:
        scp_cmd = [
            "scp", "-r",
            "-i", ssh_key,
            "-o", "StrictHostKeyChecking=accept-new",
            f"{local_bitstream_dir}/*",
            remote_path
        ]
    else:
        scp_cmd = [
            "scp", "-r",
            "-o", "StrictHostKeyChecking=accept-new",
            f"{local_bitstream_dir}/*",
            remote_path
        ]
    
    try:
        print("Copying files...")
        result = subprocess.run(scp_cmd, check=False)
        if result.returncode == 0:
            print("✓ Bitstream files copied successfully\n")
            return True
        else:
            print(f"✗ Failed to copy bitstream files (exit code: {result.returncode})\n")
            return False
    except Exception as e:
        print(f"✗ Error copying bitstream files: {e}\n")
        return False


def print_summary(exit_code: int) -> None:
    """Print execution summary."""
    print("\n" + "=" * 90)
    if exit_code == 0:
        print("✓ Bitstream programming via SSH completed successfully")
    else:
        print(f"✗ Bitstream programming via SSH failed with exit code: {exit_code}")
    print("=" * 90 + "\n")


def main() -> int:
    """Main entry point."""
    args = parse_args()
    
    # Load configuration
    config = load_config()
    
    # Get host configuration
    if args.host_type not in config['hosts']:
        print(f"Error: Host type '{args.host_type}' not found in config")
        return 1
    
    host_config = config['hosts'][args.host_type]
    hostname = host_config['hostname']
    username = host_config['username']
    workspace_root = host_config['workspace_root']
    
    # Print configuration
    print("\n" + "=" * 90)
    print("REMOTE BITSTREAM PROGRAMMING CONFIGURATION")
    print("=" * 90)
    print(f"Target Host:     {args.host_type} ({username}@{hostname})")
    print(f"Version:         {args.version}")
    print(f"Bitstream File:  {Path(args.bitstream_path).name}")
    print(f"Remote Path:     /home/{username}/HSB/CI_CD/bitstream/{Path(args.bitstream_path).name}")
    print(f"Peer IP:         {args.peer_ip}")
    print(f"Workspace Root:  {workspace_root}")
    print("=" * 90 + "\n")
    
    # Copy bitstream files to remote host
    local_bitstream_dir = Path(__file__).parent.parent / "bitstream"
    copy_success = copy_bitstream_to_remote(config, args.host_type, local_bitstream_dir, dry_run=args.dry_run)
    
    if not copy_success and not args.dry_run:
        print("Warning: Failed to copy bitstream files, but continuing anyway...")
    
    # Build remote command
    remote_command = build_remote_command(args, workspace_root, username)
    
    # Build SSH command
    ssh_cmd, _, _ = build_ssh_command(config, args.host_type, remote_command)
    
    # Execute SSH command
    exit_code = execute_ssh_command(ssh_cmd, dry_run=args.dry_run)
    
    print("Performing power cycle on Hololink device...")
    try:
                
        with relay.RelayController():
            print("✓ Device initialized")
            print("  Turning ON relay 4...")
            relay.relay_xon(4)
            print("  ✓ Relay 4 ON")
            time.sleep(3)  # Keep relay on for 3 seconds
            
            print("  Turning OFF relay 4...")
            relay.relay_xoff(4)
            print("  ✓ Relay 4 OFF")
        print("✓ Power cycle completed\n")

    except Exception as e:
        print(f"✗ Error during controlling relay: {e}")

    # Print summary
    if not args.dry_run:
        print_summary(exit_code)
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
