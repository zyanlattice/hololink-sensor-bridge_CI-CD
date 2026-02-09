"""
Test suite for verify_reg.py
Tests APB bus register read/write operations.
"""

import pytest


@pytest.mark.hardware
def test_apb_current_device(hololink_device_ip, device_type, host_interface, record_test_result):
    """Test APB bus for the currently configured device type."""
    import verify_reg
    import sys
    
    original_argv = sys.argv
    try:
        sys.argv = [
            "verify_reg.py",
            "--peer-ip", hololink_device_ip,
            f"--{device_type}",
            "--hostif", str(host_interface)
        ]
        
        try:
            verify_reg.main()
            success = True
            message = f"APB register test: PASS"
        except SystemExit as e:
            success = e.code == 0
            message = f"APB register test: {'PASS' if success else 'FAIL'}"
        
        record_test_result({
            "success": success,
            "message": message,
            "stats": {
                "device_type": device_type,
                "host_interface": host_interface
            }
        })
        
        assert success, message
    
    finally:
        sys.argv = original_argv
