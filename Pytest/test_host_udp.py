"""
Test suite for verify_host_UDP.py
Tests UDP loopback functionality on host.
"""

import pytest
import sys
from io import StringIO


@pytest.mark.network
def test_udp_loopback(record_test_result):
    """Test UDP loopback on localhost."""
    # Import the verification script
    import verify_host_UDP
    
    original_stdout = sys.stdout
    
    try:
        # Capture stdout for user visibility
        captured_output = StringIO()
        sys.stdout = captured_output
        
        try:
            # verify_host_UDP.py returns (success, message, metrics)
            success, message, metrics = verify_host_UDP.main()
            
        except Exception as e:
            success = False
            message = f"UDP loopback test failed: {str(e)}"
            metrics = {"error": str(e)}
            
        finally:
            sys.stdout = original_stdout
            output_text = captured_output.getvalue()
            if output_text:
                print(output_text)
        
        record_test_result({
            "success": success,
            "message": message,
            "category": "network",
            "tags": ["udp", "loopback", "localhost"],
            "stats": metrics
        })
        
        assert success, message
    
    finally:
        sys.stdout = original_stdout


