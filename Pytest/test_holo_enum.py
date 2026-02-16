"""
Test suite for Hololink enumeration verification.
Tests verify_holo_enum.py script for basic connectivity.
"""

import pytest
import sys
from io import StringIO


@pytest.mark.hardware
def test_hololink_enumeration(hololink_device_ip, record_test_result):
    """
    Test Hololink enumeration and basic connectivity.
    
    This test verifies:
    - Hololink device broadcasts are detected
    - Enumeration data is correctly parsed
    - Expected device IP appears in broadcasts
    """
    # Import the verification script
    import verify_holo_enum
    
    # Mock command-line arguments
    original_argv = sys.argv
    original_stdout = sys.stdout
    
    try:
        sys.argv = [
            "verify_holo_enum.py",
            "--count", "10",  # Capture 10 enumerations
            "--timeout", "30",  # 30 second timeout
            "--expected-ip", hololink_device_ip
        ]
        
        # Capture stdout for user visibility
        captured_output = StringIO()
        sys.stdout = captured_output
        
        try:
            # verify_holo_enum.py returns (success, message, metrics)
            success, message, metrics = verify_holo_enum.main()
            
        except Exception as e:
            success = False
            message = f"Hololink enumeration failed: {str(e)}"
            metrics = {"error": str(e), "expected_ip": hololink_device_ip}
            
        finally:
            sys.stdout = original_stdout
            output_text = captured_output.getvalue()
            if output_text:
                print(output_text)
        
        record_test_result({
            "success": success,
            "message": message,
            "category": "system_integration",
            "tags": ["enumeration", "broadcast", "connectivity"],
            "stats": metrics
        })
        
        assert success, message
    
    finally:
        sys.argv = original_argv
        sys.stdout = original_stdout

