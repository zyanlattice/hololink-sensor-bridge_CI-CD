"""
Test suite for verify_camera_driver.py
Tests IMX258 camera driver detection and initialization.
"""

import pytest


@pytest.mark.hardware
@pytest.mark.camera
def test_camera_driver_detection(hololink_device_ip, record_test_result):
    """Test that IMX258 camera driver can be detected and initialized."""
    # Import the verification script
    import verify_camera_driver
    import sys
    
    original_argv = sys.argv
    try:
        sys.argv = [
            "verify_camera_driver.py",
            "--peer-ip", hololink_device_ip
        ]
        
        # Run verification
        success = verify_camera_driver.main()
        
        message = f"Camera driver detection: {'PASS' if success else 'FAIL'}"
        
        record_test_result({
            "success": success,
            "message": message,
            "stats": {}
        })
        
        assert success, message
    
    finally:
        sys.argv = original_argv
