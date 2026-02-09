"""
Test suite for verify_multi_mode_imx258.py
Tests IMX258 camera across multiple modes in sequence.
"""

import pytest

@pytest.mark.xfail(reason="IMX258 camera config not optimized", strict=True)
@pytest.mark.hardware
@pytest.mark.camera
@pytest.mark.slow
def test_multi_mode_sequence(hololink_device_ip, camera_id, record_test_result):
    """Test camera across multiple modes in sequence (Mode 0, 1, 0, 0, 1)."""
    # Import the verification script
    import verify_multi_mode_imx258
    import sys
    
    original_argv = sys.argv
    try:
        sys.argv = [
            "verify_multi_mode_imx258.py",
            "--camera-ip", hololink_device_ip,
            "--camera-id", str(camera_id)
        ]
        
        # Run multi-mode verification
        # Note: verify_multi_mode_imx258.main() runs a sequence of tests
        # and exits with sys.exit(), so we need to catch that
        try:
            verify_multi_mode_imx258.main()
            success = True
            message = "Multi-mode camera test: PASS"
        except SystemExit as e:
            success = e.code == 0
            message = f"Multi-mode camera test: {'PASS' if success else 'FAIL'}"
        
        record_test_result({
            "success": success,
            "message": message,
            "stats": {"test_modes": [0, 1, 0, 0, 1]}
        })
        
        assert success, message
    
    finally:
        sys.argv = original_argv

