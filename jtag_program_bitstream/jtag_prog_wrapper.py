#!/usr/bin/env python3
"""
JTAG Bitstream Programmer Wrapper
Coordinates local FPGA programming via USB JTAG, then triggers Docker verification on Jetson Orin.
"""
import logging
import argparse
import subprocess
import sys
import os
from pathlib import Path
from typing import Optional, Tuple
import time

# Add parent scripts directory to path for imports
_script_dir = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(_script_dir))

import control_tapo_kasa
import terminal_print_formating as tpf



class JTAGProgrammerWrapper:
    """Wrapper for JTAG FPGA programming with remote Docker verification."""
    
    def __init__(self, verbose: bool = False):
        """
        Initialize wrapper.
        
        Args:
            verbose: Enable verbose output
        """
        self.verbose = verbose
        self.script_dir = Path(__file__).parent
        self.radiant_programmer = self.script_dir / "radiant_usb_programmer.py"
        
    def _print_header(self, text: str):
        """Print formatted header."""
        print("\n" + "=" * 90)
        print(f"  {text}")
        print("=" * 90)
    
    def _print_info(self, text: str):
        """Print info message."""
        logging.info(f"{text}")
    
    def _print_success(self, text: str):
        """Print success message."""
        logging.info(f"[✓] {text}")
    
    def _print_error(self, text: str):
        """Print error message."""
        logging.error(f"[✗] {text}")
    
    def _print_warning(self, text: str):
        """Print warning message."""
        logging.warning(f"[⚠] {text}")
    
    def program_fpga(
        self,
        bitstream_path: str,
        operation: str = "Erase,Program,Verify",
        config: Optional[str] = None,
        device_type: Optional[str] = None,
        max_retries: int = 3
    ) -> Tuple[bool, str]:
        """
        Program FPGA via radiant_usb_programmer.py.
        
        Args:
            bitstream_path: Path to bitstream file
            operation: Programming operation type
            config: Path to configuration file
            device_type: Device type ('cpnx' or 'avant')
            max_retries: Maximum retry attempts
            
        Returns:
            (success, results_dir)
        """
        self._print_header("FPGA Programming via USB JTAG")
        
        # Build command
        cmd = [
            sys.executable,
            str(self.radiant_programmer),
            "--bitstream", bitstream_path,
            "--operation", operation,
            "--max-retries", str(max_retries),
        ]
        
        if config:
            cmd.extend(["--config", config])
        
        if device_type:
            cmd.extend(["--device-type", device_type])
        
        if self.verbose:
            cmd.append("--verbose")
        
        self._print_info(f"Executing: {' '.join(cmd)}")
        
        try:
            result = subprocess.run(cmd, check=False, capture_output=False, text=True)

            if result.returncode == 0:
                self._print_success("FPGA programming successful!")
                return True, ""
            else:
                self._print_error("FPGA programming failed!")
                return False, ""
        
        except Exception as e:
            self._print_error(f"Exception during programming: {e}")
            return False, ""
    

    def trigger_orin_verification(
        self,
        orin_ip: str,
        version: str,
        bitstream_path: str,
        peer_ip: str,
        md5: str = "",
        manifest: str = "",
        max_saves: int = 1,
        timeout: int = 600
    ) -> bool:
        """
        Trigger Docker on Jetson Orin for verification.
        
        Uses SSH to execute program_bitstream_docker.py on the Jetson Orin.
        
        Args:
            orin_ip: IP address of Jetson Orin
            version: Bitstream version
            bitstream_path: Path to bitstream file
            peer_ip: Hololink device IP address
            md5: MD5 checksum (optional)
            manifest: Manifest file path (optional)
            max_saves: Maximum number of images to save
            timeout: Command timeout in seconds
            
        Returns:
            True if successful, False otherwise
        """
        self._print_header("Triggering Jetson Orin Docker Verification")
        
        # Build remote command
        remote_cmd = [
            "python3",
            "/home/lattice/HSB/CI_CD/scripts/verify_camera_imx258.py",
            "--camera-ip", version,
            "--camera-mode", bitstream_path,
            "--save-images", peer_ip,
            "--max-saves", str(max_saves),
            "--save-dir", dir
        ]
        
        if md5:
            remote_cmd.extend(["--md5", md5])
        
        if manifest:
            remote_cmd.extend(["--manifest", manifest])
        
        # Build SSH command
        ssh_cmd = ["ssh", f"lattice@{orin_ip}"] + remote_cmd
        
        self._print_info(f"Target Orin IP: {orin_ip}")
        self._print_info(f"Executing remote command: {' '.join(remote_cmd)}")
        
        try:
            result = subprocess.run(
                ssh_cmd,
                timeout=timeout,
                check=False,
                capture_output=False,
                text=True
            )
            
            if result.returncode == 0:
                self._print_success("Jetson Orin verification completed successfully!")
                return True
            else:
                self._print_error(f"Jetson Orin verification failed with exit code: {result.returncode}")
                return False
        
        except subprocess.TimeoutExpired:
            self._print_error(f"Remote command timeout after {timeout} seconds")
            return False
        except FileNotFoundError:
            self._print_error("SSH not found. Ensure SSH client is installed and in PATH")
            return False
        except Exception as e:
            self._print_error(f"Exception during remote execution: {e}")
            return False
    
    def trigger_orin_docker_verify(
        self,
        orin_ip: str,
        peer_ip: str,
        camera_id: int = 0,
        camera_mode: int = 4,
        frame_limit: int = 300,
        timeout_sec: int = 10,
        min_fps: float = 30.0,
        max_saves: int = 1,
        save_images: bool = False,
        timeout: int = 600,
        workspace_root: str = "/home/lattice/HSB/holoscan-sensor-bridge"
    ) -> bool:
        """
        Trigger Docker on Jetson Orin to run verify_camera_imx258.py.
        
        Uses SSH to execute Docker on Orin with proper image version from VERSION file.
        Mirrors the pattern from program_bitstream_docker.py.
        
        Args:
            orin_ip: IP address of Jetson Orin
            peer_ip: Hololink device IP address (camera)
            camera_id: Camera index (0 or 1)
            camera_mode: Camera mode to test
            frame_limit: Number of frames to capture for verification
            timeout_sec: Timeout for frame capture in seconds
            min_fps: Minimum acceptable FPS
            max_saves: Maximum number of images to save
            save_images: Whether to save captured frame images
            timeout: SSH command timeout in seconds
            workspace_root: Root directory of holoscan-sensor-bridge workspace
            
        Returns:
            True if successful, False otherwise
        """
        self._print_header("Triggering Jetson Orin Docker Verification")
        
        # Build a single SSH command that reads VERSION and runs both verification scripts in one container
        # This avoids multiple password prompts by combining into one SSH call
        combined_cmd = (
            f"VERSION=$(cat {workspace_root}/VERSION) && "
            f"docker run --rm --net host --gpus all --runtime=nvidia "
            f"--shm-size=1gb --privileged "
            f"-v {workspace_root}:{workspace_root} "
            f"-v /home/lattice:/home/lattice "
            f"-v /sys/bus/pci/devices:/sys/bus/pci/devices "
            f"-v /sys/kernel/mm/hugepages:/sys/kernel/mm/hugepages "
            f"-v /dev:/dev "
            f"-v /tmp/.X11-unix:/tmp/.X11-unix "
            f"-v /tmp/argus_socket:/tmp/argus_socket "
            f"-v /sys/devices:/sys/devices "
            f"-v /var/nvidia/nvcam/settings:/var/nvidia/nvcam/settings "
            f"-w /home/lattice/HSB/CI_CD "
            f"-e NVIDIA_DRIVER_CAPABILITIES=graphics,video,compute,utility,display "
            f"-e NVIDIA_VISIBLE_DEVICES=all "
            f"-e DISPLAY=:0 "
            f"-e enableRawReprocess=2 "
            f"hololink-demo:$VERSION "
            f"bash -c '"
            f"python3 /home/lattice/HSB/CI_CD/scripts/verify_camera_imx258.py "
            f"--camera-ip {peer_ip} "
            f"--camera-id {camera_id} "
            f"--camera-mode {camera_mode} "
            f"--frame-limit {frame_limit} "
            f"--timeout {timeout_sec} "
            f"--min-fps {min_fps} "
            f"--max-saves {max_saves} "
            f"--save-images "
            f"--save-dir /home/lattice/HSB/CI_CD"
        )
        
        if save_images:
            combined_cmd += " --save-images"
        
        # Chain with eth speed verification
        combined_cmd += (
            f" && python3 /home/lattice/HSB/CI_CD/scripts/verify_eth_speed.py"
            f"'"
        )
        
        # Single SSH command with key-based auth (non-interactive, no password prompt)
        ssh_cmd = [
            "ssh",
            "-o", "BatchMode=yes",                    # Non-interactive, key auth only
            "-o", "StrictHostKeyChecking=accept-new", # Auto-accept new host keys
            f"lattice@{orin_ip}",
            combined_cmd
        ]
        
        self._print_info(f"Target Orin IP: {orin_ip}")
        self._print_info(f"Peer (Camera) IP: {peer_ip}")
        self._print_info(f"Camera Mode: {camera_mode}, Frame Limit: {frame_limit}")
        self._print_info("Starting Docker container on Orin for verification...")
        
        try:
            result = subprocess.run(
                ssh_cmd,
                timeout=timeout,
                check=False,
                capture_output=False,
                text=True
            )
            
            if result.returncode == 0:
                self._print_success("Jetson Orin Docker verification completed successfully!")
                return True
            else:
                self._print_error(f"Docker verification failed with exit code: {result.returncode}")
                return False
        
        except subprocess.TimeoutExpired:
            self._print_error(f"Remote command timeout after {timeout} seconds")
            return False
        except FileNotFoundError:
            self._print_error("SSH not found. Ensure SSH client is installed and in PATH")
            return False
        except Exception as e:
            self._print_error(f"Exception during remote execution: {e}")
            return False

    def copy_images_from_orin(self, orin_ip: str, remote_dir: str, local_dir: str, extensions: list = None, timeout: int = 60) -> bool:
        """Copy multiple file types from Orin."""
        if extensions is None:
            extensions = ["*.npy","*.png"]  # Copy both raw and preview images
        
        os.makedirs(local_dir, exist_ok=True)
        
        for ext in extensions:
            self._print_info(f"Copying {ext} files...")
            
            scp_cmd = [
                "scp", "-r",
                "-o", "BatchMode=yes",
                "-o", "StrictHostKeyChecking=accept-new",
                f"lattice@{orin_ip}:{remote_dir}/{ext}",
                local_dir
            ]
            
            result = subprocess.run(scp_cmd, timeout=timeout, check=False, 
                                capture_output=True, text=True)
            
            if result.returncode == 0:
                self._print_success(f"Copied {ext} files")
            else:
                self._print_warning(f"No {ext} files found or copy failed")
        
        return True
    
    def del_images_from_orin(self, orin_ip: str, remote_dir: str, local_dir: str, extensions: list = None, timeout: int = 60) -> bool:
        """Delete multiple file types from Orin."""
        if extensions is None:
            extensions = ["*.npy","*.png"]  # Copy both raw and preview images
              
        for ext in extensions:
            self._print_info(f"Copying {ext} files...")
            
            delete_cmd = [
                "ssh",
                "-o", "BatchMode=yes",
                "-o", "StrictHostKeyChecking=accept-new",
                f"lattice@{orin_ip}",
                f"rm -rf {remote_dir}/{ext}"
            ]
            
            result = subprocess.run(delete_cmd, timeout=timeout, check=False, 
                                capture_output=True, text=True)
            
            if result.returncode == 0:
                self._print_success(f"Deleted {ext} files")
            else:
                self._print_warning(f"No {ext} files found or delete failed")
        
        return True


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="JTAG FPGA Programmer with Jetson Orin Docker Verification",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Program CPNX FPGA only
  python jtag_prog_wrapper.py --bitstream bitstream.bit --peer-ip 192.168.0.2

  # Program Avant FPGA only
  python jtag_prog_wrapper.py --bitstream bitstream.bit --peer-ip 192.168.0.2 --device-type avant

  # Program FPGA and trigger Orin verification
  python jtag_prog_wrapper.py --bitstream bitstream.bit --peer-ip 192.168.0.2 \\
    --version "0104_2507" --orin-ip 192.168.0.3 --device-type avant

  # Program with fast configuration
  python jtag_prog_wrapper.py --bitstream bitstream.bit --peer-ip 192.168.0.2 \\
    --device-type avant --fast

  # Verbose mode with all steps
  python jtag_prog_wrapper.py --bitstream bitstream.bit --peer-ip 192.168.0.2 \\
    --version "0104_2507" --orin-ip 192.168.0.3 --device-type avant --verbose
        """
    )
    
    # FPGA programming arguments
    parser.add_argument(
        "--bitstream",
        type=str,
        required=True,
        help="Path to bitstream file (.bit)"
    )
    parser.add_argument(
        "--operation",
        type=str,
        default="Erase,Program,Verify",
        choices=["Erase,Program,Verify", "Fast Configuration", "Program,Verify", "Erase,Program"],
        help="Programming operation (default: Erase,Program,Verify)"
    )
    parser.add_argument(
        "--device-type",
        type=str,
        choices=["cpnx", "avant"],
        help="Device type (cpnx=LFCPNX/SRAM, avant=LAV-AT/SPI). Overrides config if provided"
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Use Fast Configuration (quick, no verify)"
    )
    parser.add_argument(
        "--config",
        type=str,
        help="Path to radiant programmer configuration file"
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Maximum retry attempts on cable errors (default: 3)"
    )
    
    # Jetson Orin verification arguments
    parser.add_argument(
        "--host-ip",
        type=str,
        required=True,
        help="IP address of Nvidia Device (triggers Docker verification if provided)"
    )
    parser.add_argument(
        "--peer-ip",
        type=str,
        default="192.168.0.2",
        help="Hololink device IP address (required if --host-ip provided)"
    )
    parser.add_argument(
        "--camera-mode",
        type=int,
        default=4,
        help="Camera mode to test (default: 4, which is 60fps_new)"
    )
    parser.add_argument(
        "--frame-limit",
        type=int,
        default=300,
        help="Number of frames to capture during verification (default: 300)"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="Timeout for frame capture in seconds (default: 10)"
    )
    parser.add_argument(
        "--min-fps",
        type=float,
        default=30.0,
        help="Minimum acceptable FPS (default: 30.0)"
    )
    parser.add_argument(
        "--max-saves",
        type=int,
        default=1,
        help="Maximum number of images to save during verification (default: 1)"
    )
    parser.add_argument(
        "--save-images",
        action="store_true",
        default=False,
        help="Save captured frame images"
    )
    parser.add_argument(
        "--orin-timeout",
        type=int,
        default=600,
        help="Timeout for Orin remote execution in seconds (default: 600)"
    )
    parser.add_argument(
        "--use-shell-method",
        action="store_true",
        help="(Deprecated) Use shell method instead of Docker"
    )
    
    # General arguments
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    
    return parser.parse_args()



def main() -> Tuple[bool, bool, bool]:
    """Main entry point."""
    args = parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(levelname)s: %(message)s'
    )
    
    try:
        os.system("cd /home/lattice/HSB/CI_CD")

        os.system('cls' if os.name == 'nt' else 'clear')
        tpf.print_start()

        prog_start = time.time()

        wrapper = JTAGProgrammerWrapper(verbose=args.verbose)
        
        # Step 1: Program FPGA via USB JTAG
        success, results_dir = wrapper.program_fpga(
            bitstream_path=args.bitstream,
            operation="Fast Configuration" if args.fast else args.operation,
            config=args.config,
            device_type=args.device_type,
            max_retries=args.max_retries
        )
        
        if not success:
            wrapper._print_error("FPGA programming failed. Aborting workflow.")
            return 1
        
        prog_end = time.time()

        logging.info("Bitstream programming completed.")
        logging.info(f"Total programming time: {prog_end - prog_start:.2f} seconds")
        program_success = True
    
        logging.info("Power cycling the Hololink device to apply new bitstream...")
        sys.argv = ([
            "control_tapo_kasa.py",
            "--toggle_off", "4",
        ])
        control_tapo_kasa.main()

        logging.info("Shutting down for 3 seconds...")
        time.sleep(3) # wait for device to power cycle

        sys.argv = ([
            "control_tapo_kasa.py",
            "--toggle_on", "4",
        ])
        control_tapo_kasa.main()

        logging.info("Waiting for device to boot up for 6 seconds...")
        time.sleep(6) # wait for device to boot up

        powercycle_ok = True
        logging.info("Hololink device power cycled successfully.")

        # Step 2: Trigger Jetson Orin verification (if requested)
        if args.orin_ip:
            # Validate required arguments for Orin
            if not args.peer_ip:
                wrapper._print_error("--peer-ip is required when using --orin-ip")
                return 1
            
            wrapper._print_info("Waiting 3 seconds before triggering Orin...")
            time.sleep(3)
            
            # Trigger Docker verification on Orin
            orin_success = wrapper.trigger_orin_docker_verify(
                orin_ip=args.orin_ip,
                peer_ip=args.peer_ip,
                camera_id=0,
                camera_mode=args.camera_mode,
                frame_limit=args.frame_limit,
                timeout_sec=args.timeout,
                min_fps=args.min_fps,
                max_saves=args.max_saves,
                save_images=args.save_images,
                timeout=args.orin_timeout,
                workspace_root="/home/lattice/HSB/holoscan-sensor-bridge"
            )
            
            if not orin_success:
                wrapper._print_error("Orin verification failed!")
                return 1
        
        if args.orin_ip and orin_success:
            wrapper._print_info("Retrieving captured images from Orin...")
            time.sleep(2)  # Give filesystem time to flush
                
            tmp_file = os.path.join(Path.cwd().parent, "results", "temp.txt")
            
            if os.path.exists(tmp_file):
                 with open(tmp_file, "r") as f:
                    res_dir = f.read()
                    print(f"Results directory: {res_dir}")
                      
            if os.path.isdir(res_dir):
                copy_success = wrapper.copy_images_from_orin(
                orin_ip=args.orin_ip,
                remote_dir="/home/lattice/HSB/CI_CD",  # Where verify_camera_imx258.py saves images
                local_dir=os.path.expanduser(res_dir),  # Or your preferred path
                timeout=60
                )
                
                if copy_success:
                    
                    del_success = wrapper.del_images_from_orin(
                        orin_ip=args.orin_ip,
                        remote_dir="/home/lattice/HSB/CI_CD",  # Where verify_camera_imx258.py saves images
                        local_dir=os.path.expanduser(res_dir),  # Or your preferred path
                        timeout=60
                    )

                    if del_success:
                        wrapper._print_success("Captured images retrieved and deleted from Orin successfully")
                    else:
                        wrapper._print_warning("Could not delete images from Orin after retrieval")
                else:
                    wrapper._print_warning("Could not retrieve images, but verification passed")

            else:
                logging.error(f"Directory does NOT exist")

            os.remove(tmp_file)

        # Success!
        wrapper._print_header("Complete Workflow Status")
        wrapper._print_success("FPGA programming completed successfully!")
        if args.orin_ip:
            wrapper._print_success("Jetson Orin verification completed successfully!")
        print("=" * 90 + "\n")

        tpf.print_end()
        
        return program_success, powercycle_ok, orin_success
    
    except KeyboardInterrupt:
        print("\n\nInterrupted by user (Ctrl+C)")
        return 0
    except Exception as e:
        print(f"\n[✗] {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return False, False


if __name__ == "__main__":
    sys.exit(main())
