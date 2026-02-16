import argparse
import os
import logging
import sys
import threading
import hololink as hololink_module
import terminal_print_formating as tpf 



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True if not "--print" in sys.argv else False, type=str, help="Bitstream file version to verify")
    parser.add_argument("--datecode", type=str, help="Bitstream datecode to verify")
    parser.add_argument("--print", action="store_true", help="Print retrieved datecode and version")

    return parser.parse_args()

def main() -> tuple[bool, bool, dict]:

    args = parse_args()
    ver = args.version
    datecode = args.datecode

    hololink = None
    metrics = {}
    
    # Setup logging with custom handler to capture hololink messages
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s: %(message)s'
    )
    
    
    try:
                
        # Find Hololink channel with retry logic (handles device busy from previous tests)
        logging.info(f"Searching for Hololink device at {"192.168.0.2"}...")
        channel_metadata = None
        max_retries = 3
        retry_delay = 1.0  # seconds
        
        for attempt in range(max_retries):
            try:
                channel_metadata = hololink_module.Enumerator.find_channel(channel_ip="192.168.0.2")
                if channel_metadata:
                    break
            except RuntimeError as e:
                if "Interrupted system call" in str(e) and attempt < max_retries - 1:
                    logging.warning(f"Device busy (attempt {attempt + 1}/{max_retries}), retrying in {retry_delay}s...")
                    import time
                    time.sleep(retry_delay)
                else:
                    raise
        
        if not channel_metadata:
            return False, False, metrics
        
        logging.info("Hololink device found")
        
        # Initialize camera
        hololink_channel = hololink_module.DataChannel(channel_metadata)

        # Start Hololink and camera
        logging.info("Starting Hololink...")
        hololink = hololink_channel.hololink()

        hololink.start()
        
        bitstream_datecode = hololink.get_fpga_date()
        bitstream_version = hololink.get_hsb_ip_version(None,True)

        # Store retrieved values in metrics
        metrics["retrieved_datecode_hex"] = f"{bitstream_datecode:#x}" if isinstance(bitstream_datecode, int) else bitstream_datecode
        metrics["retrieved_datecode_decimal"] = int(bitstream_datecode) if not isinstance(bitstream_datecode, int) else bitstream_datecode
        metrics["retrieved_version_hex"] = f"{bitstream_version:#x}" if isinstance(bitstream_version, int) else bitstream_version
        metrics["retrieved_version_decimal"] = int(bitstream_version) if not isinstance(bitstream_version, int) else bitstream_version

        if args.print:
            logging.info(f"Retrieved FPGA datecode: {bitstream_datecode:#x} (decimal: {bitstream_datecode})")
            logging.info(f"Retrieved HSB IP version: {bitstream_version:#x} (decimal: {bitstream_version})")
            print(f"📊 Metrics: {metrics}")
            return True, True, metrics

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
                metrics["expected_datecode_hex"] = f"{expected_datecode:#x}"
                metrics["expected_datecode_decimal"] = expected_datecode
                metrics["datecode_match"] = (bitstream_datecode == expected_datecode)
                
                if bitstream_datecode == expected_datecode:
                    logging.info(f"✓ Datecode verification PASSED, Bitstream datecode: {bitstream_datecode:#x}, Exepected datecode: {expected_datecode:#x}")
                    datecode_ok = True
                else:
                    logging.error(f"✗ Datecode mismatch - Expected: {expected_datecode:#x}, Got: {bitstream_datecode:#x}")
                    print(f"📊 Metrics: {metrics}")
                    return False, version_ok, metrics
            except (ValueError, TypeError) as e:
                logging.error(f"Invalid datecode format '{datecode}': {e}")
                metrics["datecode_parse_error"] = str(e)
                print(f"📊 Metrics: {metrics}")
                return False, version_ok, metrics
       

        # Verify version if provided
        if ver:
            try:
                expected_ver = int(ver, 0)  # Supports hex (0x...) and decimal
                metrics["expected_version_hex"] = f"{expected_ver:#x}"
                metrics["expected_version_decimal"] = expected_ver
                metrics["version_match"] = (bitstream_version == expected_ver)
                
                if bitstream_version == expected_ver:
                    logging.info(f"✓ Version verification PASSED, Bitstream version: {bitstream_version:#x}, Expected version: {expected_ver:#x}")
                    version_ok = True
                else:
                    logging.error(f"✗ Version mismatch - Expected: {expected_ver:#x}, Got: {bitstream_version:#x}")
                    print(f"📊 Metrics: {metrics}")
                    return datecode_ok, False, metrics
            except (ValueError, TypeError) as e:
                logging.error(f"Invalid version format '{ver}': {e}")
                metrics["version_parse_error"] = str(e)
                print(f"📊 Metrics: {metrics}")
                return datecode_ok, False, metrics
      
        print("=" * 90)
        
        # Print metrics at end of successful run
        print(f"📊 Metrics: {metrics}")

    except Exception as e:
        logging.error(f"Error during verification: {e}")
        import traceback
        traceback.print_exc()
        metrics["error"] = str(e)
        print(f"📊 Metrics: {metrics}")
        return False, False, metrics
    finally:
        # Cleanup
        if hololink and hasattr(hololink, 'stop'):
            try:
                logging.info("Stopping Hololink...")
                hololink.stop()
            except Exception as e:
                logging.warning(f"Error stopping hololink: {e}")

    return datecode_ok, version_ok, metrics

if __name__ == "__main__":
    datecode_ok, version_ok, metrics = main()
    exit(0 if (datecode_ok and version_ok) else 1)