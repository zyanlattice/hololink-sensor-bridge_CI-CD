
import re
import subprocess
from typing import Optional, Tuple
import sys
from pathlib import Path
import logging
import time
import argparse
import threading

# Configure logging to show in terminal
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


# Add parent scripts directory to path for imports
_script_dir = Path(__file__).parent.parent 
sys.path.insert(0, str(_script_dir))


import cuda.bindings.driver as cuda
import holoscan
import hololink as hololink_module
import datetime
import math

# Timestamp constants 
MS_PER_SEC = 1000.0
US_PER_SEC = 1000.0 * MS_PER_SEC
NS_PER_SEC = 1000.0 * US_PER_SEC
SEC_PER_NS = 1.0 / NS_PER_SEC


def get_timestamp(metadata: dict, name: str) -> float:
    """Extract PTP timestamp from metadata (seconds + nanoseconds)."""
    s = metadata.get(f"{name}_s", 0)
    f = metadata.get(f"{name}_ns", 0)
    f *= SEC_PER_NS
    return s + f


def save_timestamp(metadata: dict, name: str, timestamp: datetime.datetime) -> None:
    """Store datetime as seconds + nanoseconds in metadata."""
    f, s = math.modf(timestamp.timestamp())
    metadata[f"{name}_s"] = int(s)
    metadata[f"{name}_ns"] = int(f * NS_PER_SEC)


# REMOVED: InstrumentedTimeProfiler
# The official approach doesn't manually add timestamps from Python operators.
# Custom timestamps using datetime.now() create Unix epoch timestamps (~1.77 billion seconds)
# which can't be compared to FPGA PTP timestamps (relative to boot, ~0-100 seconds).
# This causes spurious latency calculations (e.g., 1.77 billion - 8 = 50,000+ second "latency").
# Instead, we rely solely on timestamps in metadata from the receiver, which are in PTP domain.
    

