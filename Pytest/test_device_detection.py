"""
Test suite for verify_device_detection.py
Tests Hololink device network detection.
"""

import pytest
import sys


@pytest.mark.hardware
@pytest.mark.network
def test_device_detection(hololink_device_ip, record_test_result):
    """Test that Hololink device can be detected on the network."""
    # Import the verification script
    import verify_device_detection
    
    # Run detection
    detected_interface = verify_device_detection.main(timeout_seconds=10)
    
    # Record results
    success = detected_interface is not None
    message = f"Detected interface: {detected_interface}" if success else "No Hololink device detected"
    
    record_test_result({
        "success": success,
        "message": message,
        "stats": {"interface": detected_interface}
    })
    
    assert success, message
