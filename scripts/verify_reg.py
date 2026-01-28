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

    if ((args.cpnx1 is False) and (args.cpnx10 is False) and (args.avant10 is False) and (args.avant25 is False)):
        print("Exception thrown: At least one device type must be specified.\n" \
        "Use --cpnx1, --cpnx10, --avant10, or --avant25 to specify the device type.")
        raise SystemExit(2)

    peer_ip = args.peer_ip
    regaddr = args.regaddr
    cpnx1 = args.cpnx1
    cpnx10 = args.cpnx10
    avant10 = args.avant10
    avant25 = args.avant25
    hostif = args.hostif

    # Connect to device
    try:
        # Find Hololink channel
        logging.info(f"Searching for Hololink device at {peer_ip}...")
        channel_metadata = hololink_module.Enumerator.find_channel(channel_ip=peer_ip)
        if not channel_metadata:
            return False, False
        
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
            addr_val = int(user_input, 16)  # Convert to integer, not string
            try:
                val = hex(hololink.read_uint32(addr_val))  # Read value
                print(f"Reading from address: {val}")
                sys.exit(0)
            except Exception as e:
                logging.error(f"Failed to read from address {hex(addr_val)}: {str(e)}")
                sys.exit(1)

        # CPNX 1G APB bus check
        if cpnx1:
            addr_val = {
                0x10000000: 0xD  # CPNX 1G
            }
            if hostif != 1:
                print("CPNX 1G only supports HOST_IF = 1")
                sys.exit(2)
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
                sys.exit(2)
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
                sys.exit(2)
            print("Starting Avant 10G or 25G APB bus check with addresses:", [hex(addr) for addr in addr_val.keys()])
            

        try:    
            for addr in addr_val:
                apb_val = hex(hololink.read_uint32(addr))  # Read value
                time.sleep(0.2)  # Small delay between reads
                if apb_val == hex(addr_val[addr]):
                    print(f"Register value for {hex(addr)}: {apb_val} is similar to expected value: {hex(addr_val[addr])})")
                    reg_check_passed = True
                else:
                    reg_check_passed = False
                    sys.exit(1)
        except Exception as e:
            logging.error(f"Failed to read from address: {str(e)}")
            sys.exit(1)

        return reg_check_passed

    except Exception as e:
        logging.error(f"Failed to start Hololink: {str(e)}")
        return False, False


if __name__ == "__main__":
    main()