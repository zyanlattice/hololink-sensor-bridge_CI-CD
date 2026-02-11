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
    
    original_argv = sys.argv
    try:
        # Mock sys.argv to prevent pytest arguments from being parsed
        sys.argv = [
            "verify_eth_speed.py",
            "--camera-ip", hololink_device_ip,
            "--camera-mode", str(camera_mode),
            "--frame-limit", "300"
        ]
        
        # This test captures frames to measure real throughput
        # It's slower than the link speed check
        success, message, stats = verify_eth_speed.main()
        
        # Check throughput stats if available
        if stats and "Throughput_mbps" in stats:
            expected_mbps = stats.get("Expected_mbps", 200)
            actual_mbps = stats["Throughput_mbps"]
            assert actual_mbps >= int(0.7 * expected_mbps), \
                f"Throughput too low: {actual_mbps} Mbps (expected >= {int(0.7 * expected_mbps)} Mbps)"
        
        record_test_result({
            "success": success,
            "message": message,
            "stats": stats
        })
        
        assert success, message
    
    finally:
        sys.argv = original_argv
