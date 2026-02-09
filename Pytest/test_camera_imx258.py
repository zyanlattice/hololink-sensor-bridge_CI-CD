"""
Test suite for verify_camera_imx258.py
Tests IMX258 camera functionality including frame capture and FPS.
"""

import pytest


@pytest.mark.xfail(reason="IMX258 camera config not optimized", strict=True)
@pytest.mark.hardware
@pytest.mark.camera
@pytest.mark.slow
@pytest.mark.parametrize("camera_mode,expected_fps", [
    (0, 60),
    (1, 30),
])
def test_camera_modes(hololink_device_ip, camera_id, camera_mode, expected_fps, record_test_result):
    """Test different IMX258 camera modes."""
    import verify_camera_imx258
    import sys
    
    original_argv = sys.argv
    try:
        sys.argv = [
            "verify_camera_imx258.py",
            "--camera-ip", hololink_device_ip,
            "--camera-id", str(camera_id),
            "--camera-mode", str(camera_mode),
            "--frame-limit", "300",
            "--timeout", "15",
            "--min-fps", str(expected_fps * 0.8)  # Allow 20% tolerance
        ]
        
        success = verify_camera_imx258.main()
        
        message = f"Camera Mode {camera_mode} ({expected_fps}fps) test: {'PASS' if success else 'FAIL'}"
        
        record_test_result({
            "success": success,
            "message": message,
            "stats": {
                "camera_mode": camera_mode,
                "expected_fps": expected_fps
            }
        })
        
        assert success, message
    
    finally:
        sys.argv = original_argv
