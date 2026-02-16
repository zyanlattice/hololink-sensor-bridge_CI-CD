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
    import re
    from io import StringIO
    
    # Mock command-line arguments
    original_argv = sys.argv
    original_stdout = sys.stdout
    
    try:
        sys.argv = [
            "verify_datecode_ver.py",
            "--datecode", bitstream_datecode,
            "--version", bitstream_version
        ]
        
        # Capture stdout to extract metrics
        captured_output = StringIO()
        sys.stdout = captured_output
        
        try:
            # Run verification
            datecode_ok, version_ok, metrics = verify_datecode_ver.main()
        finally:
            sys.stdout = original_stdout
            output_text = captured_output.getvalue()
            if output_text:
                print(output_text)
        
        # Extract metrics from output if not returned directly
        if not metrics or len(metrics) == 0:
            metrics_match = re.search(r'📊 Metrics: ({.*})', output_text)
            if metrics_match:
                import ast
                try:
                    metrics = ast.literal_eval(metrics_match.group(1))
                except:
                    metrics = {}
        
        # verify_datecode_ver.py already populates all metrics - no need to add anything
        success = datecode_ok and version_ok
        message = f"Datecode verification: {'PASS' if datecode_ok else 'FAIL'}; Version verification: {'PASS' if version_ok else 'FAIL'}"
        
        record_test_result({
            "success": success,
            "message": message,
            "category": "hardware_verification",
            "tags": ["bitstream", "datecode", "version"],
            "stats": metrics
        })
        
        assert success, message
    
    finally:
        sys.argv = original_argv
        sys.stdout = original_stdout



