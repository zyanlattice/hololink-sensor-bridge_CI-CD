"""
Test suite for verify_multi_mode_imx258.py
Tests IMX258 camera across multiple modes in sequence.
"""

import pytest
import sys
from io import StringIO

@pytest.mark.xfail(reason="IMX258 camera config not optimized", strict=True)
@pytest.mark.hardware
@pytest.mark.camera
@pytest.mark.slow
def test_multi_mode_sequence(hololink_device_ip, camera_id, device_type, record_test_result):
    """Test camera across multiple modes in sequence (Mode 0, 1, 0, 0, 1)."""
    # Skip entire test for cpnx1 devices (only mode 1 supported, no multi-mode testing)
    if device_type and device_type.lower() == "cpnx1":
        pytest.skip(f"Skipping multi-mode test for device type {device_type} (only mode 1 supported)")
    
    # Import the verification script
    import verify_multi_mode_imx258
    
    original_argv = sys.argv
    original_stdout = sys.stdout
    
    try:
        sys.argv = [
            "verify_multi_mode_imx258.py",
            "--camera-ip", hololink_device_ip,
            "--camera-id", str(camera_id)
        ]
        
        # Capture stdout for user visibility
        captured_output = StringIO()
        sys.stdout = captured_output
        
        try:
            # verify_multi_mode_imx258.py returns (success, message, metrics)
            success, message, metrics = verify_multi_mode_imx258.main()
            
        except Exception as e:
            success = False
            message = f"Multi-mode camera test failed: {str(e)}"
            metrics = {"error": str(e), "test_modes": [0, 1, 0, 0, 1]}
            
        finally:
            sys.stdout = original_stdout
            output_text = captured_output.getvalue()
            if output_text:
                print(output_text)
        
        record_test_result({
            "success": success,
            "message": message,
            "category": "camera",
            "tags": ["camera", "imx258", "multi_mode", "mode_switching"],
            "stats": metrics
        })
        
        assert success, message
    
    finally:
        sys.argv = original_argv
        sys.stdout = original_stdout

