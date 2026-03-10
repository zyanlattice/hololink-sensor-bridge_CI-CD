"""
Test suite for verify_PTP_imx258.py
Tests PTP clock synchronization and latency measurements for IMX258 camera.
"""

import pytest
import sys
from io import StringIO


@pytest.mark.xfail(reason="MIPI CSI2 soft IP not fully optimized", strict=True)
@pytest.mark.hardware
@pytest.mark.camera
@pytest.mark.slow
def test_ptp_latency_analysis(hololink_device_ip, camera_id, camera_mode, record_test_result):
    """Test complete PTP latency analysis (all 5 metrics) for IMX258."""
    import verify_PTP_imx258
    
    original_argv = sys.argv
    original_stdout = sys.stdout
    captured_output = StringIO()
    
    try:
        sys.argv = [
            "verify_PTP_imx258.py",
            "--camera-ip", hololink_device_ip,
            "--camera-mode", str(camera_mode),
            "--frame-limit", "300"
        ]
        
        # Capture stdout while allowing console output
        sys.stdout = captured_output
        try:
            success, message, metrics = verify_PTP_imx258.main()
        finally:
            sys.stdout = original_stdout
            output = captured_output.getvalue()
            print(output, end='')  # Echo to console
        
        # Check that all latency metrics are present
        required_metrics = [
            "mean_frame_acquisition_ms",
            "mean_cpu_latency_us",
            "mean_overall_latency_ms"
        ]
        
        for metric in required_metrics:
            assert metric in metrics, f"Missing metric: {metric}"
        
        # Check that latencies are reasonable
        assert metrics["mean_frame_acquisition_ms"] < 30, "Frame acquisition time too high"
        assert metrics["mean_overall_latency_ms"] < 50, "Overall latency too high"
        
        record_test_result({
            "success": success,
            "message": message,
            "category": "timing",
            "tags": ["ptp", "latency", "synchronization", "timing", "imx258"],
            "stats": metrics
        })
        
        assert success, message
    
    except Exception as e:
        record_test_result({
            "success": False,
            "message": f"Test runtime error: {str(e)}",
            "category": "timing",
            "tags": ["ptp", "latency", "synchronization", "timing", "imx258"],
            "stats": {}
        })
        raise
    
    finally:
        sys.argv = original_argv
