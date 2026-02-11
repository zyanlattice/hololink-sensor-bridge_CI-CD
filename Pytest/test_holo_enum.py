"""
Test suite for Hololink enumeration verification.
Tests verify_holo_enum.py script for basic connectivity.
"""

import pytest
import sys


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
    try:
        sys.argv = [
            "verify_holo_enum.py",
            "--count", "10",  # Capture 10 enumerations
            "--timeout", "30",  # 30 second timeout
            "--expected-ip", hololink_device_ip
        ]
        
        # Run the verification
        success = verify_holo_enum.main()
        
        message = f"Hololink Enumeration: {'PASS' if success else 'FAIL'}"
        if not success:
            message += " - Failed to capture expected enumerations or verify IP"
        
        record_test_result({
            "success": success,
            "message": message,
            "stats": {
                "expected_ip": hololink_device_ip,
                "enumeration_count": 10
            }
        })
        
        assert success, message
    
    finally:
        sys.argv = original_argv

