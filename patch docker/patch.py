#!/usr/bin/env python3
"""
Docker Dockerfile Patcher
Patches Dockerfile.demo to add missing pytest plugins for CI/CD testing.

Usage:
    python patch.py                                               # Auto-detect HSB workspace
    python patch.py <path_to_Dockerfile.demo>                     # Explicit path
    
Example:
    python patch.py                                               # Uses HSB/holoscan-sensor-bridge/docker/Dockerfile.demo
    python patch.py ~/HSB/holoscan-sensor-bridge/docker/Dockerfile.demo
"""

import argparse
import sys
from pathlib import Path
import shutil
from datetime import datetime


def find_hsb_root(start_path: Path = None) -> Path:
    """
    Find HSB folder by searching current directory and parent directories.
    
    Args:
        start_path: Starting directory (defaults to script location)
        
    Returns:
        Path to HSB folder
        
    Raises:
        FileNotFoundError: If HSB folder not found in hierarchy
    """
    if start_path is None:
        start_path = Path(__file__).parent
    
    current = start_path.resolve()
    
    # Search up to 5 levels
    for _ in range(5):
        # Check if current directory is named HSB
        if current.name == "HSB":
            return current
        
        # Check if HSB exists as a subdirectory
        hsb_path = current / "HSB"
        if hsb_path.exists() and hsb_path.is_dir():
            return hsb_path
        
        # Move to parent
        if current.parent == current:  # Reached root
            break
        current = current.parent
    
    raise FileNotFoundError(
        "Could not find HSB folder. Please ensure you're running from within the HSB workspace "
        "or provide the explicit path to Dockerfile.demo"
    )


def backup_file(file_path: Path) -> Path:
    """Create a backup of the original file."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = file_path.with_suffix(f'.demo.backup_{timestamp}')
    shutil.copy2(file_path, backup_path)
    print(f"✓ Backup created: {backup_path}")
    return backup_path


def patch_dockerfile(file_path: Path, dry_run: bool = False) -> bool:
    """
    Patch Dockerfile.demo to add missing pytest plugins.
    
    Changes:
    - Line: RUN pip3 install pytest pytest-timeout
    - To:   RUN pip3 install pytest pytest-timeout pytest-html pytest-metadata pytest-json-report pytest-xdist
    
    Returns:
        True if patched successfully, False otherwise
    """
    
    if not file_path.exists():
        print(f"✗ Error: File not found: {file_path}")
        return False
    
    # Read the file
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Define the search and replace strings
    old_line = "RUN pip3 install pytest pytest-timeout"
    new_line = "RUN pip3 install pytest pytest-timeout pytest-html pytest-metadata"
    
    # Check if already patched
    if new_line in content:
        print("✓ Dockerfile already patched (pytest plugins already installed)")
        return True
    
    # Check if old line exists
    if old_line not in content:
        print(f"✗ Error: Could not find expected line in Dockerfile:")
        print(f"  Expected: {old_line}")
        print(f"  This file may have been modified or is not the expected version.")
        return False
    
    # Apply patch
    patched_content = content.replace(old_line, new_line)
    
    if dry_run:
        print("\n" + "=" * 80)
        print("DRY RUN - Changes that would be applied:")
        print("=" * 80)
        print(f"- {old_line}")
        print(f"+ {new_line}")
        print("=" * 80 + "\n")
        return True
    
    # Create backup before modifying
    backup_path = backup_file(file_path)
    
    # Write patched content
    try:
        with open(file_path, 'w') as f:
            f.write(patched_content)
        print(f"✓ Successfully patched: {file_path}")
        print(f"\nAdded pytest plugins:")
        print(f"  - pytest-html       (HTML test reports)")
        print(f"  - pytest-metadata   (test metadata support)")
        print(f"  - pytest-json-report (JSON test reports)")
        return True
    except Exception as e:
        print(f"✗ Error writing patched file: {e}")
        print(f"  Restoring from backup: {backup_path}")
        shutil.copy2(backup_path, file_path)
        return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Patch Dockerfile.demo to add missing pytest plugins",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Auto-detect HSB workspace and patch Dockerfile
  python patch.py
  
  # Patch specific Dockerfile
  python patch.py ~/HSB/holoscan-sensor-bridge/docker/Dockerfile.demo
  
  # Dry run to see what would be changed
  python patch.py --dry-run
  
  # After patching, rebuild Docker image
  cd ~/HSB/holoscan-sensor-bridge/docker
  ./build.sh --igpu  # or --dgpu depending on platform
        """
    )
    
    parser.add_argument("dockerfile", type=str, nargs='?', default=None,
                       help="Path to Dockerfile.demo to patch (default: auto-detect from HSB folder)")
    parser.add_argument("--dry-run", action="store_true",
                       help="Show what would be changed without modifying the file")
    
    args = parser.parse_args()
    
    # Determine Dockerfile path
    if args.dockerfile:
        # User provided explicit path
        dockerfile_path = Path(args.dockerfile).resolve()
    else:
        # Auto-detect from HSB folder
        try:
            hsb_root = find_hsb_root()
            dockerfile_path = hsb_root / "holoscan-sensor-bridge" / "docker" / "Dockerfile.demo"
            print(f"Auto-detected HSB root: {hsb_root}")
        except FileNotFoundError as e:
            print(f"✗ Error: {e}")
            return 1
    
    print("=" * 80)
    print("Docker Dockerfile Patcher")
    print("=" * 80)
    print(f"Target file: {dockerfile_path}")
    print(f"Mode:        {'DRY RUN' if args.dry_run else 'APPLY PATCH'}")
    print("=" * 80 + "\n")
    
    # Apply patch
    success = patch_dockerfile(dockerfile_path, dry_run=args.dry_run)
    
    if success:
        if not args.dry_run:
            print("\n" + "=" * 80)
            print("✓ Patch applied successfully!")
            print("=" * 80)
            print("\nNext steps:")
            print("1. Rebuild Docker image:")
            print(f"   cd {dockerfile_path.parent}")
            print("   ./build.sh --igpu  # or --dgpu for discrete GPU")
            print("\n2. Verify pytest plugins are installed:")
            print("   docker run --rm hololink-demo:<VERSION> pip3 list | grep pytest")
            print("=" * 80 + "\n")
        return 0
    else:
        print("\n✗ Patch failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
