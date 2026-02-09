
from html import parser
import logging
import sys
import argparse
import holoscan
import hololink as hololink_module


def argument_parser() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify IMX258 camera driver functionality")
    parser.add_argument("--peer-ip", type=str, default="192.168.0.2", help="Hololink device IP")
    parser.add_argument("--log-level", type=int, default=logging.INFO, help="Logging level")
    return parser.parse_args()

def main() -> bool:
    
    args = argument_parser()
    peer_ip = args.peer_ip
    log_level = args.log_level
    

        # Setup logging
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Find Hololink channel
    logging.info(f"Searching for Hololink device at {peer_ip}...")
    channel_metadata = hololink_module.Enumerator.find_channel(channel_ip=peer_ip)
    if not channel_metadata:
        return False, f"Failed to find Hololink device at {peer_ip}", {}
    
    logging.info("Hololink device found")

    # Try to find camera
    hololink_channel = hololink_module.DataChannel(channel_metadata)
    logging.info(f"Channel initialized: {hololink_channel}")
    camera = hololink_module.sensors.imx258.Imx258(hololink_channel, 0)
    if not camera:
        return False, "Failed to find IMX258 camera", {}
    
    # Print all available camera modes
    print("Available IMX258 Camera Modes:")
    for mode in hololink_module.sensors.imx258.Imx258_Mode:
        print(f"  {mode.value}: {mode.name}")

    # CRITICAL: Reset hololink framework to clear global device registry
    # This prevents cached/buffered frames from previous runs affecting the next run
    try:
        logging.info("Resetting Hololink framework (clears global device registry)...")
        hololink_module.Hololink.reset_framework()
    except Exception as e:
        logging.warning(f"Error resetting hololink framework: {e}")

    cam_success = True

    return cam_success

if __name__ == "__main__":
    main()