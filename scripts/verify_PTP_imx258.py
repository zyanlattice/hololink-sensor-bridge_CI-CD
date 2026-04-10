import ctypes
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
import cupy as cp
import holoscan
import hololink as hololink_module
import datetime
import math

# Timestamp constants 
MS_PER_SEC = 1000.0
US_PER_SEC = 1000.0 * MS_PER_SEC
NS_PER_SEC = 1000.0 * US_PER_SEC
SEC_PER_NS = 1.0 / NS_PER_SEC


def get_timestamp(metadata, name):
    """Extract PTP timestamp from metadata (seconds + nanoseconds)."""
    s = metadata[f"{name}_s"]
    f = metadata[f"{name}_ns"]
    f *= SEC_PER_NS
    return s + f


def save_timestamp(metadata: dict, name: str, timestamp: datetime.datetime) -> None:
    """Store datetime as seconds + nanoseconds in metadata."""
    f, s = math.modf(timestamp.timestamp())
    metadata[f"{name}_s"] = int(s)
    metadata[f"{name}_ns"] = int(f * NS_PER_SEC)

class InstrumentedTimeProfiler(holoscan.core.Operator):
    def __init__(
        self,
        *args,
        recorder_queue=None,
        operator_name="operator",
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._recorder_queue = recorder_queue
        self._operator_name = operator_name

    def setup(self, spec):
        logging.info("InstrumentedTimeProfiler setup")
        spec.input("input")
        spec.output("output")

    def compute(self, op_input, op_output, context):
        # What time is it now?
        operator_timestamp = datetime.datetime.now(datetime.UTC)

        in_message = op_input.receive("input")
        cp_frame = cp.asarray(in_message.get(""))
        #
        save_timestamp(
            self.metadata, self._operator_name + "_timestamp", operator_timestamp
        )
        op_output.emit({"": cp_frame}, "output")

class MonitorOperator(holoscan.core.Operator):
    def __init__(
        self,
        *args,
        recorder_queue=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._recorder_queue = recorder_queue

    def setup(self, spec):
        logging.info("MonitorOperator setup")
        spec.input("input")
        spec.output("output")  # Pass through to FrameCounterOp

    def compute(self, op_input, op_output, context):
        # What time is it now?
        complete_timestamp = datetime.datetime.now(datetime.UTC)

        in_message = op_input.receive("input")
        # Save complete_timestamp to metadata
        save_timestamp(self.metadata, "complete_timestamp", complete_timestamp)
        # Pass through to next operator (FrameCounterOp)
        op_output.emit(in_message, "output")

class FrameCounterOp(holoscan.core.Operator):
    """
    Terminal operator for comprehensive PTP timestamp analysis.
    
    Reads 5 timestamps per frame from metadata (NVIDIA-style):
    1. frame_start: FPGA first data byte (PTP domain) - from receiver
    2. frame_end: FPGA last data byte + metadata (PTP domain) - from receiver
    3. received: Host reception time (Unix epoch) - from receiver
    4. operator_timestamp: After receiver processing - from InstrumentedTimeProfiler
    5. complete_timestamp: After ISP/visualization processing - from MonitorOperator
    
    Consolidates all timing metrics like the latency script's main() function.
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
        
        # Timestamp storage (5 timestamps per frame - NVIDIA latency script approach)
        self.frame_start_times = []      # T1: FPGA first data byte (PTP domain)
        self.frame_end_times = []        # T2: FPGA last data byte + metadata (PTP domain)
        self.received_timestamps = []    # T3: Host reception time (Unix epoch)
        self.operator_timestamps = []    # T4: After receiver operator processing (Unix epoch)
        self.complete_timestamps = []    # T5: After ISP/visualization complete (Unix epoch)
        
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
        
        # Receive frame with all metadata from previous operators
        in_message = op_input.receive("input")
        
        if self.start_time is None:
            self.start_time = time.time()
        
        self.frame_count += 1
        
        # Read all timestamps from metadata (saved by various operators in the pipeline)
        try:
            frame_start_s = get_timestamp(self.metadata, "timestamp")      # FPGA: first data byte (from receiver)
            frame_end_s = get_timestamp(self.metadata, "metadata")         # FPGA: last data byte + metadata (from receiver)
            received_s = get_timestamp(self.metadata, "received")          # Host reception time (from receiver)
            operator_s = get_timestamp(self.metadata, "operator_timestamp")  # Saved by InstrumentedTimeProfiler
            complete_s = get_timestamp(self.metadata, "complete_timestamp")  # Saved by MonitorOperator
            
            # Store timestamps directly (no validation like latency script)
            self.frame_start_times.append(frame_start_s)
            self.frame_end_times.append(frame_end_s)
            self.received_timestamps.append(received_s)
            self.operator_timestamps.append(operator_s)
            self.complete_timestamps.append(complete_s)
            
            if self.frame_count == 1:
                logging.info(f"✓ All timestamps available:")
                logging.info(f"  frame_start={frame_start_s:.3f}s, frame_end={frame_end_s:.3f}s")
                logging.info(f"  received={received_s:.3f}s, operator={operator_s:.3f}s, complete={complete_s:.3f}s")
                
        except Exception as e:
            logging.warning(f"Could not read timestamps from metadata: {e}")
            self.missing_timestamp_count += 1
            self.frame_start_times.append(None)
            self.frame_end_times.append(None)
            self.received_timestamps.append(None)
            self.operator_timestamps.append(None)
            self.complete_timestamps.append(None)

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
        
        Analyzes (with full pipeline):
        1. Frame Latency (sensor readout + FPGA processing)
        2. CPU Wake Up Time (background thread wake latency)
        3. LinuxReceiverOp Latency (receiver operator processing)
        4. ISP + Visualizer Op Latency (image processing pipeline)
        5. GPU Host Latency (total CPU/GPU processing)
        6. Total Latency (frame start to processing complete)
        7. Inter-frame Jitter (PTP clock stability)
        
        Args:
            drop_frames: Number of frames to drop from start AND end for stability.
                        Default=5 matches NVIDIA script behavior.
        """
        import statistics
        
        # Filter out None values (frames where metadata wasn't available)
        all_valid_indices = [i for i in range(len(self.frame_start_times)) 
                            if self.frame_start_times[i] is not None 
                            and self.frame_end_times[i] is not None
                            and self.received_timestamps[i] is not None
                            and self.operator_timestamps[i] is not None
                            and self.complete_timestamps[i] is not None]
        
        # Count invalid frames (missing metadata)
        frames_with_missing_metadata = self.frame_count - len(all_valid_indices)
        
        # Drop first/last N frames for stability (NVIDIA approach: settled_timestamps)
        valid_indices = all_valid_indices
        frames_dropped_for_stability = 0
        if drop_frames > 0 and len(all_valid_indices) > drop_frames * 2:
            valid_indices = all_valid_indices[drop_frames:-drop_frames]
            frames_dropped_for_stability = drop_frames * 2
            logging.info(f"Dropped first/last {drop_frames} frames for stability (NVIDIA approach)")
        
        if len(valid_indices) < 2:
            return {"error": "Insufficient PTP timestamp data"}
        
        # === 1. Frame Latency (sensor readout + FPGA processing) ===
        frame_latencies = [
            self.frame_end_times[i] - self.frame_start_times[i]
            for i in valid_indices
        ]
        
        # === 2. CPU Wake Up Time (time for background thread to wake up) ===
        cpu_wakeup_times = [
            self.received_timestamps[i] - self.frame_end_times[i]
            for i in valid_indices
        ]
        
        # === 3. LinuxReceiverOp Latency (receiver operator processing) ===
        receiver_latencies = [
            self.operator_timestamps[i] - self.received_timestamps[i]
            for i in valid_indices
        ]
        
        # === 4. ISP + Visualizer Op Latency (processing pipeline) ===
        isp_viz_latencies = [
            self.complete_timestamps[i] - self.operator_timestamps[i]
            for i in valid_indices
        ]
        
        # === 5. GPU Host Latency (total CPU/GPU processing) ===
        gpu_host_latencies = [
            cpu_wakeup_times[i] + receiver_latencies[i] + isp_viz_latencies[i]
            for i in range(len(valid_indices))
        ]
        
        # === 6. Total Latency Per Frame ===
        total_latencies = [
            frame_latencies[i] + gpu_host_latencies[i]
            for i in range(len(valid_indices))
        ]
        
        # === 7. Inter-Frame Jitter (PTP clock stability) ===
        valid_ptp_timestamps = [self.frame_end_times[i] for i in valid_indices]
        ptp_intervals = [
            valid_ptp_timestamps[i+1] - valid_ptp_timestamps[i] 
            for i in range(len(valid_ptp_timestamps) - 1)
        ]
        
        # Mode-aware tolerance: 60fps (mode 0) = 16.67ms, 30fps (mode 1) = 33.33ms
        expected_interval_ms = 16.67 if self.camera_mode == 0 else 33.33
        tolerance = 1.05  # 5% tolerance
        interval_fail_cnt = sum(1 for intv in ptp_intervals if intv*1000 >= expected_interval_ms * tolerance)
        
        # Calculate percentile statistics for outlier analysis
        sorted_frame_lat = sorted(frame_latencies)
        sorted_cpu_wake = sorted(cpu_wakeup_times)
        sorted_receiver = sorted(receiver_latencies)
        sorted_isp_viz = sorted(isp_viz_latencies)
        sorted_gpu_host = sorted(gpu_host_latencies)
        sorted_total = sorted(total_latencies)
        
        p95_idx = int(len(valid_indices) * 0.95)
        p99_idx = int(len(valid_indices) * 0.99)
        
        return {
            "frame_count": self.requested_limit,
            "frames_captured": self.frame_count,
            "frames_dropped_for_stability": frames_dropped_for_stability,
            "frames_with_missing_metadata": frames_with_missing_metadata,
            "frames_analyzed": len(valid_indices),
            
            # Frame Latency (sensor readout + FPGA processing)
            "mean_frame_latency_ms": statistics.mean(frame_latencies) * 1000,
            "min_frame_latency_ms": min(frame_latencies) * 1000,
            "max_frame_latency_ms": max(frame_latencies) * 1000,
            "p95_frame_latency_ms": sorted_frame_lat[p95_idx] * 1000,
            "p99_frame_latency_ms": sorted_frame_lat[p99_idx] * 1000,
            "stdev_frame_latency_us": statistics.stdev(frame_latencies) * 1000000 if len(frame_latencies) > 1 else 0,
            
            # CPU Wake Up Time
            "mean_cpu_wakeup_ms": statistics.mean(cpu_wakeup_times) * 1000,
            "min_cpu_wakeup_ms": min(cpu_wakeup_times) * 1000,
            "max_cpu_wakeup_ms": max(cpu_wakeup_times) * 1000,
            "p95_cpu_wakeup_ms": sorted_cpu_wake[p95_idx] * 1000,
            "p99_cpu_wakeup_ms": sorted_cpu_wake[p99_idx] * 1000,
            
            # LinuxReceiverOp Latency
            "mean_receiver_latency_ms": statistics.mean(receiver_latencies) * 1000,
            "min_receiver_latency_ms": min(receiver_latencies) * 1000,
            "max_receiver_latency_ms": max(receiver_latencies) * 1000,
            "p95_receiver_latency_ms": sorted_receiver[p95_idx] * 1000,
            "p99_receiver_latency_ms": sorted_receiver[p99_idx] * 1000,
            
            # ISP + Visualizer Op Latency
            "mean_isp_viz_latency_ms": statistics.mean(isp_viz_latencies) * 1000,
            "min_isp_viz_latency_ms": min(isp_viz_latencies) * 1000,
            "max_isp_viz_latency_ms": max(isp_viz_latencies) * 1000,
            "p95_isp_viz_latency_ms": sorted_isp_viz[p95_idx] * 1000,
            "p99_isp_viz_latency_ms": sorted_isp_viz[p99_idx] * 1000,
            
            # GPU Host Latency (total CPU/GPU processing)
            "mean_gpu_host_latency_ms": statistics.mean(gpu_host_latencies) * 1000,
            "min_gpu_host_latency_ms": min(gpu_host_latencies) * 1000,
            "max_gpu_host_latency_ms": max(gpu_host_latencies) * 1000,
            "p95_gpu_host_latency_ms": sorted_gpu_host[p95_idx] * 1000,
            "p99_gpu_host_latency_ms": sorted_gpu_host[p99_idx] * 1000,
            
            # Total Latency Per Frame
            "mean_total_latency_ms": statistics.mean(total_latencies) * 1000,
            "min_total_latency_ms": min(total_latencies) * 1000,
            "max_total_latency_ms": max(total_latencies) * 1000,
            "p95_total_latency_ms": sorted_total[p95_idx] * 1000,
            "p99_total_latency_ms": sorted_total[p99_idx] * 1000,
            
            # Inter-frame jitter (PTP clock stability)
            "mean_frame_interval_ms": statistics.mean(ptp_intervals) * 1000,
            "stdev_frame_interval_ms": statistics.stdev(ptp_intervals) * 1000 if len(ptp_intervals) > 1 else 0,
            "frame_jitter_pct": (statistics.stdev(ptp_intervals) / statistics.mean(ptp_intervals) * 100) if statistics.mean(ptp_intervals) > 0 else 0,
            "interval_fail_count": interval_fail_cnt,
            
            # Metadata for reporting
            "expected_interval_ms": expected_interval_ms,
            "camera_mode": self.camera_mode,
            "test_duration_sec": valid_ptp_timestamps[-1] - valid_ptp_timestamps[0] if len(valid_ptp_timestamps) > 1 else 0,
        }


def _measure_hololink_ptp(camera_ip: str = "192.168.0.2", frame_limit: int = 300, 
                          timeout_seconds: int = 15, camera_mode: int = 0) -> Optional[dict]:
    """
    Comprehensive PTP timestamp measurement for IMX258 camera.
    
    Args:
        camera_ip: IP of Hololink device
        frame_limit: Number of frames to analyze (captures frame_limit + 10 for dropping)
        timeout_seconds: Maximum time to wait
        camera_mode: Camera mode (0=60fps, 1=30fps)
        
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
        channel_metadata = hololink_module.Enumerator.find_channel(channel_ip=camera_ip)
        if not channel_metadata:
            logging.warning(f"Failed to find Hololink device at {camera_ip}")
            return None
        
        logging.info("Hololink device found")
        
        # Initialize camera
        hololink_channel = hololink_module.DataChannel(channel_metadata)
        camera = hololink_module.sensors.imx258.Imx258(hololink_channel, camera_id=0)
        
        # Minimal application for PTP measurement
        class PTSApplication(holoscan.core.Application):
            """Minimal app for PTP timestamp measurement."""
            
            def __init__(self, cuda_ctx, cuda_dev_ord, hl_chan, cam, capture_limit, 
                        requested_limit, camera_mode=0, headless=False, fullscreen=True):
                super().__init__()
                self._cuda_context = cuda_ctx
                self._cuda_device_ordinal = cuda_dev_ord
                self._hololink_channel = hl_chan
                self._camera = cam
                self._capture_limit = capture_limit  # Actual frames to capture (requested + 10)
                self._requested_limit = requested_limit  # What user requested (for reporting)
                self._camera_mode = camera_mode
                self._headless = headless
                self._fullscreen = fullscreen
                self._recorder_queue = []  # Not used but needed for operator compatibility
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
                
                csi_to_bayer_pool = holoscan.resources.BlockMemoryPool(
                    self,
                    name="pool",
                    # storage_type of 1 is device memory
                    storage_type=1,
                    block_size=self._camera._width
                    * ctypes.sizeof(ctypes.c_uint16)
                    * self._camera._height,
                    num_blocks=2,
                )
                csi_to_bayer_operator = hololink_module.operators.CsiToBayerOp(
                    self,
                    name="csi_to_bayer",
                    allocator=csi_to_bayer_pool,
                    cuda_device_ordinal=self._cuda_device_ordinal,
                )
                self._camera.configure_converter(csi_to_bayer_operator)

                frame_context = self._cuda_context
                receiver_operator = hololink_module.operators.LinuxReceiverOperator(
                    self,
                    count_condition,
                    name="receiver",
                    frame_size=self._camera._width * self._camera._height * 2,
                    frame_context=frame_context,
                    hololink_channel=self._hololink_channel,
                    device=self._camera,
                )

                pixel_format = self._camera.pixel_format()
                bayer_format = self._camera.bayer_format()
                image_processor_operator = hololink_module.operators.ImageProcessorOp(
                    self,
                    name="image_processor",
                    optical_black=50,
                    bayer_format=bayer_format.value,
                    pixel_format=pixel_format.value,
                )

                rgba_components_per_pixel = 4
                bayer_pool = holoscan.resources.BlockMemoryPool(
                    self,
                    name="pool",
                    # storage_type of 1 is device memory
                    storage_type=1,
                    block_size=self._camera._width
                    * rgba_components_per_pixel
                    * ctypes.sizeof(ctypes.c_uint16)
                    * self._camera._height,
                    num_blocks=2,
                )
                demosaic = holoscan.operators.BayerDemosaicOp(
                    self,
                    name="demosaic",
                    pool=bayer_pool,
                    generate_alpha=True,
                    alpha_value=65535,
                    bayer_grid_pos=bayer_format.value,
                    interpolation_mode=0,
                )

                visualizer = holoscan.operators.HolovizOp(
                    self,
                    name="holoviz",
                    fullscreen=self._fullscreen,
                    headless=self._headless,
                    framebuffer_srgb=True,
                    enable_camera_pose_output=True,
                    camera_pose_output_type="extrinsics_model",
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
                
                profiler = InstrumentedTimeProfiler(
                    self,
                    name="profiler",
                    recorder_queue=self._recorder_queue,
                )


                monitor = MonitorOperator(
                    self,
                    name="monitor",
                    recorder_queue=self._recorder_queue,
                )
                # Pipeline: receiver → frame_counter (terminal)
                self.add_flow(receiver_operator, profiler, {("output", "input")})
                self.add_flow(profiler, csi_to_bayer_operator, {("output", "input")})
                self.add_flow(csi_to_bayer_operator, image_processor_operator, {("output", "input")})
                self.add_flow(image_processor_operator, demosaic, {("output", "receiver")})
                self.add_flow(demosaic, visualizer, {("transmitter", "receivers")})
                self.add_flow(visualizer, monitor, {("camera_pose_output", "input")})
                self.add_flow(monitor, self._frame_counter, {("output", "input")})
            
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
        hololink.reset()  # Ensure clean state
        
        # STEP 1: Configure MIPI lanes FIRST (required before PTP sync)
        logging.info("Configuring MIPI lanes...")
        camera.configure_mipi_lane(4, 371)
        
        # STEP 2: CRITICAL - Synchronize PTP clock AFTER MIPI config
        logging.info("Synchronizing PTP clock...")
        if not hololink.ptp_synchronize():
            logging.error("Failed to synchronize PTP - timestamps will be invalid")
            return None
        logging.info("PTP synchronized successfully")

        # STEP 3: Configure camera mode AFTER PTP sync
        logging.info("Configuring camera mode...")
        camera.configure(camera_mode)
        camera.set_focus(-140)
        camera.set_exposure(0x0600)
        camera.set_analog_gain(0x0180)
        camera.start()
        
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
        if application._frame_counter is None:
            logging.error("Frame counter was not initialized - application may have failed to compose")
            return None
            
        ptp_stats = application._frame_counter.get_ptp_timing_stats()
        if ptp_stats and "error" not in ptp_stats:
            logging.info(f"\n{'='*80}")
            logging.info(f"PTP Timestamp Analysis (IMX258, Linux UDP)\n{'='*80}")
            logging.info(f"Frames requested: {ptp_stats['frame_count']}")
            logging.info(f"Frames captured: {ptp_stats['frames_captured']} (includes +10 buffer for stabilization)")
            logging.info(f"Frames dropped for stability: {ptp_stats['frames_dropped_for_stability']} (first/last 5)")
            if ptp_stats['frames_with_missing_metadata'] > 0:
                logging.info(f"Frames with missing metadata: {ptp_stats['frames_with_missing_metadata']}")
            logging.info(f"Frames analyzed: {ptp_stats['frames_analyzed']}")
            
            # Show breakdown of invalid frames
            frame_counter = application._frame_counter
            total_invalid = frame_counter.invalid_domain_count + frame_counter.invalid_ordering_count + frame_counter.missing_timestamp_count
            if total_invalid > 0:
                logging.info(f"\nInvalid frames breakdown:")
                logging.info(f"   Domain violations (Unix epoch): {frame_counter.invalid_domain_count}")
                logging.info(f"   Ordering violations (end <= start): {frame_counter.invalid_ordering_count}")
                logging.info(f"   Missing timestamps: {frame_counter.missing_timestamp_count}")
            
            # Print detailed statistics
            logging.info(f"\n1. Frame Latency (sensor readout + FPGA processing):")
            logging.info(f"   Mean: {ptp_stats['mean_frame_latency_ms']:.3f} ms")
            logging.info(f"   Min/P95/P99/Max: {ptp_stats['min_frame_latency_ms']:.3f} / {ptp_stats['p95_frame_latency_ms']:.3f} / {ptp_stats['p99_frame_latency_ms']:.3f} / {ptp_stats['max_frame_latency_ms']:.3f} ms")
            
            logging.info(f"\n2. CPU Wake Up Time:")
            logging.info(f"   Mean: {ptp_stats['mean_cpu_wakeup_ms']:.3f} ms")
            logging.info(f"   Min/P95/P99/Max: {ptp_stats['min_cpu_wakeup_ms']:.3f} / {ptp_stats['p95_cpu_wakeup_ms']:.3f} / {ptp_stats['p99_cpu_wakeup_ms']:.3f} / {ptp_stats['max_cpu_wakeup_ms']:.3f} ms")
            
            logging.info(f"\n3. LinuxReceiverOp Latency:")
            logging.info(f"   Mean: {ptp_stats['mean_receiver_latency_ms']:.3f} ms")
            logging.info(f"   Min/P95/P99/Max: {ptp_stats['min_receiver_latency_ms']:.3f} / {ptp_stats['p95_receiver_latency_ms']:.3f} / {ptp_stats['p99_receiver_latency_ms']:.3f} / {ptp_stats['max_receiver_latency_ms']:.3f} ms")
            
            logging.info(f"\n4. ISP + Visualizer Op Latency:")
            logging.info(f"   Mean: {ptp_stats['mean_isp_viz_latency_ms']:.3f} ms")
            logging.info(f"   Min/P95/P99/Max: {ptp_stats['min_isp_viz_latency_ms']:.3f} / {ptp_stats['p95_isp_viz_latency_ms']:.3f} / {ptp_stats['p99_isp_viz_latency_ms']:.3f} / {ptp_stats['max_isp_viz_latency_ms']:.3f} ms")
            
            logging.info(f"\n5. GPU Host Latency (CPU wake + Receiver + ISP/Viz):")
            logging.info(f"   Mean: {ptp_stats['mean_gpu_host_latency_ms']:.3f} ms")
            logging.info(f"   Min/P95/P99/Max: {ptp_stats['min_gpu_host_latency_ms']:.3f} / {ptp_stats['p95_gpu_host_latency_ms']:.3f} / {ptp_stats['p99_gpu_host_latency_ms']:.3f} / {ptp_stats['max_gpu_host_latency_ms']:.3f} ms")
            
            logging.info(f"\n6. Total Latency Per Frame:")
            logging.info(f"   Mean: {ptp_stats['mean_total_latency_ms']:.3f} ms")
            logging.info(f"   Min/P95/P99/Max: {ptp_stats['min_total_latency_ms']:.3f} / {ptp_stats['p95_total_latency_ms']:.3f} / {ptp_stats['p99_total_latency_ms']:.3f} / {ptp_stats['max_total_latency_ms']:.3f} ms")
            
            logging.info(f"\n7. Inter-Frame Jitter (PTP clock stability):")
            expected_interval_ms = 16.67 if camera_mode == 0 else 33.33
            logging.info(f"   Mean interval: {ptp_stats['mean_frame_interval_ms']:.3f} ms (expected: ~{expected_interval_ms:.2f} ms)")
            logging.info(f"   Jitter: {ptp_stats['frame_jitter_pct']:.3f}%")
            logging.info(f"   Std Dev: {ptp_stats['stdev_frame_interval_ms']:.3f} ms")
            logging.info(f"   Frames outside tolerance: {ptp_stats['interval_fail_count']}")
            
            if ptp_stats['frame_jitter_pct'] > 10.0:
                logging.warning(f"  [!]  High jitter ({ptp_stats['frame_jitter_pct']:.2f}%) - check camera configuration")
            else:
                logging.info(f"   ✓ Frame timing is stable")
            
            # Print summary table
            logging.info(f"\n")
            logging.info(f"{'='*80}")
            logging.info(f"LATENCY SUMMARY TABLE (Average values for {ptp_stats['frames_analyzed']} frames in ms)")
            logging.info(f"{'='*80}\n")
            
            # Calculate column widths
            col_width = 20
            
            # Row 1: Headers
            logging.info(f"{'='*91}")
            logging.info(f"|{'Frame Latency':^{col_width}} | {'CPU Wake Up':^{col_width}} | {'ReceiverOp':^{col_width}} | {'ISP+Viz Op':^{col_width}}|")
            logging.info(f"|{'-'*col_width}-+-{'-'*col_width}-+-{'-'*col_width}-+-{'-'*col_width}|")
            
            # Row 2: Values
            logging.info(f"|{ptp_stats['mean_frame_latency_ms']:^{col_width}.3f} | {ptp_stats['mean_cpu_wakeup_ms']:^{col_width}.3f} | {ptp_stats['mean_receiver_latency_ms']:^{col_width}.3f} | {ptp_stats['mean_isp_viz_latency_ms']:^{col_width}.3f}|")
            logging.info(f"|{'-'*col_width}-+-{'-'*col_width}-+-{'-'*col_width}-+-{'-'*col_width}|")
            
            # Row 3: GPU Host Latency header (merged cols 2-4)
            logging.info(f"|{'':^{col_width}} | {'GPU Host Latency (CPU+Receiver+ISP/Viz)':^{col_width*3 + 6}}|")
            logging.info(f"|{'-'*col_width}-+-{'-'*(col_width*3 + 6)}|")
            
            # Row 4: GPU Host Latency value (merged cols 2-4)
            logging.info(f"|{'':^{col_width}} | {ptp_stats['mean_gpu_host_latency_ms']:^{col_width*3 + 6}.3f}|")
            logging.info(f"{'='*91}")
            
            # Row 5: Total Latency header (merged all cols)
            logging.info(f"|{'Total Latency Per Frame':^89}|")
            logging.info(f"|{'-'*89}|")
            
            # Row 6: Total Latency value (merged all cols)
            logging.info(f"|{ptp_stats['mean_total_latency_ms']:^{89}.3f}|")
            logging.info(f"{'='*91}\n")
            
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
    parser = argparse.ArgumentParser(description="Verify IMX258 PTP timestamp accuracy")
    parser.add_argument("--camera-ip", type=str, default="192.168.0.2", help="Hololink device IP")
    parser.add_argument("--camera-mode", type=int, default=0, help="Camera mode (0=60fps, 1=30fps)")
    parser.add_argument("--frame-limit", type=int, default=300, help="Number of frames to analyze")
    
    return parser.parse_args()


def main() -> Tuple[bool, str, dict]:
    """
    Verify PTP timestamp accuracy for IMX258 camera (Linux UDP only).
    
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
            "frames_dropped_for_stability": 0,
            "frames_with_missing_metadata": 0,
            "frames_analyzed": 0,
            "mean_frame_latency_ms": 0,
            "expected_frame_latency_ms": 0,
            "mean_cpu_wakeup_ms": 0,
            "mean_receiver_latency_ms": 0,
            "mean_isp_viz_latency_ms": 0,
            "mean_gpu_host_latency_ms": 0,
            "mean_total_latency_ms": 0,
            "mean_frame_interval_ms": 0,
            "stdev_frame_interval_ms": 0,
            "frame_jitter_pct": 0,
            "interval_fail_count": 0,
            "expected_interval_ms": 16.67 if cam_mode == 0 else 33.33,
            "test_duration_sec": 0,
        }
        print(f"📊 Metrics: {stats}")
        return ptp_pass, "PTP measurement failed", stats
    else:
        # Extract metrics for validation
        mean_frame_latency = result['mean_frame_latency_ms']
        mean_total_latency = result['mean_total_latency_ms']
        interval_fail_count = result['interval_fail_count']
        
        # Expected frame latency (mode-specific):
        EXPECTED_FRAME_LAT_MS = {
            0: 7.87,   # Mode 0: 60fps
            1: 15.8,   # Mode 1: 30fps
        }
        expected_lat_ms = EXPECTED_FRAME_LAT_MS.get(cam_mode, 7.87)
        tolerance = 0.20  # ±20%
        
        # Pass criteria:
        # 1. Frame latency within ±20% of expected
        # 2. Inter-frame jitter acceptable (< 10% of frames outside tolerance)
        ptp_pass = (
            (expected_lat_ms * (1 - tolerance) <= mean_frame_latency <= expected_lat_ms * (1 + tolerance)) and
            (interval_fail_count <= frame_lim * 0.1)
        )
        
        stats = {
            "camera_ip": cam_ip,
            "camera_mode": cam_mode,
            "frame_limit": frame_lim,
            "frames_captured": result['frames_captured'],
            "frames_dropped_for_stability": result['frames_dropped_for_stability'],
            "frames_with_missing_metadata": result['frames_with_missing_metadata'],
            "frames_analyzed": result['frames_analyzed'],
            
            # Frame Latency
            "mean_frame_latency_ms": result['mean_frame_latency_ms'],
            "expected_frame_latency_ms": expected_lat_ms,
            "min_frame_latency_ms": result['min_frame_latency_ms'],
            "max_frame_latency_ms": result['max_frame_latency_ms'],
            "p95_frame_latency_ms": result['p95_frame_latency_ms'],
            "p99_frame_latency_ms": result['p99_frame_latency_ms'],
            
            # CPU Wake Up Time
            "mean_cpu_wakeup_ms": result['mean_cpu_wakeup_ms'],
            
            # LinuxReceiverOp Latency
            "mean_receiver_latency_ms": result['mean_receiver_latency_ms'],
            
            # ISP + Visualizer Op Latency
            "mean_isp_viz_latency_ms": result['mean_isp_viz_latency_ms'],
            
            # GPU Host Latency
            "mean_gpu_host_latency_ms": result['mean_gpu_host_latency_ms'],
            
            # Total Latency
            "mean_total_latency_ms": result['mean_total_latency_ms'],
            "min_total_latency_ms": result['min_total_latency_ms'],
            "max_total_latency_ms": result['max_total_latency_ms'],
            
            # Inter-frame jitter
            "mean_frame_interval_ms": result['mean_frame_interval_ms'],
            "stdev_frame_interval_ms": result['stdev_frame_interval_ms'],
            "frame_jitter_pct": result['frame_jitter_pct'],
            "interval_fail_count": result['interval_fail_count'],
            
            # Metadata
            "expected_interval_ms": result['expected_interval_ms'],
            "test_duration_sec": result.get('test_duration_sec', 0),
        }
        
        print(f"📊 Metrics: {stats}")
        
        if ptp_pass:
            return True, (f"PTP validation passed (Frame latency={mean_frame_latency:.2f}ms, "
                         f"Total latency={mean_total_latency:.2f}ms)"), stats
        else:
            failure_reasons = []
            if not (expected_lat_ms * (1 - tolerance) <= mean_frame_latency <= expected_lat_ms * (1 + tolerance)):
                failure_reasons.append(f"Frame latency={mean_frame_latency:.2f}ms (expected {expected_lat_ms}±{int(tolerance*100)}% for mode {cam_mode})")
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
