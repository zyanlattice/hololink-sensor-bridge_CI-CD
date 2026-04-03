"""
Test suite for verify_camera_imx274.py
Tests IMX274 camera functionality including frame capture and FPS.
"""

import pytest

@pytest.mark.quick
@pytest.mark.hardware
@pytest.mark.camera
@pytest.mark.parametrize("camera_mode,expected_fps", [
    (0, 60),  # 4K 60fps
    (1, 60),  # 1080p 60fps
])
def test_camera_modes(hololink_device_ip, camera_id, camera_mode, expected_fps, device_type, record_test_result):
    """Test different IMX274 camera modes."""
    import verify_camera_imx274
    import sys
    import re
    from io import StringIO
    import time
    
    original_argv = sys.argv
    original_stdout = sys.stdout
    
    # Record start time to filter files created during this test
    test_start_time = time.time()
    
    try:
        sys.argv = [
            "verify_camera_imx274.py",
            "--camera-ip", hololink_device_ip,
            "--camera-id", str(camera_id),
            "--camera-mode", str(camera_mode),
            "--frame-limit", "300",
            "--timeout", "15"
        ]
        
        # Capture stdout for user visibility
        captured_output = StringIO()
        sys.stdout = captured_output
        
        try:
            # verify_camera_imx274.py returns (success, message, metrics)
            success, message, metrics = verify_camera_imx274.main()
                
        except Exception as e:
            success = False
            message = f"Camera Mode {camera_mode} test failed: {str(e)}"
            metrics = {"camera_mode": camera_mode, "expected_fps": expected_fps, "error": str(e)}
            
        finally:
            sys.stdout = original_stdout
            output_text = captured_output.getvalue()
            if output_text:
                print(output_text)
        
        # Build artifacts list for saved images created during THIS test
        artifacts = []
        save_dir = metrics.get("save_dir")
        saved_count = metrics.get("saved_images", 0)
        
        if save_dir and saved_count > 0:
            import os
            from pathlib import Path
            
            # Find PNG files created during this test run only
            save_path = Path(save_dir)
            if save_path.exists():
                png_files = sorted([
                    f for f in save_path.glob("frame_*.png")
                    if f.stat().st_mtime >= test_start_time
                ])
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
            "tags": ["camera", "imx274", f"mode_{camera_mode}", f"{expected_fps}fps"],
            "stats": metrics,
            "artifacts": artifacts
        })
        
        assert success, message
    
    finally:
        sys.argv = original_argv
        sys.stdout = original_stdout


@pytest.mark.hardware
@pytest.mark.camera
@pytest.mark.slow
def test_camera_save_img(hololink_device_ip, camera_id, record_test_result, save_dir):
    """Test IMX274 camera with image saving (uses mode 1 for better performance)."""
    import verify_camera_imx274
    import sys
    import re
    from io import StringIO
    import time
    
    # Use mode 1 (1080p) instead of mode 0 (4K) for image saving
    # to avoid excessive HolovizOp rendering overhead
    camera_mode = 1  
    expected_fps = 60  # IMX274 mode 1 is 60fps
    
    original_argv = sys.argv
    original_stdout = sys.stdout
    
    # Record start time to filter files created during this test
    test_start_time = time.time()
    
    try:
        sys.argv = [
            "verify_camera_imx274.py",
            "--camera-ip", hololink_device_ip,
            "--camera-id", str(camera_id),
            "--camera-mode", str(camera_mode),
            "--frame-limit", "300",
            "--timeout", "15",
            "--save-images",
            "--holoviz",
            "--save-dir", str(save_dir)
        ]
        
        # Capture stdout for user visibility
        captured_output = StringIO()
        sys.stdout = captured_output
        
        try:
            # verify_camera_imx274.py returns (success, message, metrics)
            success, message, metrics = verify_camera_imx274.main()
                
        except Exception as e:
            success = False
            message = f"Camera Mode {camera_mode} with image saving failed: {str(e)}"
            metrics = {"camera_mode": camera_mode, "expected_fps": expected_fps, "error": str(e)}
            
        finally:
            sys.stdout = original_stdout
            output_text = captured_output.getvalue()
            if output_text:
                print(output_text)
        
        # Build artifacts list for saved images created during THIS test
        artifacts = []
        save_dir = metrics.get("save_dir")
        saved_count = metrics.get("saved_images", 0)
        
        if save_dir and saved_count > 0:
            import os
            from pathlib import Path
            
            # Find PNG files created during this test run only
            save_path = Path(save_dir)
            if save_path.exists():
                png_files = sorted([
                    f for f in save_path.glob("frame_*.png")
                    if f.stat().st_mtime >= test_start_time
                ])
                for png_file in png_files:
                    artifacts.append({
                        "type": "png",
                        "path": str(png_file.relative_to(Path.cwd())) if png_file.is_relative_to(Path.cwd()) else str(png_file),
                        "label": f"Frame {png_file.stem}",
                        "meta": {"save_dir": str(save_dir)}
                    })
            
            # Validate that images were actually saved
            if saved_count == 0 or len(png_files) == 0:
                success = False
                message = f"Camera Mode {camera_mode} with image saving FAILED: No images saved"
                success = False
                message = f"Camera Mode {camera_mode} with image saving FAILED: No images saved"
        
        # Remove save_dir from metrics (now in artifact metadata)
        if "save_dir" in metrics:
            del metrics["save_dir"]
        
        record_test_result({
            "success": success,
            "message": message,
            "category": "camera",
            "tags": ["camera", "imx274", f"mode_{camera_mode}", "image_save"],
            "stats": metrics,
            "artifacts": artifacts
        })
        
        assert success, message
    
    finally:
        sys.argv = original_argv
        sys.stdout = original_stdout



