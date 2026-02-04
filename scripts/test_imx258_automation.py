import cmd
from html import parser
import sys
import os
import argparse
import logging
from pathlib import Path
import importlib
import subprocess
import threading
import time


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Master automation script for IMX258 and related tests.")

    # Arguments from verify_reg.py
    parser.add_argument("--peer-ip", type=str, default="192.168.0.2", help="Hololink device IP")
    parser.add_argument("--cpnx1", action="store_true", help="CPNX Versa 1G device")
    parser.add_argument("--cpnx10", action="store_true", help="CPNX Versa 10G device")
    parser.add_argument("--avant10", action="store_true", help="Avant Versa 10G device")
    parser.add_argument("--avant25", action="store_true", help="Avant Versa 25G device")
    parser.add_argument("--hostif", type=int, choices=[1, 2, 3, 4], help="Host interface type (1, 2, 3, or 4)", default=1)

    # Arguments from verify_PTP.py, verify_eth_speed.py, verify_camera_imx258.py, verify_multi_mode_imx258.py
    parser.add_argument("--camera-mode", type=int, default=0, help="Camera mode")
    parser.add_argument("--frame-limit", type=int, default=300, help="Number of frames to capture")
    parser.add_argument("--save-images", action="store_true", default=False, help="Save captured frames as images")
    parser.add_argument("--save-dir", type=str, default="/home/lattice/HSB/CI_CD/test_image_folder", help="Directory to save images")
    parser.add_argument("--holoviz", action="store_true", help="Run with holoviz (GUI)")

    # Arguments from verify_datecode_ver.py
    parser.add_argument("--version", type=str, help="Bitstream file version to verify", required=True)
    parser.add_argument("--datecode", type=str, help="Bitstream datecode to verify", required=True)

    return parser.parse_args()

