"""
Test suite for verify_multi_mode_imx274.py
Tests IMX274 camera across multiple modes in sequence.
"""

import pytest
import sys
from io import StringIO

@pytest.mark.hardware
@pytest.mark.camera
@pytest.mark.slow
def test_multi_mode_sequence(hololink_device_ip, camera_id, device_type, record_test_result):
    """Test IMX274 camera across multiple modes in sequence (Mode 0, 1, 2, 1, 0)."""
    # Import the verification script
    import verify_multi_mode_imx274
    
    original_argv = sys.argv
    original_stdout = sys.stdout
    
    try:
        sys.argv = [
            "verify_multi_mode_imx274.py",
            "--camera-ip", hololink_device_ip,
            "--camera-id", str(camera_id)
        ]
        
        # Capture stdout for user visibility
        captured_output = StringIO()
        sys.stdout = captured_output
        
        try:
            # verify_multi_mode_imx274.py returns (success, message, metrics)
            success, message, metrics = verify_multi_mode_imx274.main()
            
        except Exception as e:
            success = False
            message = f"Multi-mode camera test failed: {str(e)}"
            metrics = {"error": str(e), "test_modes": [0, 1, 2, 1, 0]}
            
        finally:
            sys.stdout = original_stdout
            output_text = captured_output.getvalue()
            if output_text:
                print(output_text)
        
        record_test_result({
            "success": success,
            "message": message,
            "category": "camera",
            "tags": ["camera", "imx274", "multi_mode", "mode_switching"],
            "stats": metrics
        })
        
        assert success, message
    
    finally:
        sys.argv = original_argv
        sys.stdout = original_stdout
