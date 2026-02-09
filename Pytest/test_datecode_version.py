"""
Test suite for verify_datecode_ver.py
Tests FPGA bitstream datecode and version verification.
"""

import pytest


@pytest.mark.hardware
def test_bitstream_datecode_ver(hololink_device_ip, bitstream_datecode, bitstream_version, record_test_result):
    """Test that FPGA datecode matches expected value."""
    if not bitstream_datecode or not bitstream_version:
        pytest.skip("No bitstream datecode or version provided")
    
    # Import the verification script
    import verify_datecode_ver
    import sys
    
    # Mock command-line arguments
    original_argv = sys.argv
    try:
        sys.argv = [
            "verify_datecode_ver.py",
            "--datecode", bitstream_datecode,
            "--version", bitstream_version
        ]
        
        # Run verification
        datecode_ok, version_ok = verify_datecode_ver.main()
        
        success = datecode_ok and version_ok
        message = f"Datecode verification: {'PASS' if datecode_ok else 'FAIL'}; Version verification: {'PASS' if version_ok else 'FAIL'}"
        
        record_test_result({
            "success": success,
            "message": message,
            "stats": {"datecode_ok": datecode_ok, "version_ok": version_ok}
        })
        
        assert success, message
    
    finally:
        sys.argv = original_argv



