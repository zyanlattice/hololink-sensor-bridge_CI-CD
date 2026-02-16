"""
Test suite for verify_device_detection.py
Tests Hololink device network detection.
"""

import pytest
import sys
from io import StringIO


@pytest.mark.hardware
@pytest.mark.network
def test_device_detection(hololink_device_ip, record_test_result):
    """Test that Hololink device can be detected on the network."""
    # Import the verification script
    import verify_device_detection
    
    original_stdout = sys.stdout
    
    try:
        # Capture stdout for user visibility
        captured_output = StringIO()
        sys.stdout = captured_output
        
        try:
            # verify_device_detection.py returns (success, message, metrics)
            success, message, metrics = verify_device_detection.main(timeout_seconds=10)
            
        except Exception as e:
            success = False
            message = f"Device detection failed: {str(e)}"
            metrics = {"error": str(e)}
            
        finally:
            sys.stdout = original_stdout
            output_text = captured_output.getvalue()
            if output_text:
                print(output_text)
        
        record_test_result({
            "success": success,
            "message": message,
            "category": "system_integration",
            "tags": ["device_detection", "network", "enumeration"],
            "stats": metrics
        })
        
        assert success, message
    
    finally:
        sys.stdout = original_stdout
