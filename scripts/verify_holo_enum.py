#!/usr/bin/env python3
"""
Script to verify Hololink enumeration and basic connectivity.
Runs 'hololink enumerate' command and captures broadcast messages.
"""

import argparse
import logging
import subprocess
import sys
import signal
import re
import time
from typing import List, Dict


def parse_enumeration_line(line: str) -> Dict:
    """
    Parse a single enumeration line from hololink enumerate output.
    
    Example line:
    INFO 1.0000 call_back hololink.py:220 tid=0xe5c -- mac_id=CA:FE:C0:FF:EE:00 hsb_ip_version=0X2511 fpga_crc=0X0 ip_address=192.168.0.2 serial_number=00000000000000 interface=eno1
    
    Args:
        line: Output line from hololink enumerate
        
    Returns:
        Dictionary with parsed enumeration data, or None if not an enumeration line
    """
    # Check if line contains enumeration data (has the -- separator)
    if '--' not in line:
        return None
    
    # Extract the data after --
    try:
        data_part = line.split('--', 1)[1].strip()
        
        # Parse key=value pairs
        enum_data = {}
        for pair in data_part.split():
            if '=' in pair:
                key, value = pair.split('=', 1)
                enum_data[key] = value
        
        # Validate we got the expected keys
        if 'mac_id' in enum_data or 'ip_address' in enum_data:
            return enum_data
            
    except Exception as e:
        logging.debug(f"Failed to parse line: {line.strip()} - {e}")
    
    return None


def run_enumeration(count: int = 10, timeout: int = 30) -> tuple[bool, List[Dict]]:
    """
    Run 'hololink enumerate' and capture enumeration broadcasts.
    
    Args:
        count: Number of enumerations to capture (default: 10)
        timeout: Maximum time to wait in seconds (default: 30)
        
    Returns:
        Tuple of (success, list of enumeration data dictionaries)
    """
    enumerations = []
    start_time = time.time()
    
    logging.info(f"Starting 'hololink enumerate' (capturing {count} broadcasts)...")
    logging.info(f"Timeout: {timeout} seconds")
    
    try:
        # Start hololink enumerate process
        process = subprocess.Popen(
            ['hololink', 'enumerate'],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # Line buffered
            universal_newlines=True
        )
        
        # Read output line by line
        while len(enumerations) < count:
            elapsed = time.time() - start_time
            
            # Check timeout
            if elapsed >= timeout:
                logging.warning(f"Timeout reached after {elapsed:.1f}s")
                logging.warning(f"Only captured {len(enumerations)}/{count} enumerations")
                process.terminate()
                process.wait(timeout=5)
                return False, enumerations
            
            # Read line
            line = process.stdout.readline()
            if not line:
                # Process ended
                logging.warning("Process ended unexpectedly")
                break
            
            # Log the raw line
            logging.debug(f"Output: {line.strip()}")
            
            # Parse enumeration data
            enum_data = parse_enumeration_line(line)
            if enum_data:
                enumerations.append(enum_data)
                logging.info(
                    f"Enumeration [{len(enumerations)}/{count}]: "
                    f"mac_id={enum_data.get('mac_id', 'N/A')} "
                    f"hsb_ip_version={enum_data.get('hsb_ip_version', 'N/A')} "
                    f"fpga_crc={enum_data.get('fpga_crc', 'N/A')} "
                    f"ip_address={enum_data.get('ip_address', 'N/A')} "
                    f"serial_number={enum_data.get('serial_number', 'N/A')} "
                    f"interface={enum_data.get('interface', 'N/A')}"
                )
        
        # Stop the process (Ctrl+C equivalent)
        logging.info(f"Captured {count} enumerations, stopping process...")
        process.send_signal(signal.SIGINT)
        
        # Wait for process to finish
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        
        elapsed = time.time() - start_time
        logging.info(f"Successfully captured {len(enumerations)} enumerations in {elapsed:.1f}s")
        return True, enumerations
        
    except FileNotFoundError:
        logging.error("'hololink' command not found. Is it installed and in PATH?")
        return False, enumerations
    except Exception as e:
        logging.error(f"Error running enumeration: {e}")
        if 'process' in locals():
            try:
                process.kill()
            except:
                pass
        return False, enumerations


def main() -> bool:
    """
    Main function to run enumeration test.
    
    Returns:
        True if test passed, False otherwise
    """
    parser = argparse.ArgumentParser(
        description="Verify Hololink enumeration and basic connectivity by running 'hololink enumerate'"
    )
    parser.add_argument(
        "--count",
        type=int,
        default=10,
        help="Number of enumerations to capture (default: 10)"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Maximum time to wait in seconds (default: 30)"
    )
    parser.add_argument(
        "--expected-ip",
        type=str,
        default="192.168.0.2",
        help="Expected IP address to verify (default: 192.168.0.2)"
    )
    parser.add_argument(
        "--log-level",
        type=int,
        default=logging.INFO,
        help="Logging level (default: INFO/20)"
    )
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=args.log_level,
        format='%(levelname)s: %(message)s'
    )
    
    # Run enumeration
    success, enumerations = run_enumeration(args.count, args.timeout)
    
    # Print summary
    logging.info("=" * 70)
    logging.info("Enumeration Test Summary:")
    logging.info("=" * 70)
    logging.info(f"Total enumerations captured: {len(enumerations)}/{args.count}")
    
    if enumerations:
        # Get unique values
        unique_ips = set(e.get('ip_address', '') for e in enumerations if e.get('ip_address'))
        unique_macs = set(e.get('mac_id', '') for e in enumerations if e.get('mac_id'))
        unique_versions = set(e.get('hsb_ip_version', '') for e in enumerations if e.get('hsb_ip_version'))
        
        logging.info(f"Unique devices found: {len(unique_ips)}")
        logging.info(f"IP addresses: {', '.join(unique_ips)}")
        logging.info(f"MAC addresses: {', '.join(unique_macs)}")
        logging.info(f"HSB IP versions: {', '.join(unique_versions)}")
        
        # Verify expected IP
        if args.expected_ip in unique_ips:
            logging.info(f"✓ Expected IP {args.expected_ip} found in enumerations")
        else:
            logging.error(f"✗ Expected IP {args.expected_ip} NOT found in enumerations")
            success = False
    else:
        logging.error("No enumerations captured")
        success = False
    
    # Final result
    if success and len(enumerations) >= args.count:
        logging.info("=" * 70)
        logging.info("✓ Enumeration test PASSED")
        logging.info("=" * 70)
        return True
    else:
        logging.error("=" * 70)
        logging.error("✗ Enumeration test FAILED")
        logging.error("=" * 70)
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