@pytest.mark.hardware
@pytest.mark.camera
@pytest.mark.slow
def test_camera_stereo_save_img(hololink_device_ip, camera_id, record_test_result, save_dir):
    """Test STEREO IMX274 cameras (dual camera setup) with image saving.
    
    Tests both left and right cameras simultaneously with side-by-side visualization.
    Saves individual frames from each camera plus fullscreen stereo screenshots.
    Uses mode 1 (1080p) for better performance with HolovizOp.
    """
    import verify_camera_stereo_imx274
    import sys
    import re
    from io import StringIO
    import time
    
    # Use mode 1 (1080p) instead of mode 0 (4K) for image saving
    # to avoid excessive HolovizOp rendering overhead
    camera_mode = 1  
    expected_fps = 60  # IMX274 mode 1 is 60fps
    
    original_argv = sys.argv
    original_stdout = sys.stdout
    
    # Record start time to filter files created during this test
    test_start_time = time.time()
    
    try:
        sys.argv = [
            "verify_camera_stereo_imx274.py",
            "--camera-ip", hololink_device_ip,
            "--camera-mode", str(camera_mode),
            "--frame-limit", "300",
            "--timeout", "15",
            "--save-images",
            "--holoviz",
            "--save-dir", str(save_dir)
        ]
        
        # Capture stdout for user visibility
        captured_output = StringIO()
        sys.stdout = captured_output
        
        try:
            # verify_camera_stereo_imx274.py returns (success, message, metrics)
            success, message, metrics = verify_camera_stereo_imx274.main()
                
        except Exception as e:
            success = False
            message = f"Camera Mode {camera_mode} with image saving failed: {str(e)}"
            metrics = {"camera_mode": camera_mode, "expected_fps": expected_fps, "error": str(e)}
            
        finally:
            sys.stdout = original_stdout
            output_text = captured_output.getvalue()
            if output_text:
                print(output_text)
        
        # Build artifacts list for saved images created during THIS test
        artifacts = []
        save_dir_path = metrics.get("save_dir")
        
        # Stereo camera returns separate counts for left, right, and screenshots
        saved_count_left = metrics.get("saved_images_left", 0)
        saved_count_right = metrics.get("saved_images_right", 0)
        saved_count_screenshot = metrics.get("saved_images_screenshot", 0)
        total_saved = saved_count_left + saved_count_right + saved_count_screenshot
        
        if save_dir_path and total_saved > 0:
            import os
            from pathlib import Path
            
            # Find PNG files created during this test run only
            save_path = Path(save_dir_path)
            if save_path.exists():
                # Collect left camera frames
                left_files = sorted([
                    f for f in save_path.glob("left_frame_*.png")
                    if f.stat().st_mtime >= test_start_time
                ])
                for png_file in left_files:
                    artifacts.append({
                        "type": "png",
                        "path": str(png_file.relative_to(Path.cwd())) if png_file.is_relative_to(Path.cwd()) else str(png_file),
                        "label": f"Left Camera - {png_file.stem}",
                        "meta": {"camera": "left", "save_dir": str(save_dir_path)}
                    })
                
                # Collect right camera frames
                right_files = sorted([
                    f for f in save_path.glob("right_frame_*.png")
                    if f.stat().st_mtime >= test_start_time
                ])
                for png_file in right_files:
                    artifacts.append({
                        "type": "png",
                        "path": str(png_file.relative_to(Path.cwd())) if png_file.is_relative_to(Path.cwd()) else str(png_file),
                        "label": f"Right Camera - {png_file.stem}",
                        "meta": {"camera": "right", "save_dir": str(save_dir_path)}
                    })
                
                # Collect stereo screenshots (fullscreen holoviz capture)
                screenshot_files = sorted([
                    f for f in save_path.glob("stereo_screenshot_*.png")
                    if f.stat().st_mtime >= test_start_time
                ])
                for png_file in screenshot_files:
                    artifacts.append({
                        "type": "png",
                        "path": str(png_file.relative_to(Path.cwd())) if png_file.is_relative_to(Path.cwd()) else str(png_file),
                        "label": f"Stereo Screenshot - {png_file.stem}",
                        "meta": {"camera": "stereo", "save_dir": str(save_dir_path)}
                    })
                
                total_files_found = len(left_files) + len(right_files) + len(screenshot_files)
            
                # Validate that images were actually saved
                if total_saved == 0 or total_files_found == 0:
                    success = False
                    message = f"Stereo Camera Mode {camera_mode} with image saving FAILED: Expected {total_saved} images, found {total_files_found}"
        
        # Remove save_dir from metrics (now in artifact metadata)
        if "save_dir" in metrics:
            del metrics["save_dir"]
        
        record_test_result({
            "success": success,
            "message": message,
            "category": "camera",
            "tags": ["camera", "imx274", "stereo", f"mode_{camera_mode}", "image_save", "dual_camera"],
            "stats": metrics,
            "artifacts": artifacts
        })
        
        assert success, message
    
    finally:
        sys.argv = original_argv
        sys.stdout = original_stdout
