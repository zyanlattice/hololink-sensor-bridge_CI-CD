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
import hololink as hololink_module

def main():
    # Connect to device
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

        # Get user input for address to read
        user_input = input("Enter address to read (hex), e.g., [0x]10007A00: ")
        addr_val = int(user_input, 16)  # Convert to integer, not string
        print(f"Reading from address: {hex(addr_val)}")

        # Perform APB bus checks here
        apb_val_1 = hex(hololink.read_uint32(addr_val))  # Expected: 0x80 - pass integer directly
        # apb_val_2 = hololink.read_uint32(0x10000000)  # Expected: 0x3
        # apb_val_3 = hololink.read_uint32(0x30007A00)  # Expected: 0x80
        # apb_val_4 = hololink.read_uint32(0x40000000)  # Expected: 0x3

        print(f"APB Bus Check Result: {apb_val_1}")
        # print(f"0x1000_7A00 = {hex(apb_val_1)}")
        # print(f"0x2000_0000 = {hex(apb_val_2)}")
        # print(f"0x3000_7A00 = {hex(apb_val_3)}")
        # print(f"0x4000_0000 = {hex(apb_val_4)}")

    except Exception as e:
        logging.error(f"Failed to start Hololink: {str(e)}")
        return False, False


if __name__ == "__main__":
    main()