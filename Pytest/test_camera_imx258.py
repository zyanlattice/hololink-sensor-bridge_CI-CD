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
    import re
    from io import StringIO
    
    # Skip mode 0 for cpnx1 devices (only mode 1 supported)
    if device_type and device_type.lower() == "cpnx1" and camera_mode == 0:
        pytest.skip(f"Skipping mode {camera_mode} for device type {device_type} (only mode 1 supported)")
    
    original_argv = sys.argv
    original_stdout = sys.stdout
    
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
        
        # Capture stdout for user visibility
        captured_output = StringIO()
        sys.stdout = captured_output
        
        try:
            # verify_camera_imx258.py returns (success, message, metrics)
            success, message, metrics = verify_camera_imx258.main()
                
        except Exception as e:
            success = False
            message = f"Camera Mode {camera_mode} test failed: {str(e)}"
            metrics = {"camera_mode": camera_mode, "expected_fps": expected_fps, "error": str(e)}
            
        finally:
            sys.stdout = original_stdout
            output_text = captured_output.getvalue()
            if output_text:
                print(output_text)
        
        # Build artifacts list if images were saved
        artifacts = []
        save_dir = metrics.get("save_dir")
        saved_count = metrics.get("saved_images", 0)
        
        if save_dir and saved_count > 0:
            import os
            from pathlib import Path
            
            # Find saved PNG files
            save_path = Path(save_dir)
            if save_path.exists():
                png_files = sorted(save_path.glob("frame_*.png"))
                for png_file in png_files:
                    artifacts.append({
                        "type": "png",
                        "path": str(png_file.relative_to(Path.cwd())) if png_file.is_relative_to(Path.cwd()) else str(png_file),
                        "label": f"Frame {png_file.stem}",
                        "meta": {"save_dir": str(save_dir)}
                    })
        
        # Remove save_dir from metrics (now in artifact metadata)
        if "save_dir" in metrics:
            del metrics["save_dir"]
        
        record_test_result({
            "success": success,
            "message": message,
            "category": "camera",
            "tags": ["camera", "imx258", f"mode_{camera_mode}", f"{expected_fps}fps"],
            "stats": metrics,
            "artifacts": artifacts
        })
        
        assert success, message
    
    finally:
        sys.argv = original_argv
        sys.stdout = original_stdout


@pytest.mark.xfail(reason="IMX258 camera config not optimized", strict=True)
@pytest.mark.hardware
@pytest.mark.camera
@pytest.mark.slow
def test_camera_save_img(hololink_device_ip, camera_id, camera_mode, record_test_result, save_dir):
    """Test IMX258 camera with image saving."""
    import verify_camera_imx258
    import sys
    import re
    from io import StringIO
    
    expected_fps = 30 if camera_mode == 1 else 60
    
    original_argv = sys.argv
    original_stdout = sys.stdout
    
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
        
        # Capture stdout for user visibility
        captured_output = StringIO()
        sys.stdout = captured_output
        
        try:
            # verify_camera_imx258.py returns (success, message, metrics)
            success, message, metrics = verify_camera_imx258.main()
                
        except Exception as e:
            success = False
            message = f"Camera Mode {camera_mode} with image saving failed: {str(e)}"
            metrics = {"camera_mode": camera_mode, "expected_fps": expected_fps, "error": str(e)}
            
        finally:
            sys.stdout = original_stdout
            output_text = captured_output.getvalue()
            if output_text:
                print(output_text)
        
        # Build artifacts list for saved images
        artifacts = []
        save_dir = metrics.get("save_dir")
        saved_count = metrics.get("saved_images", 0)
        
        if save_dir and saved_count > 0:
            import os
            from pathlib import Path
            
            # Find saved PNG files
            save_path = Path(save_dir)
            if save_path.exists():
                png_files = sorted(save_path.glob("frame_*.png"))
                for png_file in png_files:
                    artifacts.append({
                        "type": "png",
                        "path": str(png_file.relative_to(Path.cwd())) if png_file.is_relative_to(Path.cwd()) else str(png_file),
                        "label": f"Frame {png_file.stem}",
                        "meta": {"save_dir": str(save_dir)}
                    })
            
            success = os.path.isfile(save_dir)
            message = f"Camera Mode {camera_mode} with image saving: {'PASS' if success else 'FAIL'}"
        
        # Remove save_dir from metrics (now in artifact metadata)
        if "save_dir" in metrics:
            del metrics["save_dir"]
        
        record_test_result({
            "success": success,
            "message": message,
            "category": "camera",
            "tags": ["camera", "imx258", f"mode_{camera_mode}", "image_save"],
            "stats": metrics,
            "artifacts": artifacts
        })
        
        assert success, message
    
    finally:
        sys.argv = original_argv
        sys.stdout = original_stdout