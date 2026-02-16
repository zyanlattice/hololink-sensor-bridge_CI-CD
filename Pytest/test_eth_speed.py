"""
Test suite for verify_eth_speed.py
Tests ethernet link speed and throughput.
"""

import pytest


@pytest.mark.xfail(reason="IMX258 camera config not optimized", strict=True)
@pytest.mark.hardware
@pytest.mark.network
@pytest.mark.slow
def test_ethernet_throughput(hololink_device_ip, camera_mode, record_test_result):
    """Test actual data throughput from Hololink device."""
    import verify_eth_speed
    import sys
    from io import StringIO
    
    original_argv = sys.argv
    original_stdout = sys.stdout
    
    try:
        # Mock sys.argv to prevent pytest arguments from being parsed
        sys.argv = [
            "verify_eth_speed.py",
            "--camera-ip", hololink_device_ip,
            "--camera-mode", str(camera_mode),
            "--frame-limit", "300"
        ]
        
        # Capture stdout for user visibility
        captured_output = StringIO()
        sys.stdout = captured_output
        
        try:
            # verify_eth_speed.py returns (success, message, stats)
            success, message, stats = verify_eth_speed.main()
            
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
            "tags": ["ethernet", "throughput", "performance"],
            "stats": stats
        })
        
        assert success, message
    
    finally:
        sys.argv = original_argv
        sys.stdout = original_stdout
