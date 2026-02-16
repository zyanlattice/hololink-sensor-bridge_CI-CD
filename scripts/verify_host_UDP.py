import socket
import struct
import time
import logging

def ethernet_loopback_test(
    host='127.0.0.1',
    port=12345,
    payload_sizes=[512, 1024, 4096, 8192, 16384, 32768, 65000],
    num_packets=5
) -> tuple[bool, dict]:
    """
    Generic UDP loopback test - no hololink protocol
    Tests pure ethernet/network layer with realistic UDP datagram sizes
    
    Note: UDP max datagram size is ~65,507 bytes (65,535 - IP header - UDP header)
    10G ethernet uses standard MTU (1500 default, up to 9000 jumbo frames)
    IP header: 20 bytes
    UDP header: 8 bytes
    Usable payload: ~65,507 bytes
    
    Returns:
        Tuple of (success: bool, metrics: dict)
    """
    
    # Initialize metrics
    metrics = {
        "host": host,
        "port": port,
        "payload_sizes_bytes": payload_sizes,
        "num_packets_per_size": num_packets,
        "total_packets_sent": 0,
        "total_packets_received": 0,
        "total_packets_failed": 0,
        "success_rate_percent": 0.0,
        "elapsed_time_seconds": 0.0,
        "timeouts": 0,
        "mismatches": 0,
        "errors": 0,
    }
    
    start_time = time.time()
    
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
                metrics["total_packets_sent"] += 1
                
                # Receive it back - use larger buffer that matches payload_size
                received, addr = sock.recvfrom(payload_size + 16)
                metrics["total_packets_received"] += 1
                
                total_packets += 1
                
                # Verify
                if received == test_packet:
                    logging.info(f"  Packet {i}: OK ({len(received)} bytes)")
                else:
                    logging.error(f"  Packet {i}: MISMATCH - sent {len(test_packet)} bytes, got {len(received)} bytes")
                    failed_packets += 1
                    metrics["mismatches"] += 1
                    
            except socket.timeout:
                logging.error(f"  Packet {i}: TIMEOUT - no response")
                failed_packets += 1
                metrics["timeouts"] += 1
            except OSError as e:
                logging.error(f"  Packet {i}: ERROR {e.errno} - {e.strerror}")
                failed_packets += 1
                metrics["errors"] += 1
                if e.errno == 90:  # EMSGSIZE
                    logging.error(f"    Message size {payload_size} bytes exceeds UDP limit (~65,507 bytes)")
                    break  # Skip remaining sizes
    
    sock.close()
    
    # Calculate final metrics
    metrics["elapsed_time_seconds"] = round(time.time() - start_time, 2)
    metrics["total_packets_failed"] = failed_packets
    metrics["success_rate_percent"] = round(100 * (total_packets - failed_packets) / total_packets, 2) if total_packets > 0 else 0.0
    
    logging.info(f"\nTest Summary:")
    logging.info(f"  Total packets: {total_packets}")
    logging.info(f"  Failed packets: {failed_packets}")
    logging.info(f"  Success rate: {metrics['success_rate_percent']:.1f}%")
    
    success = failed_packets == 0
    return success, metrics

def main() -> tuple[bool, str, dict]:
    """Run UDP loopback test.
    
    Returns:
        Tuple of (success: bool, message: str, metrics: dict)
    """
    logging.basicConfig(level=logging.INFO)
    success, metrics = ethernet_loopback_test()
    
    if success:
        logging.info("UDP loopback test completed successfully.")
        message = "UDP loopback test passed"
    else:
        logging.error("UDP loopback test failed.")
        message = f"UDP loopback test failed: {metrics['total_packets_failed']} packets failed"
    
    print(f"\n📊 Metrics: {metrics}")
    return success, message, metrics

if __name__ == "__main__":
    import sys
    success, message, metrics = main()
    sys.exit(0 if success else 1)