"""
Test suite for verify_host_UDP.py
Tests UDP loopback functionality on host.
"""

import pytest


@pytest.mark.network
def test_udp_loopback(record_test_result):
    """Test UDP loopback on localhost."""
    # Import the verification script
    import verify_host_UDP
    
    # Run UDP loopback test
    success = verify_host_UDP.main()
    
    message = f"UDP loopback test: {'PASS' if success else 'FAIL'}"
    
    record_test_result({
        "success": success,
        "message": message,
        "stats": {}
    })
    
    assert success, message


