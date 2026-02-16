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
    import re
    from io import StringIO
    
    original_argv = sys.argv
    original_stdout = sys.stdout
    
    try:
        sys.argv = [
            "verify_reg.py",
            "--peer-ip", hololink_device_ip,
            f"--{device_type}",
            "--hostif", str(host_interface)
        ]
        
        # Capture stdout for user visibility
        captured_output = StringIO()
        sys.stdout = captured_output
        
        try:
            # verify_reg.py returns (success, metrics)
            success, metrics = verify_reg.main()
            message = f"APB register test: {'PASS' if success else 'FAIL'}"
            
        finally:
            sys.stdout = original_stdout
            # Print captured output for debugging
            output_text = captured_output.getvalue()
            if output_text:
                print(output_text)
        
        # Merge device info with metrics from verify_reg
        all_metrics = {
            "device_type": device_type,
            "host_interface": host_interface,
            **metrics  # Add all metrics from verify_reg.py
        }
        
        record_test_result({
            "success": success,
            "message": message,
            "category": "hardware_verification",
            "tags": ["apb", "registers", "hardware"],
            "stats": all_metrics
        })
        
        assert success, message
    
    finally:
        sys.argv = original_argv
        sys.stdout = original_stdout
