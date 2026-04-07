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


class FrameCounterOp(holoscan.core.Operator):
    """
    Terminal operator for comprehensive PTP timestamp analysis.
    
    Captures 3 timestamps per frame (NVIDIA-style):
    1. frame_start: FPGA first data byte (PTP domain)
    2. frame_end: FPGA last data byte + metadata (PTP domain)
    3. received: Host reception time (Unix epoch, for network latency)
    """
    
    def __init__(self, *args, frame_limit=50, requested_limit=None, app=None, 
                 pass_through=False, camera=None, hololink=None, 
                 save_images=False, camera_mode=0, **kwargs):
        self.pass_through = pass_through
        self.frame_limit = frame_limit  # Actual capture limit (requested + 10 for dropping)
        self.requested_limit = requested_limit or frame_limit  # What user requested (for reporting)
        self.frame_count = 0
        self.start_time = None
        self.camera_mode = camera_mode  # Store for mode-aware tolerance checking
        
        # Timestamp storage (3 timestamps per frame like NVIDIA script)
        self.frame_start_times = []      # T1: FPGA first data byte (PTP domain)
        self.frame_end_times = []        # T2: FPGA last data byte + metadata (PTP domain)
        self.received_timestamps = []    # T3: Host reception time (Unix epoch)
        
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
        # No output port - this is a terminal operator
        
    def compute(self, op_input, op_output, context):
        # Check BEFORE incrementing to prevent off-by-one errors
        if self.frame_count >= self.frame_limit:
            in_message = op_input.receive("input")
            return
        
        # CRITICAL: Capture host reception timestamp IMMEDIATELY after receiving message
        # This measures network latency (FPGA → Host)
        in_message = op_input.receive("input")
        received_time = time.time()  # Unix epoch timestamp (for network latency calculation)
        
        if self.start_time is None:
            self.start_time = time.time()
        
        self.frame_count += 1
        
        # Read PTP timestamps from FPGA - copy BOTH timestamps immediately to avoid race condition
        try:
            # Read both timestamps as close together as possible to minimize race window
            frame_start_s = get_timestamp(self.metadata, "timestamp")      # FPGA: first data byte
            frame_end_s = get_timestamp(self.metadata, "metadata")         # FPGA: last data byte + metadata
            timestamp_pair = (frame_start_s, frame_end_s)  # Store as tuple immediately
            
            # Validate timestamp domain: PTP timestamps are relative to device boot (< 10000 seconds)
            # Unix epoch timestamps are ~1.77 billion seconds (March 2026)
            MAX_PTP_TIMESTAMP = 10000  # 10000 seconds = ~2.7 hours since boot (generous)
            MAX_FRAME_ACQ_TIME = 0.1   # 100ms max for frame acquisition (catches race condition corruption)
            
            frame_start_s, frame_end_s = timestamp_pair  # Unpack from tuple
            
            # Validate: frame_end > frame_start (should be ~16.67ms apart for IMX274 at 60fps)
            is_valid_ptp_start = frame_start_s is not None and 0 < frame_start_s < MAX_PTP_TIMESTAMP
            is_valid_ptp_end = frame_end_s is not None and 0 < frame_end_s < MAX_PTP_TIMESTAMP
            is_valid_ordering = frame_end_s > frame_start_s if (is_valid_ptp_start and is_valid_ptp_end) else False
            is_valid_acq_time = (frame_end_s - frame_start_s) < MAX_FRAME_ACQ_TIME if is_valid_ordering else False
            
            if is_valid_ptp_start and is_valid_ptp_end and is_valid_ordering and is_valid_acq_time:
                # All timestamps valid - store them
                self.frame_start_times.append(frame_start_s)
                self.frame_end_times.append(frame_end_s)
                self.received_timestamps.append(received_time)
                
                if self.frame_count == 1:
                    logging.info(f"✓ PTP metadata available (frame_start={frame_start_s:.3f}s, frame_end={frame_end_s:.3f}s, received={received_time:.3f}s)")
            else:
                # Invalid timestamps - track failure reasons
                if not is_valid_ptp_start or not is_valid_ptp_end:
                    self.invalid_domain_count += 1
                    reason = "domain (Unix epoch)"
                elif not is_valid_ordering:
                    self.invalid_ordering_count += 1
                    reason = "ordering (end <= start)"
                elif not is_valid_acq_time:
                    self.invalid_ordering_count += 1
                    acq_time_ms = (frame_end_s - frame_start_s) * 1000
                    reason = f"acquisition time too large ({acq_time_ms:.1f}ms)"
                else:
                    reason = "unknown"
                
                if self.frame_count == 1:
                    logging.warning(f"⚠️  Invalid timestamp {reason}: frame_start={frame_start_s:.3f}s, frame_end={frame_end_s:.3f}s")
                elif self.frame_count % 50 == 0:
                    logging.warning(f"Frame {self.frame_count}: Invalid timestamp {reason}")
                
                # Store None for invalid frames
                self.frame_start_times.append(None)
                self.frame_end_times.append(None)
                self.received_timestamps.append(None)
                
        except Exception as e:
            logging.warning(f"Could not read PTP timestamps from metadata: {e}")
            self.missing_timestamp_count += 1
            self.frame_start_times.append(None)
            self.frame_end_times.append(None)
            self.received_timestamps.append(None)

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
        Comprehensive PTP timing analysis (NVIDIA-style).
        
        Analyzes:
        1. Frame acquisition time (sensor readout + FPGA processing)
        2. Inter-frame jitter (PTP clock stability)
        3. Network latency (FPGA → Host) - NEW
        
        Args:
            drop_frames: Number of frames to drop from start AND end for stability.
                        Default=5 matches NVIDIA script behavior.
        """
        import statistics
        
        # Filter out None values (frames where PTP metadata wasn't available)
        valid_indices = [i for i in range(len(self.frame_start_times)) 
                        if self.frame_start_times[i] is not None 
                        and self.frame_end_times[i] is not None
                        and self.received_timestamps[i] is not None]
        
        # Drop first/last N frames for stability (NVIDIA approach: settled_timestamps)
        if drop_frames > 0 and len(valid_indices) > drop_frames * 2:
            valid_indices = valid_indices[drop_frames:-drop_frames]
            logging.info(f"Dropped first/last {drop_frames} frames for stability (NVIDIA approach)")
        
        if len(valid_indices) < 2:
            return {"error": "Insufficient PTP timestamp data"}
        
        # === 1. Frame Acquisition Time (sensor readout + FPGA processing) ===
        frame_acquisition_times = []
        validated_indices = []
        
        for i in valid_indices:
            frame_start = self.frame_start_times[i]
            frame_end = self.frame_end_times[i]
            
            # Frame acquisition = time from sensor start to FPGA metadata ready
            frame_time_dt = frame_end - frame_start  # Expected: ~16.67ms for IMX274 (60fps all modes)
            
            # Sanity check: should be positive and < 100ms
            if frame_time_dt < 0 or frame_time_dt > 0.1:
                logging.warning(f"Unreasonable frame acquisition time in frame {i}: {frame_time_dt*1000:.2f}ms (skipping)")
                continue
            
            frame_acquisition_times.append(frame_time_dt)
            validated_indices.append(i)
        
        # Check if we have enough valid data after filtering
        if len(frame_acquisition_times) < 2:
            logging.error(f"Insufficient valid PTP data: only {len(frame_acquisition_times)} frames")
            return {"error": "Insufficient valid PTP timestamp data after filtering"}
        
        # === 2. Inter-Frame Jitter (PTP clock stability) ===
        valid_ptp_timestamps = [self.frame_end_times[i] for i in validated_indices]
        ptp_intervals = [valid_ptp_timestamps[i+1] - valid_ptp_timestamps[i] 
                        for i in range(len(valid_ptp_timestamps) - 1)]
        
        # IMX274: 60fps all modes (16.67ms interval)
        expected_interval_ms = 16.67  # All modes run at 60fps
        tolerance = 1.05  # 5% tolerance
        interval_fail_cnt = sum(1 for intv in ptp_intervals if intv*1000 >= expected_interval_ms * tolerance)
        
        # === 3. Network Latency (FPGA → Host) - NEW ===
        # Calculate time from FPGA metadata ready to host reception
        # NOTE: This requires converting PTP time to Unix epoch using boot_time offset
        # For simplicity, we use the FIRST frame to calculate boot_time offset
        first_valid_idx = validated_indices[0]
        boot_time_offset = self.received_timestamps[first_valid_idx] - self.frame_end_times[first_valid_idx]
        
        network_latencies = []
        for i in validated_indices:
            # Convert PTP timestamp to Unix epoch using boot_time offset
            fpga_time_unix = self.frame_end_times[i] + boot_time_offset
            host_received_time = self.received_timestamps[i]
            
            # Network latency = host received - FPGA metadata ready (in Unix epoch)
            latency = host_received_time - fpga_time_unix
            
            # Sanity check: latency should be positive and < 100ms for Linux UDP
            if latency < 0 or latency > 0.1:
                logging.warning(f"Unreasonable network latency in frame {i}: {latency*1000:.2f}ms (skipping)")
                continue
            
            network_latencies.append(latency)
        
        if len(network_latencies) < 2:
            logging.warning("Insufficient network latency data after filtering")
            network_latencies = [0.0]  # Fallback to avoid crash
        
        # Calculate percentile statistics for outlier analysis
        sorted_acq_times = sorted(frame_acquisition_times)
        sorted_latencies = sorted(network_latencies)
        p95_acq_idx = int(len(sorted_acq_times) * 0.95)
        p99_acq_idx = int(len(sorted_acq_times) * 0.99)
        p95_lat_idx = int(len(sorted_latencies) * 0.95)
        p99_lat_idx = int(len(sorted_latencies) * 0.99)
        
        # NVIDIA script validation thresholds:
        # - Linux UDP: average latency < 12ms
        # - RoCE: average latency < 4ms (not applicable for AGX Orin)
        avg_network_latency_ms = statistics.mean(network_latencies) * 1000
        max_network_latency_ms = max(network_latencies) * 1000
        
        # Validation: Linux UDP should have < 12ms average latency
        LINUX_MAX_AVG_LATENCY_MS = 12.0
        latency_pass = avg_network_latency_ms < LINUX_MAX_AVG_LATENCY_MS
        
        return {
            "frame_count": self.requested_limit,
            "frames_captured": self.frame_count,
            "valid_frames": len(validated_indices),
            "invalid_frames": self.frame_count - len(validated_indices),
            
            # Frame acquisition time (sensor readout + FPGA processing)
            # Expected: ~16.67ms for IMX274 (60fps all modes)
            "mean_frame_acquisition_ms": statistics.mean(frame_acquisition_times) * 1000,
            "min_frame_acquisition_ms": min(frame_acquisition_times) * 1000,
            "max_frame_acquisition_ms": max(frame_acquisition_times) * 1000,
            "p95_frame_acquisition_ms": sorted_acq_times[p95_acq_idx] * 1000,
            "p99_frame_acquisition_ms": sorted_acq_times[p99_acq_idx] * 1000,
            "stdev_frame_acquisition_us": statistics.stdev(frame_acquisition_times) * 1000000 if len(frame_acquisition_times) > 1 else 0,
            
            # Inter-frame jitter (PTP clock stability)
            "mean_frame_interval_ms": statistics.mean(ptp_intervals) * 1000,
            "stdev_frame_interval_ms": statistics.stdev(ptp_intervals) * 1000 if len(ptp_intervals) > 1 else 0,
            "frame_jitter_pct": (statistics.stdev(ptp_intervals) / statistics.mean(ptp_intervals) * 100) if statistics.mean(ptp_intervals) > 0 else 0,
            "interval_fail_count": interval_fail_cnt,
            
            # Network latency (FPGA → Host) - NEW
            "mean_network_latency_ms": avg_network_latency_ms,
            "min_network_latency_ms": min(network_latencies) * 1000,
            "max_network_latency_ms": max_network_latency_ms,
            "p95_network_latency_ms": sorted_latencies[p95_lat_idx] * 1000,
            "p99_network_latency_ms": sorted_latencies[p99_lat_idx] * 1000,
            "stdev_network_latency_us": statistics.stdev(network_latencies) * 1000000 if len(network_latencies) > 1 else 0,
            "network_latency_pass": latency_pass,
            "max_allowed_latency_ms": LINUX_MAX_AVG_LATENCY_MS,
            
            # Metadata for reporting
            "expected_interval_ms": expected_interval_ms,
            "camera_mode": self.camera_mode,
            "test_duration_sec": valid_ptp_timestamps[-1] - valid_ptp_timestamps[0] if len(valid_ptp_timestamps) > 1 else 0,
            "boot_time_offset": boot_time_offset,  # For debugging
        }


def _measure_hololink_ptp(camera_ip: str = "192.168.0.2", frame_limit: int = 300, 
                          timeout_seconds: int = 15, camera_mode: int = 0) -> Optional[dict]:
    """
    Comprehensive PTP timestamp measurement for IMX274 camera.
    
    Args:
        camera_ip: IP of Hololink device
        frame_limit: Number of frames to analyze (captures frame_limit + 10 for dropping)
        timeout_seconds: Maximum time to wait
        camera_mode: Camera mode (0-6, all run at 60fps)
        
    Returns:
        Dictionary with timing statistics, or None if measurement failed
    """
    
    hololink = None
    camera = None
    cu_context = None
    application = None
    app_thread = None
    stop_event = threading.Event()
    
    try:
        logging.info(f"Measuring PTP timestamps: {frame_limit} frames from {camera_ip}...")
        
        # Initialize CUDA
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
        
        # Find Hololink channel
        logging.info(f"Searching for Hololink device at {camera_ip}...")
        
        # Retry logic to handle "Interrupted system call" errors when tests run back-to-back
        max_retries = 3
        retry_delay = 0.5  # Start with 500ms
        channel_metadata = None
        
        for attempt in range(max_retries):
            try:
                channel_metadata = hololink_module.Enumerator.find_channel(channel_ip=camera_ip)
                if channel_metadata:
                    break
                logging.warning(f"Device not found at {camera_ip}, attempt {attempt + 1}/{max_retries}")
            except RuntimeError as e:
                if "Interrupted system call" in str(e) and attempt < max_retries - 1:
                    logging.warning(f"Interrupted system call on attempt {attempt + 1}/{max_retries}, retrying after {retry_delay}s delay...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    raise
        
        if not channel_metadata:
            logging.warning(f"Failed to find Hololink device at {camera_ip} after {max_retries} attempts")
            return None
        
        logging.info("Hololink device found")
        
        # Initialize camera (IMX274-specific)
        hololink_channel = hololink_module.DataChannel(channel_metadata)
        camera = hololink_module.sensors.imx274.dual_imx274.Imx274Cam(hololink_channel, expander_configuration=0)
        camera_mode_enum = hololink_module.sensors.imx274.imx274_mode.Imx274_Mode(camera_mode)
        
        # Minimal application for PTP measurement
        class PTSApplication(holoscan.core.Application):
            """Minimal app for PTP timestamp measurement."""
            
            def __init__(self, cuda_ctx, cuda_dev_ord, hl_chan, cam, capture_limit, 
                        requested_limit, camera_mode=0):
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
                # Use CountCondition to limit frames
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
                
                # Frame counter as terminal operator
                self._frame_counter = FrameCounterOp(
                    self,
                    name="frame_counter",
                    frame_limit=self._capture_limit,
                    requested_limit=self._requested_limit,
                    pass_through=False,
                    camera_mode=self._camera_mode
                )
                
                # Pipeline: receiver → frame_counter (terminal)
                self.add_flow(receiver_operator, self._frame_counter, {("output", "input")})
            
            def get_frame_count(self) -> int:
                return self._frame_counter.frame_count if self._frame_counter else 0
        
        # Create application
        # Add 10 frames to capture limit (for dropping first/last 5) but report requested count
        FRAMES_TO_DROP = 10  # Drop 5 from start + 5 from end
        capture_limit = frame_limit + FRAMES_TO_DROP
        logging.info(f"Capturing {capture_limit} frames (analyzing {frame_limit} after dropping first/last 5)...")
        
        application = PTSApplication(
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

        # Configure camera AFTER PTP is ready (IMX274-specific sequence)
        logging.info("Configuring camera...")
        camera.setup_clock()
        camera.configure(camera_mode_enum)
        camera.set_digital_gain_reg(0x4)  # Set digital gain
        
        start_time = time.time()
        
        # Run application in thread
        def run_app():
            try:
                application.run()  # Will complete when CountCondition reaches frame_limit
            except Exception as e:
                logging.warning(f"Application exception: {e}")
        
        app_thread = threading.Thread(target=run_app, daemon=True)
        app_thread.start()
        
        # Monitor for completion
        poll_interval = 0.1
        first_frame_time = None
        last_frame_time = None
        max_wait_time = timeout_seconds + 30  # Extra time for setup + capture
        start_wait = time.time()
        
        while app_thread.is_alive():
            time.sleep(poll_interval)
            
            frames = application.get_frame_count()
            
            # Track when first frame arrives
            if frames > 0 and first_frame_time is None:
                first_frame_time = time.time()
                logging.info(f"First frame received after {time.time() - start_time:.2f}s")
            
            # Track last frame time
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
        
        # Wait for thread to join
        if app_thread.is_alive():
            logging.info("Waiting for application thread to finish...")
            app_thread.join(timeout=3.0)
            if app_thread.is_alive():
                logging.warning("Application thread still alive after 3s timeout")
        
        stop_event.set()
        
        # Report PTP timing analysis
        ptp_stats = application._frame_counter.get_ptp_timing_stats()
        if ptp_stats and "error" not in ptp_stats:
            logging.info(f"\n{'='*80}")
            logging.info(f"PTP Timestamp Analysis (IMX274, Linux UDP)")
            logging.info(f"{'='*80}")
            logging.info(f"Frames captured: {ptp_stats['frames_captured']} (requested: {ptp_stats['frame_count']}, +10 for dropping)")
            logging.info(f"Frames analyzed: {ptp_stats['valid_frames']}/{ptp_stats['frame_count']} (after dropping & filtering)")
            
            # Show breakdown of invalid frames
            frame_counter = application._frame_counter
            total_invalid = frame_counter.invalid_domain_count + frame_counter.invalid_ordering_count + frame_counter.missing_timestamp_count
            if total_invalid > 0:
                logging.info(f"\nInvalid frames breakdown:")
                logging.info(f"   Domain violations (Unix epoch): {frame_counter.invalid_domain_count}")
                logging.info(f"   Ordering violations (end <= start): {frame_counter.invalid_ordering_count}")
                logging.info(f"   Missing timestamps: {frame_counter.missing_timestamp_count}")
            
            logging.info(f"\n1. Frame Acquisition Time (sensor readout + FPGA processing):")
            logging.info(f"   Mean: {ptp_stats['mean_frame_acquisition_ms']:.3f} ms")
            logging.info(f"   Expected: ~16.67ms (60fps all modes)")
            logging.info(f"   Min/P95/P99/Max: {ptp_stats['min_frame_acquisition_ms']:.3f} / {ptp_stats['p95_frame_acquisition_ms']:.3f} / {ptp_stats['p99_frame_acquisition_ms']:.3f} / {ptp_stats['max_frame_acquisition_ms']:.3f} ms")
            logging.info(f"   Std Dev: {ptp_stats['stdev_frame_acquisition_us']:.1f} µs")
            
            logging.info(f"\n2. Inter-Frame Jitter (PTP clock stability):")
            logging.info(f"   Mean interval: {ptp_stats['mean_frame_interval_ms']:.3f} ms (expected: ~16.67 ms)")
            logging.info(f"   Jitter: {ptp_stats['frame_jitter_pct']:.3f}%")
            logging.info(f"   Std Dev: {ptp_stats['stdev_frame_interval_ms']:.3f} ms")
            logging.info(f"   Frames outside tolerance: {ptp_stats['interval_fail_count']}")
            
            if ptp_stats['frame_jitter_pct'] > 10.0:
                logging.warning(f"   ⚠️  High jitter ({ptp_stats['frame_jitter_pct']:.2f}%) - check camera configuration")
            else:
                logging.info(f"   ✓ Frame timing is stable")
            
            # NEW: Network latency analysis
            logging.info(f"\n3. Network Latency (FPGA → Host, Linux UDP):")
            logging.info(f"   Mean: {ptp_stats['mean_network_latency_ms']:.3f} ms")
            logging.info(f"   Min/P95/P99/Max: {ptp_stats['min_network_latency_ms']:.3f} / {ptp_stats['p95_network_latency_ms']:.3f} / {ptp_stats['p99_network_latency_ms']:.3f} / {ptp_stats['max_network_latency_ms']:.3f} ms")
            logging.info(f"   Std Dev: {ptp_stats['stdev_network_latency_us']:.1f} µs")
            logging.info(f"   Max allowed (Linux UDP): < {ptp_stats['max_allowed_latency_ms']:.1f} ms")
            
            if ptp_stats['network_latency_pass']:
                logging.info(f"   ✓ Network latency is within specification")
            else:
                logging.warning(f"   ⚠️  Network latency exceeds {ptp_stats['max_allowed_latency_ms']:.1f}ms threshold")
            
            logging.info(f"\n{'='*80}\n")
            return ptp_stats
        elif ptp_stats and "error" in ptp_stats:
            logging.warning(f"PTP timing stats unavailable: {ptp_stats['error']}")
            return None
        
        return None
        
    except Exception as e:
        logging.warning(f"PTP measurement failed: {e}", exc_info=True)
        return None
    
    finally:
        stop_event.set()
        
        # Cleanup sequence (correct order)
        if hololink:
            try:
                logging.info("Stopping Hololink...")
                hololink.stop()
            except Exception as e:
                logging.error(f"Error stopping hololink: {e}")
        
        if app_thread and app_thread.is_alive():
            logging.info("Waiting for application thread to finish...")
            app_thread.join(timeout=5.0)
            if app_thread.is_alive():
                logging.error("Application thread still alive after 5s")
        
        # Reset Hololink framework
        try:
            logging.info("Resetting Hololink framework...")
            hololink_module.Hololink.reset_framework()
        except Exception as e:
            logging.warning(f"Error resetting hololink framework: {e}")
        
        # Destroy CUDA context
        if cu_context:
            try:
                logging.info("Destroying CUDA context...")
                cuda.cuCtxDestroy(cu_context)
            except Exception as e:
                logging.error(f"Error destroying CUDA context: {e}")


def argument_parser() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify IMX274 PTP timestamp accuracy")
    parser.add_argument("--camera-ip", type=str, default="192.168.0.2", help="Hololink device IP")
    parser.add_argument("--camera-mode", type=int, default=0, help="Camera mode (0-6, all run at 60fps)")
    parser.add_argument("--frame-limit", type=int, default=300, help="Number of frames to analyze")
    
    return parser.parse_args()


def main() -> Tuple[bool, str, dict]:
    """
    Verify PTP timestamp accuracy for IMX274 camera (Linux UDP only).
    
    Returns:
        Tuple of (success: bool, message: str, stats: dict)
    """
    args = argument_parser()
    cam_ip = args.camera_ip
    frame_lim = args.frame_limit
    cam_mode = args.camera_mode

    # Measure PTP timestamps
    result = _measure_hololink_ptp(camera_ip=cam_ip, frame_limit=frame_lim, 
                                    timeout_seconds=15, camera_mode=cam_mode)
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
            "mean_network_latency_ms": 0,
            "min_network_latency_ms": 0,
            "max_network_latency_ms": 0,
            "p95_network_latency_ms": 0,
            "p99_network_latency_ms": 0,
            "stdev_network_latency_us": 0,
            "network_latency_pass": False,
            "expected_interval_ms": 16.67,  # 60fps all modes
            "test_duration_sec": 0,
        }
        print(f"📊 Metrics: {stats}")
        return ptp_pass, "PTP measurement failed", stats
    else:
        # Extract metrics for validation
        mean_frame_acquisition = result['mean_frame_acquisition_ms']
        mean_network_latency = result['mean_network_latency_ms']
        interval_fail_count = result['interval_fail_count']
        network_latency_pass = result['network_latency_pass']
        
        # Pass criteria (NVIDIA-style):
        # 1. Frame acquisition time within ±10% of expected (16.67ms for IMX274 @ 60fps)
        # 2. Network latency < 12ms (Linux UDP threshold)
        # 3. Inter-frame jitter acceptable (< 10% of frames outside tolerance)
        ptp_pass = (
            (16.67 * 0.9 <= mean_frame_acquisition <= 16.67 * 1.1) and  # Frame acq time OK
            network_latency_pass and  # Network latency < 12ms
            (interval_fail_count <= frame_lim * 0.1)  # Max 10% jitter failures
        )
        
        stats = {
            "camera_ip": cam_ip,
            "camera_mode": cam_mode,
            "frame_limit": frame_lim,
            "frames_captured": result['frames_captured'],
            "valid_frames": result['valid_frames'],
            "invalid_frames": result.get('invalid_frames', 0),
            
            # Frame acquisition time
            "mean_frame_acquisition_ms": result['mean_frame_acquisition_ms'],
            "min_frame_acquisition_ms": result['min_frame_acquisition_ms'],
            "max_frame_acquisition_ms": result['max_frame_acquisition_ms'],
            "p95_frame_acquisition_ms": result['p95_frame_acquisition_ms'],
            "p99_frame_acquisition_ms": result['p99_frame_acquisition_ms'],
            "stdev_frame_acquisition_us": result['stdev_frame_acquisition_us'],
            
            # Inter-frame jitter
            "mean_frame_interval_ms": result['mean_frame_interval_ms'],
            "stdev_frame_interval_ms": result['stdev_frame_interval_ms'],
            "frame_jitter_pct": result['frame_jitter_pct'],
            "interval_fail_count": result['interval_fail_count'],
            
            # Network latency (NEW)
            "mean_network_latency_ms": result['mean_network_latency_ms'],
            "min_network_latency_ms": result['min_network_latency_ms'],
            "max_network_latency_ms": result['max_network_latency_ms'],
            "p95_network_latency_ms": result['p95_network_latency_ms'],
            "p99_network_latency_ms": result['p99_network_latency_ms'],
            "stdev_network_latency_us": result['stdev_network_latency_us'],
            "network_latency_pass": result['network_latency_pass'],
            
            # Metadata
            "expected_interval_ms": result['expected_interval_ms'],
            "test_duration_sec": result.get('test_duration_sec', 0),
        }
        
        print(f"📊 Metrics: {stats}")
        
        if ptp_pass:
            return True, (f"PTP validation passed (Frame acq={mean_frame_acquisition:.2f}ms, "
                         f"Network latency={mean_network_latency:.2f}ms)"), stats
        else:
            failure_reasons = []
            if not (16.67 * 0.9 <= mean_frame_acquisition <= 16.67 * 1.1):
                failure_reasons.append(f"Frame acquisition={mean_frame_acquisition:.2f}ms (expected 16.67±10%)")
            if not network_latency_pass:
                failure_reasons.append(f"Network latency={mean_network_latency:.2f}ms (max 12ms)")
            if interval_fail_count > frame_lim * 0.1:
                failure_reasons.append(f"Jitter failures={interval_fail_count} (max {int(frame_lim*0.1)})")
            
            return False, f"PTP validation failed: {'; '.join(failure_reasons)}", stats


if __name__ == "__main__":
    success, message, stats = main()
    if success:
        print(f"[PASS] {message}")
        sys.exit(0)
    else:
        print(f"[FAIL] {message}")
        sys.exit(1)
