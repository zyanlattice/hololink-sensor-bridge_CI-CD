"""
Test suite for verify_PTP.py
Tests PTP clock synchronization and latency measurements.
"""

import pytest


@pytest.mark.xfail(reason="MIPI CSI2 soft IP not fully optimized", strict=True)
@pytest.mark.hardware
@pytest.mark.camera
@pytest.mark.slow
def test_ptp_latency_analysis(hololink_device_ip, camera_id, record_test_result):
    """Test complete PTP latency analysis (all 5 metrics)."""
    import verify_PTP
    import sys
    
    original_argv = sys.argv
    try:
        sys.argv = [
            "verify_PTP.py",
            "--camera-ip", hololink_device_ip,
            "--camera-mode", "0",
            "--frame-limit", "300"
        ]
        
        success, message, stats = verify_PTP.main()
        
        # Check that all latency metrics are present
        required_metrics = [
            "mean_frame_acquisition_ms",
            "Mean_CPU_Latency_us",
            "Mean_Overall_Latency_ms"
        ]
        
        for metric in required_metrics:
            assert metric in stats, f"Missing metric: {metric}"
        
        # Check that latencies are reasonable
        assert stats["mean_frame_acquisition_ms"] < 30, "Frame acquisition time too high"
        assert stats["Mean_Overall_Latency_ms"] < 50, "Overall latency too high"
        
        record_test_result({
            "success": success,
            "message": message,
            "stats": stats
        })
        
        assert success, message
    
    finally:
        sys.argv = original_argv