class FrameCounterOp(holoscan.core.Operator):
    """Terminal operator to count frames and perform complete PTP latency analysis."""
    
    def __init__(self, *args, frame_limit=50, requested_limit=None, app=None, pass_through=False, camera=None, hololink=None, save_images=False, camera_mode=0, **kwargs):
        self.pass_through = pass_through
        self.frame_limit = frame_limit  # Actual capture limit (requested + 10 for dropping)
        self.requested_limit = requested_limit or frame_limit  # What user requested (for reporting)
        self.frame_count = 0
        self.start_time = None
        self.timestamps = []  # System clock timestamps
        self.ptp_timestamps = []  # PTP timestamps from FPGA
        self.camera_mode = camera_mode  # Store for mode-aware tolerance checking
        
        # Store PTP timestamps for frame interval analysis (official approach)
        self.frame_start_times = []      # timestamp: FPGA first data byte (PTP domain)
        self.frame_end_times = []        # metadata: FPGA last data byte + metadata (PTP domain)
        
        # Diagnostic counters
        self.invalid_domain_count = 0    # Timestamps > 10000s (Unix epoch)
        self.invalid_ordering_count = 0  # frame_end <= frame_start
        self.missing_timestamp_count = 0 # None values
        
        self.app = app
        self.camera = camera
        self.hololink = hololink
        self.save_images = save_images
        
        super().__init__(*args, **kwargs)
        
    def setup(self, spec):
        spec.input("input")
        # No output port - this is a terminal operator like MonitorOperator in latency.py
        
    def compute(self, op_input, op_output, context):
        # Check BEFORE incrementing to prevent off-by-one errors
        if self.frame_count >= self.frame_limit:
            in_message = op_input.receive("input")
            return
        
        # Receive message FIRST - this makes self.metadata available
        in_message = op_input.receive("input")
        
        if self.start_time is None:
            self.start_time = time.time()
        
        self.frame_count += 1
        self.timestamps.append(time.time())
        
        # Read PTP timestamps from FPGA - copy BOTH timestamps immediately to avoid race condition
        # (metadata buffer is shared and can be updated by receiver between reads)
        try:
            # CRITICAL: Read both timestamps as close together as possible to minimize race window
            # Official script creates tuple immediately: (timestamp, metadata, host_time)
            frame_start_s = get_timestamp(self.metadata, "timestamp")      # FPGA: first data byte
            frame_end_s = get_timestamp(self.metadata, "metadata")         # FPGA: last data byte + metadata
            timestamp_pair = (frame_start_s, frame_end_s)  # Store as tuple immediately (like official script)
            
            # Validate timestamp domain: PTP timestamps are relative to device boot (< 1000 seconds)
            # Unix epoch timestamps are ~1.77 billion seconds (March 2026)
            # Reject Unix epoch timestamps - they indicate receiver firmware bug
            MAX_PTP_TIMESTAMP = 10000  # 10000 seconds = ~2.7 hours since boot (generous)
            MAX_FRAME_ACQ_TIME = 0.1   # 100ms max for frame acquisition (catches race condition corruption)
            
            frame_start_s, frame_end_s = timestamp_pair  # Unpack from tuple
            
            # Also check that frame_end > frame_start (should be ~16-20ms apart)
            is_valid_ptp_start = frame_start_s is not None and 0 < frame_start_s < MAX_PTP_TIMESTAMP
            is_valid_ptp_end = frame_end_s is not None and 0 < frame_end_s < MAX_PTP_TIMESTAMP
            is_valid_ordering = frame_end_s > frame_start_s if (is_valid_ptp_start and is_valid_ptp_end) else False
            is_valid_acq_time = (frame_end_s - frame_start_s) < MAX_FRAME_ACQ_TIME if is_valid_ordering else False
            
            if is_valid_ptp_start and is_valid_ptp_end and is_valid_ordering and is_valid_acq_time:
                # Both timestamps are in PTP domain, properly ordered, and reasonable acquisition time
                self.frame_start_times.append(frame_start_s)
                self.frame_end_times.append(frame_end_s)
                self.ptp_timestamps.append(frame_end_s)
                
                if self.frame_count == 1:
                    logging.info(f"✓ PTP metadata available (frame_start={frame_start_s:.3f}s, frame_end={frame_end_s:.3f}s)")
            else:
                # One or both timestamps are Unix epoch or invalid - reject frame
                # Track specific failure reasons
                if not is_valid_ptp_start or not is_valid_ptp_end:
                    self.invalid_domain_count += 1
                    reason = "domain (Unix epoch)"
                elif not is_valid_ordering:
                    self.invalid_ordering_count += 1
                    reason = "ordering (end <= start)"
                elif not is_valid_acq_time:
                    self.invalid_ordering_count += 1  # Count as ordering issue (partial corruption)
                    acq_time_ms = (frame_end_s - frame_start_s) * 1000
                    reason = f"acquisition time too large ({acq_time_ms:.1f}ms)"
                else:
                    reason = "unknown"
                
                if self.frame_count == 1:
                    logging.warning(f"⚠️  Invalid timestamp {reason}: frame_start={frame_start_s:.3f}s, frame_end={frame_end_s:.3f}s")
                elif self.frame_count % 50 == 0:  # Log occasional warnings
                    logging.warning(f"Frame {self.frame_count}: Invalid timestamp {reason} (start={frame_start_s:.3f}s, end={frame_end_s:.3f}s)")
                
                self.frame_start_times.append(None)
                self.frame_end_times.append(None)
                self.ptp_timestamps.append(None)
        except Exception as e:
            logging.warning(f"Could not read PTP timestamps from metadata: {e}")
            self.missing_timestamp_count += 1
            # Append None for missing data
            self.frame_start_times.append(None)
            self.frame_end_times.append(None)
            self.ptp_timestamps.append(None)
        
        

        if self.frame_count % 10 == 0:
            elapsed = time.time() - self.start_time
            fps = self.frame_count / elapsed if elapsed > 0 else 0
            logging.info(f"Frames received: {self.frame_count}, FPS: {fps:.2f}")

        # Stop application when we reach frame_limit
        if self.frame_count >= self.frame_limit:
            logging.info(f"Reached frame limit ({self.frame_limit}), stopping application...")
            
            if not self.save_images:
                def stop_everything():
                    try:
                        if self.camera:
                            self.camera.stop()
                    except Exception as e:
                        logging.warning(f"Error stopping camera: {e}")
                    
                    try:
                        if self.hololink:
                            self.hololink.stop()
                    except Exception as e:
                        logging.warning(f"Error stopping hololink: {e}")
                    
                    time.sleep(0.5)
                    try:
                        self.app.stop()
                    except Exception as e:
                        logging.warning(f"Error stopping app: {e}")
                
                stop_thread = threading.Thread(target=stop_everything, daemon=True)
                stop_thread.start()
    
    def get_ptp_timing_stats(self, drop_frames=5) -> dict:
        """
        Analyze PTP frame timing and jitter (official approach).
        
        Args:
            drop_frames: Number of frames to drop from start AND end (like official script).
                        Default=5 matches official linux_imx258_latency.py behavior.
                        Set to 0 to analyze all frames (more rigorous but may include outliers).
        """
        import statistics
        
        # Filter out None values (frames where PTP metadata wasn't available)
        valid_indices = [i for i in range(len(self.frame_start_times)) 
                        if self.frame_start_times[i] is not None 
                        and self.frame_end_times[i] is not None]
        
        # Drop first/last N frames to match official script's "settled_timestamps" approach
        # Official script: settled_timestamps = recorder_queue[5:-5]
        if drop_frames > 0 and len(valid_indices) > drop_frames * 2:
            valid_indices = valid_indices[drop_frames:-drop_frames]
            logging.info(f"Dropped first/last {drop_frames} frames for stability (official script approach)")
        
        if len(valid_indices) < 2:
            return {"error": "Insufficient PTP timestamp data"}
        
        # Calculate frame acquisition time (sensor readout + FPGA processing)
        frame_acquisition_times = []
        validated_indices = []
        
        for i in valid_indices:
            frame_start = self.frame_start_times[i]
            frame_end = self.frame_end_times[i]
            
            # Frame acquisition = time from sensor start to FPGA metadata ready
            frame_time_dt = frame_end - frame_start  # Expected: ~19.4ms for IMX258 in mode 0
            
            # Sanity check: should be positive and < 1 second (catches remaining outliers)
            if frame_time_dt < 0 or frame_time_dt > 0.1:
                logging.warning(f"Unreasonable frame acquisition time in frame {i}: {frame_time_dt*1000:.2f}ms (skipping)")
                continue
            
            frame_acquisition_times.append(frame_time_dt)
            validated_indices.append(i)
        
        # Check if we have enough valid data after filtering
        if len(frame_acquisition_times) < 2:
            logging.error(f"Insufficient valid PTP data: only {len(frame_acquisition_times)} frames with valid timestamps")
            return {"error": "Insufficient valid PTP timestamp data after filtering invalid timestamps"}
        
        # Calculate inter-frame jitter using only validated frames
        valid_ptp_timestamps = [self.frame_end_times[i] for i in validated_indices]
        ptp_intervals = [valid_ptp_timestamps[i+1] - valid_ptp_timestamps[i] 
                        for i in range(len(valid_ptp_timestamps) - 1)]
        
        # Mode-aware tolerance: 60fps (mode 0) = 16.67ms, 30fps (mode 1) = 33.33ms
        expected_interval_ms = 16.67 if self.camera_mode == 0 else 33.33
        tolerance = 1.05  # 5% tolerance
        fail_cnt = sum(1 for intv in ptp_intervals if intv*1000 >= expected_interval_ms * tolerance)
        
        # Calculate percentile statistics for outlier analysis
        sorted_acq_times = sorted(frame_acquisition_times)
        p95_idx = int(len(sorted_acq_times) * 0.95)
        p99_idx = int(len(sorted_acq_times) * 0.99)
        
        # Debug: log first few intervals for diagnostics
        if len(ptp_intervals) >= 5:
            logging.info(f"DEBUG: First 5 frame intervals (ms): {[f'{intv*1000:.2f}' for intv in ptp_intervals[:5]]}")
            logging.info(f"DEBUG: First 6 frame_end timestamps (s): {[f'{ts:.3f}' for ts in valid_ptp_timestamps[:6]]}")
        
        return {
            "frame_count": self.requested_limit,  # Report requested count, not actual captured count
            "frames_captured": self.frame_count,   # Actual frames captured (requested + 10)
            "valid_frames": len(validated_indices),
            "invalid_frames": self.frame_count - len(validated_indices),
            
            # Frame acquisition time (sensor readout + FPGA processing)
            # Expected: ~19.4ms for IMX258 (15.8ms sensor + 3.6ms FPGA overhead)
            "mean_frame_acquisition_ms": statistics.mean(frame_acquisition_times) * 1000,
            "min_frame_acquisition_ms": min(frame_acquisition_times) * 1000,
            "max_frame_acquisition_ms": max(frame_acquisition_times) * 1000,
            "p95_frame_acquisition_ms": sorted_acq_times[p95_idx] * 1000 if len(sorted_acq_times) > 0 else 0,
            "p99_frame_acquisition_ms": sorted_acq_times[p99_idx] * 1000 if len(sorted_acq_times) > 0 else 0,
            "stdev_frame_acquisition_us": statistics.stdev(frame_acquisition_times) * 1000000 if len(frame_acquisition_times) > 1 else 0,
            
            # Inter-frame jitter (PTP clock stability)
            "mean_frame_interval_ms": statistics.mean(ptp_intervals) * 1000 if ptp_intervals else 0,
            "stdev_frame_interval_ms": statistics.stdev(ptp_intervals) * 1000 if len(ptp_intervals) > 1 else 0,
            "frame_jitter_pct": (statistics.stdev(ptp_intervals) / statistics.mean(ptp_intervals) * 100) if ptp_intervals and statistics.mean(ptp_intervals) > 0 else 0,
            "interval_fail_count": fail_cnt,
            
            # Metadata for reporting
            "expected_interval_ms": expected_interval_ms,
            "camera_mode": self.camera_mode,
            "test_duration_sec": valid_ptp_timestamps[-1] - valid_ptp_timestamps[0] if len(valid_ptp_timestamps) > 1 else 0,
        }
        
        # Debug: print first few intervals to diagnose timestamp issue
        if len(ptp_intervals) >= 5:
            logging.info(f"DEBUG: First 5 frame intervals (seconds): {[f'{intv:.6f}' for intv in ptp_intervals[:5]]}")
            logging.info(f"DEBUG: First 6 frame_end timestamps: {[f'{ts:.3f}' for ts in valid_ptp_timestamps[:6]]}")
        
        return retval


