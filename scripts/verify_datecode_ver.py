import argparse
import os
import logging
import sys
import threading
import hololink as hololink_module
import terminal_print_formating as tpf 



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True, type=str, help="Bitstream file version to verify")
    parser.add_argument("--datecode", type=str, help="Bitstream datecode to verify")

    return parser.parse_args()

def main() -> tuple[bool, bool]:

    args = parse_args()
    ver = args.version
    datecode = args.datecode

    hololink = None
    
    # Setup logging with custom handler to capture hololink messages
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s: %(message)s'
    )
    
    
    try:
                
        # Find Hololink channel
        logging.info(f"Searching for Hololink device at {"192.168.0.2"}...")
        channel_metadata = hololink_module.Enumerator.find_channel(channel_ip="192.168.0.2")
        if not channel_metadata:
            return False, False
        
        logging.info("Hololink device found")
        
        # Initialize camera
        hololink_channel = hololink_module.DataChannel(channel_metadata)

        # Start Hololink and camera
        logging.info("Starting Hololink...")
        hololink = hololink_channel.hololink()

        hololink.start()
        
        bitstream_datecode = hololink.get_fpga_date()
        bitstream_version = hololink.get_hsb_ip_version(None,True)

        # Ensure values are integer (might be returned as string from binding)
        if isinstance(bitstream_datecode, str):
            bitstream_datecode = int(bitstream_datecode, 0)
        if isinstance(bitstream_version, str):
            bitstream_version = int(bitstream_version, 0)
        
        datecode_ok = False
        version_ok = False

        logging.info(f"FPGA datecode: {bitstream_datecode:#x} (decimal: {bitstream_datecode})")
        logging.info(f"HSB IP version: {bitstream_version:#x} (decimal: {bitstream_version})")
        

        print(tpf.header_footer(90, "Datecode and Version Verification Results"))

        # Verify datecode if provided
        if datecode:
            try:
                expected_datecode = int(datecode, 0)  # Supports hex (0x...) and decimal
                if bitstream_datecode == expected_datecode:
                    logging.info(f"✓ Datecode verification PASSED, Bitstream datecode: {bitstream_datecode:#x}, Exepected datecode: {expected_datecode:#x}")
                    datecode_ok = True
                else:
                    logging.error(f"✗ Datecode mismatch - Expected: {expected_datecode:#x}, Got: {bitstream_datecode:#x}")
                    return False, version_ok
            except (ValueError, TypeError) as e:
                logging.error(f"Invalid datecode format '{datecode}': {e}")
                return False, version_ok
       

        # Verify version if provided
        if ver:
            try:
                expected_ver = int(ver, 0)  # Supports hex (0x...) and decimal
                if bitstream_version == expected_ver:
                    logging.info(f"✓ Version verification PASSED, Bitstream version: {bitstream_version:#x}, Expected version: {expected_ver:#x}")
                    version_ok = True
                else:
                    logging.error(f"✗ Version mismatch - Expected: {expected_ver:#x}, Got: {bitstream_version:#x}")
                    return datecode_ok, False
            except (ValueError, TypeError) as e:
                logging.error(f"Invalid version format '{ver}': {e}")
                return datecode_ok, False
      
        print("=" * 90)

    except Exception as e:
        logging.error(f"Error during verification: {e}")
        import traceback
        traceback.print_exc()
        return False, False
    finally:
        # Cleanup
        if hololink and hasattr(hololink, 'stop'):
            try:
                logging.info("Stopping Hololink...")
                hololink.stop()
            except Exception as e:
                logging.warning(f"Error stopping hololink: {e}")

    return datecode_ok, version_ok

if __name__ == "__main__":
    result = main()
    exit(0 if all(result) else 1)