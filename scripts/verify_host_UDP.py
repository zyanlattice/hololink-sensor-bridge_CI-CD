import socket
import struct
import time
import logging

def ethernet_loopback_test(
    host='127.0.0.1',
    port=12345,
    payload_sizes=[512, 1024, 4096, 8192, 16384, 32768, 65000],
    num_packets=5
):
    """
    Generic UDP loopback test - no hololink protocol
    Tests pure ethernet/network layer with realistic UDP datagram sizes
    
    Note: UDP max datagram size is ~65,507 bytes (65,535 - IP header - UDP header)
    10G ethernet uses standard MTU (1500 default, up to 9000 jumbo frames)
    IP header: 20 bytes
    UDP header: 8 bytes
    Usable payload: ~65,507 bytes
    """
    
    # Create UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    # Optional: Set SO_RCVBUF for better performance
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024*1024)  # 1MB buffer
    
    sock.bind((host, port))
    sock.settimeout(5.0)  # 5 second timeout
    
    total_packets = 0
    failed_packets = 0
    
    for payload_size in payload_sizes:
        logging.info(f"Testing payload size: {payload_size} bytes")
        
        for i in range(num_packets):
            try:
                # Create simple test packet: [timestamp][sequence][payload]
                timestamp = struct.pack('d', time.time())  # 8 bytes
                sequence = struct.pack('I', i)              # 4 bytes
                payload = b'X' * (payload_size - 12)
                
                test_packet = timestamp + sequence + payload
                
                # Send to self
                sock.sendto(test_packet, (host, port))
                
                # Receive it back - use larger buffer that matches payload_size
                received, addr = sock.recvfrom(payload_size + 16)
                
                total_packets += 1
                
                # Verify
                if received == test_packet:
                    logging.info(f"  Packet {i}: OK ({len(received)} bytes)")
                else:
                    logging.error(f"  Packet {i}: MISMATCH - sent {len(test_packet)} bytes, got {len(received)} bytes")
                    failed_packets += 1
                    
            except socket.timeout:
                logging.error(f"  Packet {i}: TIMEOUT - no response")
                failed_packets += 1
            except OSError as e:
                logging.error(f"  Packet {i}: ERROR {e.errno} - {e.strerror}")
                failed_packets += 1
                if e.errno == 90:  # EMSGSIZE
                    logging.error(f"    Message size {payload_size} bytes exceeds UDP limit (~65,507 bytes)")
                    break  # Skip remaining sizes
    
    sock.close()
    
    logging.info(f"\nTest Summary:")
    logging.info(f"  Total packets: {total_packets}")
    logging.info(f"  Failed packets: {failed_packets}")
    logging.info(f"  Success rate: {100 * (total_packets - failed_packets) / total_packets if total_packets > 0 else 0:.1f}%")
    
    return failed_packets == 0

def main()-> bool:
    logging.basicConfig(level=logging.INFO)
    success = ethernet_loopback_test()
    if success:
        logging.info("UDP loopback test completed successfully.")
        return True
    else:
        logging.error("UDP loopback test failed.")
        return False

if __name__ == "__main__":
    main()