def _measure_hololink_ptp(camera_ip: str = "192.168.0.2", frame_limit: int = 300, timeout_seconds: int = 15, camera_mode: int = 0 ) -> Tuple[Optional[int], Optional[int]]:
    """
    Measure actual hololink throughput by receiving frames from camera.
    Uses exact same initialization as verify_camera_imx258.py, just counts frames without processing.
    
    Args:
        camera_ip: IP of Hololink device
        frame_limit: Number of frames to receive
        timeout_seconds: Maximum time to wait
        
    Returns:
        Throughput in Mbps, or None if measurement failed
    """
    
    hololink = None
    camera = None
    cu_context = None
    application = None
    stop_event = threading.Event()
    
    try:
        logging.info(f"Measuring hololink throughput: {frame_limit} frames from {camera_ip}...")
        
        # Initialize CUDA (exactly like verify_camera_imx258.py)
        logging.info("Initializing CUDA...")
        (cu_result,) = cuda.cuInit(0)
        if cu_result != cuda.CUresult.CUDA_SUCCESS:
            logging.warning(f"CUDA initialization failed: {cu_result}")
            return None
        
        cu_device_ordinal = 0
        cu_result, cu_device = cuda.cuDeviceGet(cu_device_ordinal)
        if cu_result != cuda.CUresult.CUDA_SUCCESS:
            logging.warning(f"Failed to get CUDA device: {cu_result}")
            return None
        
        cu_result, cu_context = cuda.cuDevicePrimaryCtxRetain(cu_device)
        if cu_result != cuda.CUresult.CUDA_SUCCESS:
            logging.warning(f"Failed to create CUDA context: {cu_result}")
            return None
        
        logging.info("CUDA initialized successfully")
        
        # Find Hololink channel (exactly like verify_camera_imx258.py)
        logging.info(f"Searching for Hololink device at {camera_ip}...")
        channel_metadata = hololink_module.Enumerator.find_channel(channel_ip=camera_ip)
        if not channel_metadata:
            logging.warning(f"Failed to find Hololink device at {camera_ip}")
            return None
        
        logging.info("Hololink device found")
        
        # Initialize camera (exactly like verify_camera_imx258.py)
        hololink_channel = hololink_module.DataChannel(channel_metadata)
        camera = hololink_module.sensors.imx258.Imx258(hololink_channel, camera_id=0)
        #camera_mode_enum = hololink_module.sensors.imx258.Imx258_Mode(camera_mode)  # Mode 2 = 60fps_cus
        
        # Minimal application - just receiver + frame counter, no processing
        class ThroughputApplication(holoscan.core.Application):
            """Minimal app for throughput measurement."""
            
            def __init__(self, cuda_ctx, cuda_dev_ord, hl_chan, cam, capture_limit, requested_limit, camera_mode=0):
                super().__init__()
                self._cuda_context = cuda_ctx
                self._cuda_device_ordinal = cuda_dev_ord
                self._hololink_channel = hl_chan
                self._camera = cam
                self._capture_limit = capture_limit  # Actual frames to capture (requested + 10)
                self._requested_limit = requested_limit  # What user requested (for reporting)
                self._camera_mode = camera_mode
                self._frame_counter = None
                # Enable metadata access from C++ receiver (required for PTP timestamps)
                self.enable_metadata(True)
            
            def compose(self):
                # Use CountCondition to limit frames (like linux_imx258_player.py)
                # Use capture_limit (requested + 10) to get extra frames for dropping
                if self._capture_limit:
                    self._count = holoscan.conditions.CountCondition(
                        self,
                        name="count",
                        count=self._capture_limit,
                    )
                    count_condition = self._count
                else:
                    self._ok = holoscan.conditions.BooleanCondition(
                        self, name="ok", enable_tick=True
                    )
                    count_condition = self._ok
                
                # Receiver operator - raw frame receive
                receiver_operator = hololink_module.operators.LinuxReceiverOperator(
                    self,
                    count_condition,
                    name="receiver",
                    frame_size=self._camera._width * self._camera._height * 2,  # RAW10, 16-bit per pixel
                    frame_context=self._cuda_context,
                    hololink_channel=self._hololink_channel,
                    device=self._camera
                )
                
                # Frame counter as terminal operator (simplified: no intermediate profiler)
                self._frame_counter = FrameCounterOp(
                    self,
                    name="frame_counter",
                    frame_limit=self._capture_limit,
                    requested_limit=self._requested_limit,
                    pass_through=False,
                    camera_mode=self._camera_mode
                )
                
                # Pipeline flow: receiver → frame_counter (terminal, no profiler)
                self.add_flow(receiver_operator, self._frame_counter, {("output", "input")})
            
            def get_frame_count(self) -> int:
                return self._frame_counter.frame_count if self._frame_counter else 0
            
            def get_fps(self) -> float:
                if not self._frame_counter or not self._frame_counter.start_time:
                    return 0.0
                elapsed = time.time() - self._frame_counter.start_time
                return self._frame_counter.frame_count / elapsed if elapsed > 0 else 0.0
        
        # Create application
        # Add 10 frames to capture limit (for dropping first/last 5) but report requested count
        FRAMES_TO_DROP = 10  # Drop 5 from start + 5 from end
        capture_limit = frame_limit + FRAMES_TO_DROP
        logging.info(f"Capturing {capture_limit} frames (analyzing {frame_limit} after dropping first/last 5)...")
        
        application = ThroughputApplication(
            cu_context,
            cu_device_ordinal,
            hololink_channel,
            camera,
            capture_limit,
            frame_limit,
            camera_mode,
        )
        
        # Start Hololink and camera (MUST follow official sequence for PTP)
        logging.info("Starting Hololink...")
        hololink = hololink_channel.hololink()
        hololink.start()
        hololink.reset()  # Ensure clean state and PTP sync

        # NOW configure camera AFTER PTP is ready
        logging.info("Configuring camera...")
        camera.configure_mipi_lane(4, 371)
        camera.configure(camera_mode)
        camera.set_focus(-140)
        camera.set_exposure(0x0600)
        camera.set_analog_gain(0x0180)
        camera.start()
        
        start_time = time.time()
        
        # Run application in thread
        def run_app():
            try:
                application.run()  # Will complete naturally when CountCondition reaches frame_limit
            except Exception as e:
                logging.warning(f"Application exception: {e}")
        
        app_thread = threading.Thread(target=run_app, daemon=True)
        app_thread.start()
        
        # Monitor for completion - the graph will naturally complete when it reaches frame_limit
        poll_interval = 0.1
        first_frame_time = None
        last_frame_time = None
        max_wait_time = timeout_seconds + 30  # Extra time for GXF setup + frame capture
        start_wait = time.time()
        
        # Loop until app completes (with timeout safety)
        while app_thread.is_alive():
            time.sleep(poll_interval)
            
            frames = application.get_frame_count()
            
            # Track when first frame arrives
            if frames > 0 and first_frame_time is None:
                first_frame_time = time.time()
                logging.info(f"First frame received after {time.time() - start_time:.2f}s")
            
            # Track when the LAST frame arrived
            if frames > 0:
                last_frame_time = time.time()
            
            # Safety timeout: if no new frames for timeout_seconds, abort
            if last_frame_time is not None and (time.time() - last_frame_time) > timeout_seconds:
                logging.error(f"No new frames for {timeout_seconds}s, aborting...")
                try:
                    application.interrupt()
                except Exception as e:
                    logging.warning(f"Error interrupting app: {e}")
                break
            
            # Safety timeout: if total time exceeds max, abort
            if (time.time() - start_wait) > max_wait_time:
                logging.error(f"Total wait time exceeded {max_wait_time}s, aborting...")
                try:
                    application.interrupt()
                except Exception as e:
                    logging.warning(f"Error interrupting app: {e}")
                break
        
        # Wait for thread to join (should be instant or very quick now that graph completed)
        if app_thread.is_alive():
            logging.info("Waiting for application thread to finish...")
            app_thread.join(timeout=3.0)
            if app_thread.is_alive():
                logging.warning("Application thread still alive after 3s timeout")
        
        stop_event.set()     
            
        # Report PTP frame timing analysis (simplified approach)
        ptp_stats = application._frame_counter.get_ptp_timing_stats()
        if ptp_stats and "error" not in ptp_stats:
            logging.info(f"\n{'='*70}")
            logging.info(f"PTP Frame Timing Analysis (FPGA timestamps only)\n{'='*70}")
            logging.info(f"Frames captured: {ptp_stats['frames_captured']} (requested: {ptp_stats['frame_count']}, +10 for dropping first/last 5)")
            logging.info(f"Frames analyzed: {ptp_stats['valid_frames']}/{ptp_stats['frame_count']} (after dropping & filtering)")
            
            # Show breakdown of invalid frames
            frame_counter = application._frame_counter
            total_invalid = frame_counter.invalid_domain_count + frame_counter.invalid_ordering_count + frame_counter.missing_timestamp_count
            if total_invalid > 0:
                logging.info(f"Invalid frames breakdown:")
                logging.info(f"   Domain violations (Unix epoch): {frame_counter.invalid_domain_count}")
                logging.info(f"   Ordering violations (end <= start): {frame_counter.invalid_ordering_count}")
                logging.info(f"   Missing timestamps: {frame_counter.missing_timestamp_count}")
            logging.info(f"")
            
            logging.info(f"Frame Acquisition Time (sensor readout + FPGA processing):")
            logging.info(f"   Mean: {ptp_stats['mean_frame_acquisition_ms']:.3f} ms")
            logging.info(f"   Expected: ~19.4ms (sensor 15.8ms + FPGA 3.6ms)")
            logging.info(f"   Min/P95/P99/Max: {ptp_stats['min_frame_acquisition_ms']:.3f} / {ptp_stats['p95_frame_acquisition_ms']:.3f} / {ptp_stats['p99_frame_acquisition_ms']:.3f} / {ptp_stats['max_frame_acquisition_ms']:.3f} ms")
            logging.info(f"   Std Dev: {ptp_stats['stdev_frame_acquisition_us']:.3f} µs")
            logging.info(f"")
            
            logging.info(f"Inter-Frame Jitter (PTP clock stability):")
            expected_interval_ms = 16.67 if camera_mode == 0 else 33.33
            logging.info(f"   Mean interval: {ptp_stats['mean_frame_interval_ms']:.3f} ms (expected: ~{expected_interval_ms:.2f} ms)")
            logging.info(f"   Jitter: {ptp_stats['frame_jitter_pct']:.3f}%")
            logging.info(f"   Std Dev: {ptp_stats['stdev_frame_interval_ms']:.3f} ms")
            logging.info(f"   Frames outside tolerance: {ptp_stats['interval_fail_count']}")
            
            if ptp_stats['frame_jitter_pct'] > 10.0:
                logging.warning(f"   ⚠️  High jitter ({ptp_stats['frame_jitter_pct']:.2f}%) - check camera configuration")
            else:
                logging.info(f"   ✓ Frame timing is stable")
            
            logging.info(f"{'='*70}\n")
            return ptp_stats
        elif ptp_stats and "error" in ptp_stats:
            logging.warning(f"PTP timing stats unavailable: {ptp_stats['error']}")
            
            # return int(throughput), int(expected_throughput)
        
        return None
        
    except Exception as e:
        logging.warning(f"Hololink PTP measurement failed: {e}", exc_info=True)
        return None
    
    finally:
        stop_event.set()
        
        # CLEANUP SEQUENCE (must be in correct order):
        # 1. Stop hololink (closes socket, which stops frame reception)
        # 2. This allows GXF receiver to unblock
        # 3. GXF graph completes naturally (doesn't hang)
        # 4. Then destroy CUDA context
        #
        # DO NOT call camera.stop() - GXF + hololink.stop() handles camera shutdown
        # DO NOT try to interrupt app from here - it should already be done
        
        if hololink:
            try:
                logging.info("Stopping Hololink (closes frame socket)...")
                hololink.stop()
            except Exception as e:
                logging.error(f"Error stopping hololink: {e}", exc_info=True)
        
        # Now give app thread a chance to finish since socket is closed
        if app_thread and app_thread.is_alive():
            logging.info("Waiting for application thread to finish after hololink.stop()...")
            app_thread.join(timeout=5.0)
            if app_thread.is_alive():
                logging.error("Application thread still alive after 5s (receiver may be stuck)")
        
        # CRITICAL: Reset hololink framework to clear global device registry
        # This prevents cached/buffered frames from previous runs affecting the next run
        try:
            logging.info("Resetting Hololink framework (clears global device registry)...")
            hololink_module.Hololink.reset_framework()
        except Exception as e:
            logging.warning(f"Error resetting hololink framework: {e}")
        
        # Destroy CUDA context
        if cu_context:
            try:
                logging.info("Destroying CUDA context...")
                cuda.cuCtxDestroy(cu_context)
            except Exception as e:
                logging.error(f"Error destroying CUDA context: {e}", exc_info=True)

