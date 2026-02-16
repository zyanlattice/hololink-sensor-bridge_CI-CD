
import os
import argparse
import sys
import time
from pathlib import Path
from datetime import datetime

# Add parent scripts directory to path for imports
_script_dir = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(_script_dir))

import control_tapo_kasa
import verify_camera_imx258
import verify_eth_speed
import terminal_print_formating as tpf

def find_holoscan_dir():
    """
    Dynamically find the holoscan-sensor-bridge directory.
    Searches from the current script location.
    This script is in /home/(user)/HSB/CI_CD/eth_program_bitstream/
    Target is /home/(user)/HSB/holoscan-sensor-bridge/
    """
    # Start from the current script's directory
    current_dir = Path(__file__).resolve().parent
    
    # Go up to HSB directory: eth_program_bitstream -> CI_CD -> HSB
    hsb_dir = current_dir.parent.parent
    holoscan_path = hsb_dir / "holoscan-sensor-bridge"
    
    if holoscan_path.exists() and holoscan_path.is_dir():
        return holoscan_path
    
    # Fallback: try common paths if dynamic search fails
    fallback_paths = [
        Path("/home/lattice/HSB/holoscan-sensor-bridge"),
        Path("/home/orin/HSB/holoscan-sensor-bridge"),
        Path("/home/thor/HSB/holoscan-sensor-bridge"),
    ]
    for path in fallback_paths:
        if path.exists() and path.is_dir():
            return path
    
    # Return first fallback path even if it doesn't exist (will fail with clear error)
    return fallback_paths[0]

def find_ci_cd_dir():
    """
    Dynamically find the CI_CD directory.
    This script is in /home/(user)/HSB/CI_CD/eth_program_bitstream/
    """
    # Go up one level from current script directory
    return Path(__file__).resolve().parent.parent

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Programme bitstream to FPGA via Hololink Bitstream Programmer")
    parser.add_argument("--bitstream-path", type=str, help="Path to the bitstream file, can be url or local path", required=True)
    parser.add_argument("--version", type=str, help="Bitstream version", required=True)
    parser.add_argument("--md5", type=str, help="Bitstream MD5 checksum", required=False) # Make optional for testing, to change to required later
    parser.add_argument("--manifest", type=str, help="File name for generated manifest", required=False)
    parser.add_argument("--fpga-uuid", type=str, help="FPGA UUID", default=None)
    parser.add_argument("--peer-ip", type=str, help="Hololink device IP to query FPGA UUID", default=None)
    parser.add_argument("--max-saves", type=int, help="Maximum number of images to save during verification (0 = no images, just test frames)", default=1)
    return parser.parse_args()

def get_curr_path() -> str:
    """Get the directory of the current script."""
    return str(Path(__file__).parent)

def get_parent_path() -> str:
    """Get the parent directory of the current script."""
    return str(Path(__file__).parent.parent)

