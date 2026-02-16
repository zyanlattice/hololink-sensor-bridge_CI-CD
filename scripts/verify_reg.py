"""
APB BUS CHECKER
 
 
Avant 10G or 25G
read 0x1000_0000 expected return 0x3
read 0x2000_0000 expected return 0x3 (only when HOST_IF = 2)
read 0x1000_000C expected return 0x5E0
read 0x2000_000C expected return 0x5E0 (only when HOST_IF = 2)
 
CPNX 10G
read 0x1000_7A00 expected return 0x80
read 0x2000_0000 expected return 0x3
read 0x3000_7A00 expected return 0x80 (only when HOST_IF = 2)
read 0x4000_0000 expected return 0x3 (only when HOST_IF = 2)
 
CPNX 1G
read 0x1000_0000 expected return 0xD
 
"""


import logging
import time 
import hololink as hololink_module
import argparse
import sys


def argument_parser()-> argparse.Namespace:
    parser = argparse.ArgumentParser(description="APB Bus Checker for Hololink Device")
    parser.add_argument("--peer-ip", type=str, default="192.168.0.2", help="Hololink device IP")  
    parser.add_argument("--cpnx1", action="store_true", help="CPNX Versa 1G device")
    parser.add_argument("--cpnx10", action="store_true", help="CPNX Versa 10G device")
    parser.add_argument("--avant10", action="store_true", help="Avant Versa 10G device")
    parser.add_argument("--avant25", action="store_true", help="Avant Versa 25G device")
    parser.add_argument("--hostif", type=int, choices=[1, 2, 3, 4], help="Host interface type (1, 2, 3, or 4)", default=1)
    parser.add_argument("--regaddr", action="store_true", help="Direct input register address to read")
    return parser.parse_args() 