def argument_parser() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify IMX258 camera functionality")
    parser.add_argument("--camera-ip", type=str, default="192.168.0.2", help="Hololink device IP")
    parser.add_argument("--camera-mode", type=int, default=0, help="Camera mode (0=60fps, 1=30fps)")
    parser.add_argument("--frame-limit", type=int, default=300, help="Number of frames to capture")
    
    return parser.parse_args()

def main() -> Tuple[bool, str, dict]:
    """
    Verify that the Ethernet link speed meets minimum requirements.
    
    Args:
        min_mbps: Minimum expected link speed in Mbps
        
    Returns:
        Tuple of (success: bool, message: str, stats: dict)
    """
    args = argument_parser()
    cam_ip = args.camera_ip
    frame_lim = args.frame_limit
    cam_mode = args.camera_mode

 
    # Measure actual throughput (requires running hardware)
    result = _measure_hololink_ptp(camera_ip=cam_ip, frame_limit=frame_lim, timeout_seconds=15, camera_mode=cam_mode)
    if result is None:
        ptp_pass = False
        stats = {
            "camera_ip": cam_ip,
            "camera_mode": cam_mode,
            "frame_limit": frame_lim,
            "frames_captured": 0,
            "valid_frames": 0,
            "invalid_frames": 0,
            "mean_frame_acquisition_ms": 0,
            "min_frame_acquisition_ms": 0,
            "max_frame_acquisition_ms": 0,
            "p95_frame_acquisition_ms": 0,
            "p99_frame_acquisition_ms": 0,
            "stdev_frame_acquisition_us": 0,
            "mean_frame_interval_ms": 0,
            "stdev_frame_interval_ms": 0,
            "frame_jitter_pct": 0,
            "interval_fail_count": 0,
            "expected_interval_ms": 16.67 if cam_mode == 0 else 33.33,
            "test_duration_sec": 0,
        }
        print(f"📊 Metrics: {stats}")
        return ptp_pass, f"Hololink PTP measurement failed", stats
    else:
        # Extract metrics for validation
        mean_frame_acquisition = result['mean_frame_acquisition_ms']
        mean_frame_interval = result['mean_frame_interval_ms']
        jitter = result['frame_jitter_pct']
        interval_fail_count = result['interval_fail_count']
        
        # Pass criteria: frame acquisition time within tolerance
        ptp_pass = (mean_frame_acquisition >= 15.8*0.9) and (mean_frame_acquisition <= 15.8*1.1)  
                   #interval_fail_count <= frame_lim * 0.1)  # Max 10% failures
                   
        
        stats = {
            "camera_ip": cam_ip,
            "camera_mode": cam_mode,
            "frame_limit": frame_lim,
            "frames_captured": result['frames_captured'],  # Actual captured (requested + 10)
            "valid_frames": result['valid_frames'],
            "invalid_frames": result.get('invalid_frames', 0),
            # Frame acquisition time (sensor → FPGA)
            "mean_frame_acquisition_ms": result['mean_frame_acquisition_ms'],
            "min_frame_acquisition_ms": result['min_frame_acquisition_ms'],
            "max_frame_acquisition_ms": result['max_frame_acquisition_ms'],
            "p95_frame_acquisition_ms": result.get('p95_frame_acquisition_ms', 0),
            "p99_frame_acquisition_ms": result.get('p99_frame_acquisition_ms', 0),
            "stdev_frame_acquisition_us": result['stdev_frame_acquisition_us'],
            # Inter-frame jitter
            "mean_frame_interval_ms": result['mean_frame_interval_ms'],
            "stdev_frame_interval_ms": result['stdev_frame_interval_ms'],
            "frame_jitter_pct": result['frame_jitter_pct'],
            "interval_fail_count": result['interval_fail_count'],
            # Metadata
            "expected_interval_ms": result.get('expected_interval_ms', 16.67 if cam_mode == 0 else 33.33),
            "test_duration_sec": result.get('test_duration_sec', 0),
        }
        
        print(f"📊 Metrics: {stats}")
        
        if ptp_pass:
            return ptp_pass, f"Hololink PTP measurement passed (Frame acquisition={mean_frame_acquisition:.2f}ms, Mean interval={mean_frame_interval:.2f}ms, Expected: 15.8±10%ms acquisition)", stats
        else:
            return False, f"Hololink PTP measurement failed: Frame acquisition={mean_frame_acquisition:.3f}ms (Expected: 15.8±10%ms)", stats
    

if __name__ == "__main__":
    success, message, stats = main()
    if success:
        print(f"[PASS] {message}")
        sys.exit(0)
    else:
        print(f"[FAIL] {message}")
        sys.exit(1)