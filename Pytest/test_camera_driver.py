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
    import re
    from io import StringIO
    
    original_argv = sys.argv
    original_stdout = sys.stdout
    
    try:
        sys.argv = [
            "verify_camera_driver.py",
            "--peer-ip", hololink_device_ip
        ]
        
        # Capture stdout for user visibility
        captured_output = StringIO()
        sys.stdout = captured_output
        
        try:
            # verify_camera_driver.py returns (success, message, metrics)
            success, message, metrics = verify_camera_driver.main()
            
        except Exception as e:
            success = False
            message = f"Camera driver detection failed: {str(e)}"
            metrics = {"error": str(e)}
            
        finally:
            sys.stdout = original_stdout
            # Print captured output
            output_text = captured_output.getvalue()
            if output_text:
                print(output_text)
        
        record_test_result({
            "success": success,
            "message": message,
            "category": "camera",
            "tags": ["camera", "driver", "imx258"],
            "stats": metrics
        })
        
        assert success, message
    
    finally:
        sys.argv = original_argv
        sys.stdout = original_stdout