def create_results_dir() -> Path:
    """Create timestamped results directory."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_dir = Path(__file__).parent.parent / "results" / f"eth_rem_programming_{timestamp}"
    results_dir.mkdir(parents=True, exist_ok=True)
    return results_dir

def main() -> tuple[bool, bool, bool, bool, bool, bool, bool, bool]:
    docker_ok = True

    # Get dynamic paths
    holoscan_dir = find_holoscan_dir()
    ci_cd_dir = find_ci_cd_dir()
    
    os.system(f"cd {ci_cd_dir}")

    os.system('cls' if os.name == 'nt' else 'clear')
    #tpf.print_img2char(f"{ci_cd_dir}/images/Lattice_Logo_Color_TransparentBG.png")
    tpf.print_start()

    # Create timestamped results directory
    results_dir = create_results_dir()
    print(f"[INFO] Results will be saved to: {results_dir}")

    args = parse_args()
 
    os.system("echo Starting Bitstream Programmer Wrapper Script")
    os.system("echo Locating bitstream file...")
    bitstream_path = args.bitstream_path 
    version = args.version 
    md5 = args.md5 
    manifest = args.manifest 
    fpga_uuid = args.fpga_uuid 
    peer_ip = args.peer_ip 
    max_saves = args.max_saves

    fpga_ok = False
    manifest_ok = False
    bitstream_ok = False


    if not md5:  # Checks both None and empty string
        missing = [name for name, val in (("--bitstream-path", bitstream_path), ("--version", version)) if not val]
        print("Md5 not provided, skipping MD5 validation.")
    else:
        missing = [name for name, val in (("--bitstream-path", bitstream_path), ("--version", version), ("--md5", md5)) if not val]
    if missing:
        print("Exception thrown: Missing required connection info: " + ", ".join(missing))
        raise SystemExit(2)
    
    
    if ((fpga_uuid is None) or (len(fpga_uuid) < 1)) and (peer_ip is None):
        print("Exception thrown: At least one --fpga-uuid or --peer-ip must be specified.")
        raise SystemExit(2)
    if (peer_ip is not None) and ((fpga_uuid is  None) or (len(fpga_uuid) < 1)):
        # Query the device for its FPGA UUID
        from read_metadata import search_metadata_value
        uuid = search_metadata_value(peer_ip, "fpga_uuid")
        if uuid is None:
            print(f"Exception thrown: Unable to query FPGA UUID from device at {peer_ip}. Please check connectivity and try again.")
            raise SystemExit(2)
        fpga_uuid = [ uuid ]
        fpga_ok = True

    #Debug
    #print("FPGA UUID:", fpga_uuid[0])
    print("FPGA UUID:", fpga_uuid)

    ori_argv = sys.argv.copy()

    print("Generating manifest file... ")
    from generate_manifest_md5 import main as generate_manifest_main
    
    sys.argv = ([
        "generate_manifest_md5.py", # argv[0] - script name required
        "--version", version,
        "--cpnx-file", bitstream_path,
        "--fpga-uuid", fpga_uuid[0] if isinstance(fpga_uuid, list) else fpga_uuid,
        "--peer-ip", peer_ip 
    ])
    if md5:  # Only add --md5 if it has a value
        sys.argv.extend(["--md5", md5])
    if manifest:
        sys.argv.extend(["--manifest", manifest])
    tmp, bitstream_ok = generate_manifest_main()
    
    sys.argv = ori_argv

    manifest_file = manifest if manifest else "new_manifest.yaml"
    # Check original location first
    original_manifest_path = os.path.join(Path.cwd(), manifest_file)
    manifest_path = os.path.join(str(results_dir), manifest_file)
    
    time.sleep(0.2)  # wait for file system to catch up

    # If manifest was generated in original location, move it to results directory
    if os.path.isfile(original_manifest_path):
        import shutil
        shutil.move(original_manifest_path, manifest_path)
        print(f"Manifest file moved to results directory: {manifest_path}")
    
    if not os.path.isfile(manifest_path):
        print(f"Exception thrown: Manifest file {manifest_path} not found.")
        raise SystemExit(2)
    else:
        print(f"Manifest file created successfully located at {manifest_path}")
        manifest_ok = True

    print("Invoking bitstream programmer...")
    print("The process takes 20 to 30 minutes to complete.")
    prog_start = time.time()
    os.system(f"cd {holoscan_dir} && program_lattice_cpnx_versa --accept-eula --skip-power-cycle {manifest_path}" )
    prog_end = time.time()

    time.sleep(0.2) # soak time

    print("Bitstream programming completed.")
    print(f"Total programming time: {prog_end - prog_start:.2f} seconds")
    program_success = True
 
    print("Power cycling the Hololink device to apply new bitstream...")
    sys.argv = ([
        "control_tapo_kasa.py",
        "--toggle_off", "4",
    ])
    control_tapo_kasa.main()

    print("Shutting down for 3 seconds...")
    time.sleep(3) # wait for device to power cycle

    sys.argv = ([
        "control_tapo_kasa.py",
        "--toggle_on", "4",
    ])
    control_tapo_kasa.main()

    print("Waiting for device to boot up for 6 seconds...")
    time.sleep(6) # wait for device to boot up

    powercycle_ok = True
    print("Hololink device power cycled successfully.")

    # Always restore argv before calling a new script
    sys.argv = ori_argv.copy()
    
    print("Running quick functional test...")
    sys.argv = [
        "verify_camera_imx258.py",
        "--camera-ip", peer_ip,
        "--max-saves", str(max_saves),
        "--save-dir", str(results_dir)
    ]
    
    # Only add --save-images flag if max_saves > 0
    if max_saves > 0:
        sys.argv.append("--save-images")

    # Initialize variables before try block
    ethspeed_ok = False
    camera_ok = False

    camera_ok = verify_camera_imx258.main()

    # Always restore argv before calling a new script
    sys.argv = ori_argv.copy()
    
    print("Running quick functional test...")
    sys.argv = [
        "verify_eth_speed.py",
        "--camera-ip", peer_ip
    ]

    ethspeed_ok = verify_eth_speed.main()[0]

    tpf.print_end()
    print("Bitstream programmer wrapper script completed.")
    print(f"\n[INFO] All results saved to: {results_dir}")

    return docker_ok, bitstream_ok, fpga_ok, manifest_ok, program_success, powercycle_ok, ethspeed_ok, camera_ok

if __name__ == "__main__":
    res = main()
    print(f"Docker OK: {res[0]}, Bitstream OK: {res[1]}, FPGA OK: {res[2]}, Manifest OK: {res[3]}, Program Success: {res[4]}, Powercycle OK: {res[5]}, Ethspeed OK: {res[6]}, Camera OK: {res[7]}")