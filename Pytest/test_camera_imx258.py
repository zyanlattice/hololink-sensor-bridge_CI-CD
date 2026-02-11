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
def test_camera_modes(hololink_device_ip, camera_id, camera_mode, expected_fps, device_type, record_test_result):
    """Test different IMX258 camera modes."""
    import verify_camera_imx258
    import sys
    
    # Skip mode 0 for cpnx1 devices (only mode 1 supported)
    if device_type and device_type.lower() == "cpnx1" and camera_mode == 0:
        pytest.skip(f"Skipping mode {camera_mode} for device type {device_type} (only mode 1 supported)")
    
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


@pytest.mark.xfail(reason="IMX258 camera config not optimized", strict=True)
@pytest.mark.hardware
@pytest.mark.camera
@pytest.mark.slow
def test_camera_save_img(hololink_device_ip, camera_id, camera_mode, record_test_result, save_dir):
    """Test IMX258 camera with image saving."""
    import verify_camera_imx258
    import sys
    
    expected_fps = 30 if camera_mode == 1 else 60
    
    original_argv = sys.argv
    try:
        sys.argv = [
            "verify_camera_imx258.py",
            "--camera-ip", hololink_device_ip,
            "--camera-id", str(camera_id),
            "--camera-mode", str(camera_mode),
            "--frame-limit", "300",
            "--timeout", "15",
            "--save-images",
            "--holoviz",
            "--save-dir", str(save_dir),
            "--min-fps", str(expected_fps * 0.8)
        ]
        
        success = verify_camera_imx258.main()
        
        message = f"Camera Mode {camera_mode} with image saving: {'PASS' if success else 'FAIL'}"
        
        record_test_result({
            "success": success,
            "message": message,
            "stats": {
                "camera_mode": camera_mode,
                "expected_fps": expected_fps,
                "save_dir": str(save_dir)
            }
        })
        
        assert success, message
    
    finally:
        sys.argv = original_argv