def main():
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    if ((args.cpnx1 is False) and (args.cpnx10 is False) and (args.avant10 is False) and (args.avant25 is False)):
        print("Exception thrown: At least one device type must be specified.\n" \
        "Use --cpnx1, --cpnx10, --avant10, or --avant25 to specify the device type.")
        raise SystemExit(2)

    # Run verify_device_detection.py
    logging.info("Running device detection test...")
    dev_detect_cmd = [
        sys.executable,
        'verify_device_detection.py',
        '--peer-ip', args.peer_ip
    ]
    try:
        dev_detect_ok = subprocess.run(dev_detect_cmd, check=True, capture_output=True, text=True)
        print(dev_detect_ok.stdout)
    except subprocess.CalledProcessError as e:
        logging.error(f"Device detection test failed: {e}\nOutput: {e.output}\nError: {e.stderr}")


    # Run verify_eth_speed.py
    logging.info("Running Ethernet speed test...")
    eth_speed_cmd = [
        sys.executable,
        'verify_eth_speed.py',
        '--camera-ip', args.peer_ip
    ]
    try:
        eth_speed_ok = subprocess.run(eth_speed_cmd, check=True, capture_output=True, text=True)
        print(eth_speed_ok.stdout)
    except subprocess.CalledProcessError as e:
        logging.error(f"Ethernet speed test failed: {e}\nOutput: {e.output}\nError: {e.stderr}")
    


    # Run verify_host_UDP.py
    logging.info("Running host UDP throughput test...")
    host_udp_cmd = [
        sys.executable,
        'verify_host_UDP.py'
    ]
    try:
        host_udp_ok = subprocess.run(host_udp_cmd, check=True, capture_output=True, text=True)
        print(host_udp_ok.stdout)
    except subprocess.CalledProcessError as e:
        logging.error(f"Host UDP throughput test failed: {e}\nOutput: {e.output}\nError: {e.stderr}")


    # Run verify_datecode_ver.py
    logging.info("Running datecode and version verification test...")
    datecode_cmd = [
        sys.executable,
        'verify_datecode_ver.py',
        '--version', args.version,
        '--datecode', args.datecode
    ]
    try:
        datecode_ver_ok = subprocess.run(datecode_cmd, check=True, capture_output=True, text=True)
        print(datecode_ver_ok.stdout)
    except subprocess.CalledProcessError as e:
        logging.error(f"Datecode and version verification test failed: {e}\nOutput: {e.output}\nError: {e.stderr}")

    # Run verify_PTP.py
    logging.info("Running PTP synchronization test...")
    ptp_cmd = [
        sys.executable,
        'verify_PTP.py',
        '--camera-ip', args.peer_ip
    ]
    try:
        ptp_ok = subprocess.run(ptp_cmd, check=True, capture_output=True, text=True)
        print(ptp_ok.stdout)
    except subprocess.CalledProcessError as e:
        logging.error(f"PTP synchronization test failed: {e}\nOutput: {e.output}\nError: {e.stderr}")

    # Run verify_reg.py
    logging.info("Running FPGA register read test...")
    reg_cmd = [
        sys.executable, 
        'verify_reg.py',
        '--peer-ip', args.peer_ip
    ]
    
    if args.cpnx1:
        reg_cmd.append('--cpnx1')
    if args.cpnx10:
        reg_cmd.append('--cpnx10')
    if args.avant10:
        reg_cmd.append('--avant10')
    if args.avant25:
        reg_cmd.append('--avant25')
    try:
        reg_read_ok = subprocess.run(reg_cmd, check=True, capture_output=True, text=True)
        print(reg_read_ok.stdout)
    except subprocess.CalledProcessError as e:
        logging.error(f"FPGA register read test failed: {e}\nOutput: {e.output}\nError: {e.stderr}")

     # Run verify_camera_imx258.py
    logging.info("Running IMX258 camera test...")
    camera_cmd = [
        sys.executable,
        'verify_camera_imx258.py',
        '--camera-ip', args.peer_ip,
        '--camera-mode', str(args.camera_mode),
        '--frame-limit', str(args.frame_limit)
    ]
    if args.save_images:
        camera_cmd.append('--save-images')
        camera_cmd.extend(['--save-dir', args.save_dir])
    if args.holoviz:
        camera_cmd.append('--holoviz')
    try:
        camera_ok = subprocess.run(camera_cmd, check=True, capture_output=True, text=True)
        print(camera_ok.stdout)
    except subprocess.CalledProcessError as e:
        logging.error(f"IMX258 camera test failed: {e}\nOutput: {e.output}\nError: {e.stderr}")


    # Run verify_multi_mode_imx258.py
    logging.info("Running IMX258 multi-mode test...")
    multi_mode_cmd = [
        sys.executable,
        'verify_multi_mode_imx258.py',
        '--camera-ip', args.peer_ip,
        '--frame-limit', str(args.frame_limit)
    ]
    if args.save_images:
        multi_mode_cmd.append('--save-images')
        multi_mode_cmd.extend(['--save-dir', args.save_dir])
    if args.holoviz:
        multi_mode_cmd.append('--holoviz')
    try:
        multi_mode_ok = subprocess.run(multi_mode_cmd, check=True, capture_output=True, text=True)
        print(multi_mode_ok.stdout)
    except subprocess.CalledProcessError as e:
        logging.error(f"IMX258 multi-mode test failed: {e}\nOutput: {e.output}\nError: {e.stderr}")

    # Run read meatadata
    logging.info("Reading hololink Enumeration metadata...")
    metadata_cmd = [
        sys.executable,
        'read_metadata.py',
        '--peer-ip', args.peer_ip
    ]
    try:
        metadata_ok = subprocess.run(metadata_cmd, check=True, capture_output=True, text=True)
        print(metadata_ok.stdout)
    except subprocess.CalledProcessError as e:
        logging.error(f"Reading hololink Enumeration metadata failed: {e}\nOutput: {e.output}\nError: {e.stderr}")

if __name__ == "__main__":
    main()