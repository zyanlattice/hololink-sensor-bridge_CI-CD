from html import parser
import logging
import sys
import argparse
import holoscan
import hololink as hololink_module
import time


def argument_parser() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify IMX258 camera driver functionality")
    parser.add_argument("--peer-ip", type=str, default="192.168.0.2", help="Hololink device IP")
    parser.add_argument("--log-level", type=int, default=logging.INFO, help="Logging level")
    return parser.parse_args()

def main() -> bool:
    
    args = argument_parser()
    peer_ip = args.peer_ip
    log_level = args.log_level

    # Metrics to track
    metrics = {
        "device_found": False,
        "camera_found": False,
        "camera_modes_available": 0,
        "camera_modes_list": [],
    }

    # Setup logging
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Find Hololink channel
    logging.info(f"Searching for Hololink device at {peer_ip}...")
    
    # Retry logic to handle "Interrupted system call" errors when tests run back-to-back
    max_retries = 3
    retry_delay = 0.5  # Start with 500ms
    channel_metadata = None
    
    for attempt in range(max_retries):
        try:
            channel_metadata = hololink_module.Enumerator.find_channel(channel_ip=peer_ip)
            if channel_metadata:
                break
            logging.warning(f"Device not found at {peer_ip}, attempt {attempt + 1}/{max_retries}")
        except RuntimeError as e:
            if "Interrupted system call" in str(e) and attempt < max_retries - 1:
                logging.warning(f"Interrupted system call on attempt {attempt + 1}/{max_retries}, retrying after {retry_delay}s delay...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                raise
    
    if not channel_metadata:
        print(f"\n📊 Metrics: {metrics}")
        return False, f"Failed to find Hololink device at {peer_ip} after {max_retries} attempts", metrics
    
    metrics["device_found"] = True
    logging.info("Hololink device found")

    # Try to find camera
    hololink_channel = hololink_module.DataChannel(channel_metadata)
    logging.info(f"Channel initialized: {hololink_channel}")
    camera = hololink_module.sensors.imx258.Imx258(hololink_channel, 0)
    if not camera:
        print(f"\n📊 Metrics: {metrics}")
        return False, "Failed to find IMX258 camera", metrics
    
    metrics["camera_found"] = True
    
    # Print all available camera modes
    print("Available IMX258 Camera Modes:")
    camera_modes = []
    for mode in hololink_module.sensors.imx258.Imx258_Mode:
        print(f"  {mode.value}: {mode.name}")
        camera_modes.append(mode.name)
    
    metrics["camera_modes_available"] = len(camera_modes)
    metrics["camera_modes_list"] = camera_modes

    # CRITICAL: Reset hololink framework to clear global device registry
    # This prevents cached/buffered frames from previous runs affecting the next run
    try:
        logging.info("Resetting Hololink framework (clears global device registry)...")
        hololink_module.Hololink.reset_framework()
    except Exception as e:
        logging.warning(f"Error resetting hololink framework: {e}")

    cam_success = True
    print(f"\n📊 Metrics: {metrics}")

    return cam_success, "Camera driver verification passed", metrics

if __name__ == "__main__":
    main()
