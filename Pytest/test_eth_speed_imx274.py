"""
Test suite for verify_eth_speed_imx274.py
Tests ethernet link speed and throughput with IMX274 camera.
"""

import pytest


@pytest.mark.hardware
@pytest.mark.network
@pytest.mark.slow
def test_ethernet_throughput(hololink_device_ip, camera_mode, record_test_result):
    """Test actual data throughput from Hololink device with IMX274 camera."""
    import verify_eth_speed_imx274
    import sys
    from io import StringIO
    
    original_argv = sys.argv
    original_stdout = sys.stdout
    
    try:
        # Mock sys.argv to prevent pytest arguments from being parsed
        sys.argv = [
            "verify_eth_speed_imx274.py",
            "--camera-ip", hololink_device_ip,
            "--camera-mode", str(camera_mode),
            "--frame-limit", "300"
        ]
        
        # Capture stdout for user visibility
        captured_output = StringIO()
        sys.stdout = captured_output
        
        try:
            # verify_eth_speed_imx274.py returns (success, message, stats)
            success, message, stats = verify_eth_speed_imx274.main()
            
        except Exception as e:
            success = False
            message = f"Ethernet throughput test failed: {str(e)}"
            stats = {"error": str(e)}
            
        finally:
            sys.stdout = original_stdout
            output_text = captured_output.getvalue()
            if output_text:
                print(output_text)
        
        # Check throughput stats if available
        if stats and "Throughput_mbps" in stats:
            expected_mbps = stats.get("Expected_mbps", 200)
            actual_mbps = stats["Throughput_mbps"]
            if actual_mbps < int(0.7 * expected_mbps):
                success = False
                message = f"Throughput too low: {actual_mbps} Mbps (expected >= {int(0.7 * expected_mbps)} Mbps)"
        
        record_test_result({
            "success": success,
            "message": message,
            "category": "network",
            "tags": ["ethernet", "throughput", "performance", "imx274"],
            "stats": stats
        })
        
        assert success, message
    
    finally:
        sys.argv = original_argv
        sys.stdout = original_stdout