def main():

    args = argument_parser()

    peer_ip = args.peer_ip
    regaddr = args.regaddr
    cpnx1 = args.cpnx1
    cpnx10 = args.cpnx10
    avant10 = args.avant10
    avant25 = args.avant25
    hostif = args.hostif
    
    # If --regaddr is specified, device type is optional (for manual address testing)
    if not regaddr:
        if ((args.cpnx1 is False) and (args.cpnx10 is False) and (args.avant10 is False) and (args.avant25 is False)):
            print("Exception thrown: At least one device type must be specified.\n" \
            "Use --cpnx1, --cpnx10, --avant10, or --avant25 to specify the device type.")
            raise SystemExit(2)
    
    # Metrics to track
    metrics = {
        "register_count": 0,
        "registers_checked": {},  # Dict of {address: value} pairs
        "registers_checked_count": 0,  # Numeric count
        "registers_passed": 0,
        "registers_failed": 0,
        "total_read_time_ms": 0.0,
        "avg_read_latency_ms": 0.0,
    }

    # Connect to device
    try:
        # Find Hololink channel
        logging.info(f"Searching for Hololink device at {peer_ip}...")
        channel_metadata = hololink_module.Enumerator.find_channel(channel_ip=peer_ip)
        if not channel_metadata:
            metrics["error"] = f"Failed to find Hololink device at {peer_ip}"
            print(f"\n📊 Metrics: {metrics}")
            return False, metrics
        
        logging.info("Hololink device found")
        
        # Initialize camera
        hololink_channel = hololink_module.DataChannel(channel_metadata)

        # Start Hololink and camera
        logging.info("Starting Hololink...")
        hololink = hololink_channel.hololink()

        hololink.start()

        if regaddr:
            # Get user input for address to read
            user_input = input("Enter address to read (hex), e.g., [0x]10007A00: ")
            try:
                # Strip whitespace and convert hex string to integer
                user_input = user_input.strip()
                # int(..., 16) handles both "10007A00" and "0x10007A00" formats
                addr_val = int(user_input, 16)
                
                # Try to read from the address
                val = hex(hololink.read_uint32(addr_val))  # Read value
                print(f"✓ Successfully read from address {hex(addr_val)}: {val}")
                metrics["regaddr_requested"] = hex(addr_val)
                metrics["regaddr_read"] = val
                print(f"\n📊 Metrics: {metrics}")
                return True, metrics
            except ValueError as e:
                error_msg = f"Invalid hex address format: {user_input}. Use format like '10007A00' or '0x10007A00'"
                logging.error(error_msg)
                metrics["error"] = error_msg
                print(f"\n📊 Metrics: {metrics}")
                return False, metrics
            except Exception as e:
                logging.error(f"Failed to read from address {hex(addr_val)}: {str(e)}")
                metrics["regaddr_requested"] = hex(addr_val)
                metrics["error"] = str(e)
                print(f"\n📊 Metrics: {metrics}")
                return False, metrics

        # CPNX 1G APB bus check
        if cpnx1:
            addr_val = {
                0x10000000: 0xD  # CPNX 1G
            }
            if hostif != 1:
                print("CPNX 1G only supports HOST_IF = 1")
                metrics["error"] = "CPNX 1G only supports HOST_IF = 1"
                print(f"\n📊 Metrics: {metrics}")
                return False, metrics
            print("Starting CPNX 1G APB bus check with addresses:", [hex(addr) for addr in addr_val.keys()])


        # CPNX 10G APB bus check
        if cpnx10:
            addr_val1 = {
                0x10007A00: 0x80,
                0x20000000: 0x3  
                }
            addr_val2 = {
                0x30007A00: 0x80,
                0x40000000: 0x3     # CPNX 10G HOST_IF = 2
                }  
            if hostif == 1:
                addr_val = addr_val1
            elif hostif == 2:
                addr_val = {**addr_val1, **addr_val2}
            elif hostif in [3, 4]:
                print("CPNX 10G only supports HOST_IF = 1 or 2")
                metrics["error"] = "CPNX 10G only supports HOST_IF = 1 or 2"
                print(f"\n📊 Metrics: {metrics}")
                return False, metrics
            print("Starting CPNX 10G APB bus check with addresses:", [hex(addr) for addr in addr_val.keys()])

        # Avant 10G or 25G APB bus check
        if avant10 or avant25:
            addr_val1 = {
                0x10000000: 0x3,
                0x1000000C: 0x5E0  # Avant 10G or 25G
            }
            addr_val2 = {
                0x20000000: 0x3,
                0x2000000C: 0x5E0  # Avant 10G or 25G HOST_IF = 2
            }
            if hostif == 1:
                addr_val = addr_val1
            elif hostif == 2:
                addr_val = {**addr_val1, **addr_val2}
            elif hostif in [3, 4]:
                print("Avant 10G or 25G only supports HOST_IF = 1 or 2")
                metrics["error"] = "Avant 10G or 25G only supports HOST_IF = 1 or 2"
                print(f"\n📊 Metrics: {metrics}")
                return False, metrics
            print("Starting Avant 10G or 25G APB bus check with addresses:", [hex(addr) for addr in addr_val.keys()])
            
        metrics["register_count"] = len(addr_val)
        read_times = []

        try:    
            for addr in addr_val:
                start_time = time.time()
                apb_val = hex(hololink.read_uint32(addr))  # Read value
                read_time_ms = (time.time() - start_time) * 1000
                read_times.append(read_time_ms)
                
                time.sleep(0.2)  # Small delay between reads
                
                # Add register to dict (address -> value mapping)
                metrics["registers_checked"][hex(addr)] = apb_val
                metrics["registers_checked_count"] += 1
                
                if apb_val == hex(addr_val[addr]):
                    print(f"✓ Register {hex(addr)}: {apb_val} == {hex(addr_val[addr])} (read time: {read_time_ms:.2f}ms)")
                    metrics["registers_passed"] += 1
                    reg_check_passed = True
                else:
                    print(f"✗ Register {hex(addr)}: {apb_val} != {hex(addr_val[addr])} (MISMATCH)")
                    metrics["registers_failed"] += 1
                    metrics["total_read_time_ms"] = sum(read_times)
                    metrics["avg_read_latency_ms"] = round(metrics["total_read_time_ms"] / len(read_times), 3) if read_times else 0
                    print(f"\n📊 Metrics: {metrics}")
                    return False, metrics
                    
            # All checks passed - calculate final metrics
            metrics["total_read_time_ms"] = sum(read_times)
            metrics["avg_read_latency_ms"] = round(metrics["total_read_time_ms"] / len(read_times), 3) if read_times else 0
            print(f"\n📊 Metrics: {metrics}")
            
        except Exception as e:
            logging.error(f"Failed to read from address: {str(e)}")
            metrics["total_read_time_ms"] = sum(read_times) if read_times else 0
            metrics["avg_read_latency_ms"] = round(metrics["total_read_time_ms"] / len(read_times), 3) if read_times else 0
            metrics["error"] = str(e)
            print(f"\n📊 Metrics: {metrics}")
            return False, metrics

        return True, metrics

    except Exception as e:
        logging.error(f"Failed to start Hololink: {str(e)}")
        print(f"\n📊 Metrics: {metrics}")
        return False, metrics


if __name__ == "__main__":
    success, metrics = main()
    sys.exit(0 if success else 1)