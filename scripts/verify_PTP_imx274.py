import ctypes
import re
import subprocess
from typing import Optional, Tuple
import sys
from pathlib import Path
import logging
import time
import argparse
import statistics
import os
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

def record_times(recorder_queue, metadata):
    """Record all timestamps from metadata to queue for later analysis."""
    frame_number = metadata.get("frame_number", 0)
    
    # Extract all 5 timestamps
    frame_start_s = get_timestamp(metadata, "timestamp")
    frame_end_s = get_timestamp(metadata, "metadata")
    received_timestamp_s = get_timestamp(metadata, "received")
    operator_timestamp_s = get_timestamp(metadata, "operator_timestamp")
    complete_timestamp_s = get_timestamp(metadata, "complete_timestamp")
    
    recorder_queue.append(
        (
            frame_start_s,
            frame_end_s,
            received_timestamp_s,
            operator_timestamp_s,
            complete_timestamp_s,
            frame_number,
        )
    )

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
        operator_timestamp = datetime.datetime.utcnow()

        in_message = op_input.receive("input")
        cp_frame = cp.asarray(in_message.get(""))
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
        complete_timestamp = datetime.datetime.utcnow()
        
        in_message = op_input.receive("input")
        
        # Save complete_timestamp to metadata
        save_timestamp(self.metadata, "complete_timestamp", complete_timestamp)
        
        # Record all timestamps to queue for analysis
        record_times(self._recorder_queue, self.metadata)
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
        self.frame_limit = frame_limit  
        self.frame_count = 0
        self.start_time = None
        self.camera_mode = camera_mode  # Store for mode-aware tolerance checking
        
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


def _measure_hololink_ptp(camera_ip: str = "192.168.0.2", frame_limit: int = 300, 
                          timeout_seconds: int = 15, camera_mode: int = 1) -> Optional[dict]:
    """
    Comprehensive PTP timestamp measurement for IMX274 camera.
    
    Args:
        camera_ip: IP of Hololink device
        frame_limit: Number of frames to analyze 
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
        channel_metadata = hololink_module.Enumerator.find_channel(channel_ip=camera_ip)
        if not channel_metadata:
            logging.warning(f"Failed to find Hololink device at {camera_ip}")
            return None
        
        logging.info("Hololink device found")
        
        # Initialize camera (IMX274-specific)
        hololink_channel = hololink_module.DataChannel(channel_metadata)
        camera = hololink_module.sensors.imx274.dual_imx274.Imx274Cam(hololink_channel, expander_configuration=0)
        camera_mode_enum = hololink_module.sensors.imx274.imx274_mode.Imx274_Mode(camera_mode)
        
        # Minimal application for PTP measurement
        class HoloscanApplication(holoscan.core.Application):
            """Minimal app for PTP timestamp measurement."""
            
            def __init__(self, cuda_ctx, cuda_dev_ord, hl_chan, cam, frame_limit, 
                        camera_mode=1, headless=False, fullscreen=True):
                super().__init__()
                self._cuda_context = cuda_ctx
                self._cuda_device_ordinal = cuda_dev_ord
                self._hololink_channel = hl_chan
                self._camera = cam
                self._frame_limit = frame_limit  
                self._camera_mode = camera_mode
                self._headless = False  # Hardcoded: Always show window
                self._fullscreen = True  # Hardcoded: Always fullscreen for best performance
                self._recorder_queue = []  # Not used but needed for operator compatibility
                self._frame_counter = None
                # Enable metadata access from C++ receiver (required for PTP timestamps)
                self.enable_metadata(True)
            
            def compose(self):
                # CRITICAL: Set camera mode BEFORE creating receiver (updates dimensions)
                # This must happen in compose() so receiver gets correct frame_size
                self._camera.set_mode(self._camera_mode)
                logging.info(f"Camera mode set to {self._camera_mode}: {self._camera._width}x{self._camera._height}")
                
                # Use CountCondition to limit frames
                if self._frame_limit:
                    self._count = holoscan.conditions.CountCondition(
                        self,
                        name="count",
                        count=self._frame_limit,
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

                frame_size = csi_to_bayer_operator.get_csi_length()
                receiver_operator = hololink_module.operators.LinuxReceiverOperator(
                    self,
                    count_condition,
                    name="receiver",
                    frame_size=frame_size,
                    frame_context=self._cuda_context,
                    hololink_channel=self._hololink_channel,
                    device=self._camera
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
                    frame_limit=self._frame_limit,
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
                
                # Pipeline: receiver → profiler → csi_to_bayer → processor → demosaic → visualizer → monitor → frame_counter
                self.add_flow(receiver_operator, profiler, {("output", "input")})
                self.add_flow(profiler, csi_to_bayer_operator, {("output", "input")})
                self.add_flow(csi_to_bayer_operator, image_processor_operator, {("output", "input")})
                self.add_flow(image_processor_operator, demosaic, {("output", "receiver")})
                self.add_flow(demosaic, visualizer, {("transmitter", "receivers")})
                self.add_flow(visualizer, monitor, {("camera_pose_output", "input")})
                self.add_flow(monitor, self._frame_counter, {("output", "input")})
            
            def get_frame_count(self) -> int:
                # Return count from recorder queue since frame_counter is commented out
                return len(self._recorder_queue) if self._recorder_queue else 0
        
        # Create application        
        application = HoloscanApplication(
            cu_context,
            cu_device_ordinal,
            hololink_channel,
            camera,
            frame_limit,
            camera_mode_enum,  # ← Pass enum, not int
        )
        
        # Start Hololink and camera (IMX274-specific sequence - MUST follow official order for PTP)
        logging.info("Starting Hololink...")
        hololink = hololink_channel.hololink()
        hololink.start()
        #hololink.reset()  # Ensure clean state

        # CRITICAL: Synchronize PTP clock (same as IMX258)
        logging.info("Synchronizing PTP clock...")
        if not hololink.ptp_synchronize():
            logging.error("Failed to synchronize PTP - timestamps will be invalid")
            return None
        logging.info("PTP synchronized successfully")

        # Configure camera AFTER PTP sync (IMX274-specific sequence)
        logging.info("Configuring camera...")
        camera.setup_clock()  # IMX274-specific
        camera.configure(camera_mode_enum)
        camera.set_digital_gain_reg(0x4)  # IMX274-specific
        
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
        
        # Get recorded timestamps from queue
        recorder_queue = application._recorder_queue
        if not recorder_queue or len(recorder_queue) < 100:
            logging.error(f"Insufficient frames captured: {len(recorder_queue) if recorder_queue else 0}")
            return None
        
        # Calculate statistics from recorder queue (matching official script)
        logging.info(f"Processing {len(recorder_queue)} captured frames...")
        
        # Drop first/last 5 frames for stability (NVIDIA approach)
        settled_timestamps = recorder_queue[5:-5]
        frames_analyzed = len(settled_timestamps)
        
        logging.info(f"Analyzing {frames_analyzed} frames after dropping first/last 5")
        
        # Calculate latencies for each frame
        frame_time_dts = []
        cpu_latency_dts = []
        operator_latency_dts = []
        processing_time_dts = []
        overall_time_dts = []

        
        for (
            frame_start_s,
            frame_end_s,
            received_timestamp_s,
            operator_timestamp_s,
            complete_timestamp_s,
            frame_number,
        ) in settled_timestamps:
            frame_time_dt = frame_end_s - frame_start_s
            frame_time_dts.append(frame_time_dt)
            
            cpu_latency_dt = received_timestamp_s - frame_end_s
            cpu_latency_dts.append(cpu_latency_dt)
            
            operator_latency_dt = operator_timestamp_s - received_timestamp_s
            operator_latency_dts.append(operator_latency_dt)
            
            processing_time_dt = complete_timestamp_s - operator_timestamp_s
            processing_time_dts.append(processing_time_dt)
                      
            overall_time_dt = complete_timestamp_s - frame_start_s
            overall_time_dts.append(overall_time_dt)
        
        # Calculate statistics (convert to ms)
        sorted_frame_lat = sorted(frame_time_dts)
        sorted_cpu_wake = sorted(cpu_latency_dts)
        sorted_receiver = sorted(operator_latency_dts)
        sorted_isp_viz = sorted(processing_time_dts)
        sorted_total = sorted(overall_time_dts)

        p95_idx = int(len(settled_timestamps) * 0.95)
        p99_idx = int(len(settled_timestamps) * 0.99)
        
        ptp_stats = {
            "frame_count": frame_limit,
            "frames_captured": len(recorder_queue),
            "frames_with_missing_metadata": 0,  # All frames in queue have complete timestamps
            "frames_analyzed": frames_analyzed,
            
            # Frame Latency (sensor readout + FPGA processing)
            "mean_frame_latency_ms": statistics.mean(frame_time_dts) * 1000,
            "min_frame_latency_ms": min(frame_time_dts) * 1000,
            "max_frame_latency_ms": max(frame_time_dts) * 1000,
            "p95_frame_latency_ms": sorted_frame_lat[p95_idx] * 1000,
            "p99_frame_latency_ms": sorted_frame_lat[p99_idx] * 1000,
            "stdev_frame_latency_us": statistics.stdev(frame_time_dts) * 1000000 if len(frame_time_dts) > 1 else 0,


            # CPU Wake Up Time
            "mean_cpu_wakeup_ms": statistics.mean(cpu_latency_dts) * 1000,
            "min_cpu_wakeup_ms": min(cpu_latency_dts) * 1000,
            "max_cpu_wakeup_ms": max(cpu_latency_dts) * 1000,
            "p95_cpu_wakeup_ms": sorted_cpu_wake[p95_idx] * 1000,
            "p99_cpu_wakeup_ms": sorted_cpu_wake[p99_idx] * 1000,

            
            # ReceiverOp Latency
            "mean_receiver_latency_ms": statistics.mean(operator_latency_dts) * 1000,
            "min_receiver_latency_ms": min(operator_latency_dts) * 1000,
            "max_receiver_latency_ms": max(operator_latency_dts) * 1000,
            "p95_receiver_latency_ms": sorted_receiver[p95_idx] * 1000,
            "p99_receiver_latency_ms": sorted_receiver[p99_idx] * 1000,
            

            # ISP + Visualizer Op Latency
            "mean_isp_viz_latency_ms": statistics.mean(processing_time_dts) * 1000,
            "min_isp_viz_latency_ms": min(processing_time_dts) * 1000,
            "max_isp_viz_latency_ms": max(processing_time_dts) * 1000,
            "p95_isp_viz_latency_ms": sorted_isp_viz[p95_idx] * 1000,
            "p99_isp_viz_latency_ms": sorted_isp_viz[p99_idx] * 1000,
            
            
            # Total Latency
            "mean_total_latency_ms": statistics.mean(overall_time_dts) * 1000,
            "min_total_latency_ms": min(overall_time_dts) * 1000,
            "max_total_latency_ms": max(overall_time_dts) * 1000,
            "p95_total_latency_ms": sorted_total[p95_idx] * 1000,
            "p99_total_latency_ms": sorted_total[p99_idx] * 1000,
            

            # Calculate percentiles
            "p95_frame_latency_ms": sorted_frame_lat[p95_idx] * 1000,
            "p99_frame_latency_ms": sorted_frame_lat[p99_idx] * 1000,
            "p95_cpu_wakeup_ms": sorted_cpu_wake[p95_idx] * 1000,
            "p99_cpu_wakeup_ms": sorted_cpu_wake[p99_idx] * 1000,
            "p95_receiver_latency_ms": sorted_receiver[p95_idx] * 1000,
            "p99_receiver_latency_ms": sorted_receiver[p99_idx] * 1000,
            "p95_isp_viz_latency_ms": sorted_isp_viz[p95_idx] * 1000,
            "p99_isp_viz_latency_ms": sorted_isp_viz[p99_idx] * 1000,
            "p95_total_latency_ms": sorted_total[p95_idx] * 1000,
            "p99_total_latency_ms": sorted_total[p99_idx] * 1000,
            
            # Inter-frame jitter
            "mean_frame_interval_ms": 0,  # Calculated below
            "stdev_frame_interval_ms": 0,  # Calculated below
            "frame_jitter_pct": 0,  # Calculated below
            "interval_fail_count": 0,
            "expected_interval_ms": 16.67,
            "camera_mode": camera_mode,
        }
        
        # Calculate inter-frame intervals
        frame_end_times = [t[1] for t in settled_timestamps]
        ptp_intervals = [frame_end_times[i+1] - frame_end_times[i] for i in range(len(frame_end_times) - 1)]
        if ptp_intervals:
            ptp_stats["mean_frame_interval_ms"] = statistics.mean(ptp_intervals) * 1000
            ptp_stats["stdev_frame_interval_ms"] = statistics.stdev(ptp_intervals) * 1000 if len(ptp_intervals) > 1 else 0
            ptp_stats["frame_jitter_pct"] = (statistics.stdev(ptp_intervals) / statistics.mean(ptp_intervals) * 100) if statistics.mean(ptp_intervals) > 0 else 0
            ptp_stats["interval_fail_count"] = sum(1 for intv in ptp_intervals if intv*1000 >= 16.67 * 1.05)
        
        # Now report the statistics
        logging.info(f"\n{'='*80}")
        logging.info(f"PTP Timestamp Analysis (IMX274, Linux UDP)\n{'='*80}")
        logging.info(f"Frames requested: {ptp_stats['frame_count']}")
        logging.info(f"Frames captured: {ptp_stats['frames_captured']})")
        logging.info(f"Frames analyzed: {ptp_stats['frames_analyzed']}")
        
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
        
        logging.info(f"\n5. Total Latency Per Frame:")
        logging.info(f"   Mean: {ptp_stats['mean_total_latency_ms']:.3f} ms")
        logging.info(f"   Min/P95/P99/Max: {ptp_stats['min_total_latency_ms']:.3f} / {ptp_stats['p95_total_latency_ms']:.3f} / {ptp_stats['p99_total_latency_ms']:.3f} / {ptp_stats['max_total_latency_ms']:.3f} ms")
        
        logging.info(f"\n6. Inter-Frame Jitter (PTP clock stability):")
        expected_interval_ms = 16.67  # All IMX274 modes run at 60fps
        logging.info(f"   Mean interval: {ptp_stats['mean_frame_interval_ms']:.3f} ms (expected: ~{expected_interval_ms:.2f} ms)")
        logging.info(f"   Jitter: {ptp_stats['frame_jitter_pct']:.3f}%")
        logging.info(f"   Std Dev: {ptp_stats['stdev_frame_interval_ms']:.3f} ms")
        logging.info(f"   Frames outside tolerance: {ptp_stats['interval_fail_count']}")
        
        if ptp_stats['frame_jitter_pct'] > 10.0:
            logging.warning(f"   [!]  High jitter ({ptp_stats['frame_jitter_pct']:.2f}%) - check camera configuration")
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
         
        # Row 3: Total Latency header (merged all cols)
        logging.info(f"|{'Total Latency Per Frame':^89}|")
        logging.info(f"|{'-'*89}|")
        
        # Row 4: Total Latency value (merged all cols)
        logging.info(f"|{ptp_stats['mean_total_latency_ms']:^{89}.3f}|")
        logging.info(f"{'='*91}\n")
        

        return ptp_stats
        
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
    parser.add_argument("--camera-mode", type=int, default=0, help="Camera mode (0-1, all run at 60fps)")
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
            "frames_with_missing_metadata": 0,
            "frames_analyzed": 0,
            "mean_frame_latency_ms": 0,
            "expected_frame_latency_ms": 0,
            "mean_cpu_wakeup_ms": 0,
            "mean_receiver_latency_ms": 0,
            "mean_isp_viz_latency_ms": 0,
            "mean_total_latency_ms": 0,
            "mean_frame_interval_ms": 0,
            "stdev_frame_interval_ms": 0,
            "frame_jitter_pct": 0,
            "interval_fail_count": 0,
            "expected_interval_ms": 16.67,
            "test_duration_sec": 0,
        }
        print(f"📊 Metrics: {stats}")
        return ptp_pass, "PTP measurement failed", stats
    else:
        # Extract metrics for validation
        mean_frame_latency = result['mean_frame_latency_ms']
        mean_cpu_wakeup = result['mean_cpu_wakeup_ms']
        mean_receiver_latency = result['mean_receiver_latency_ms']
        mean_isp_viz_latency = result['mean_isp_viz_latency_ms']
        mean_total_latency = result['mean_total_latency_ms']
        interval_fail_count = result['interval_fail_count']
        jitter_pct = result['frame_jitter_pct']
        
        # Expected frame latency (mode-specific):
        EXPECTED_FRAME_LAT_MS = {
            0: 15.8,   # Mode 0: 4K 60fps
            1: 7.87,   # Mode 1: 1080p 60fps
            2: 15.8,   # Mode 2: 4K 60fps 12-bit
        }
        expected_lat_ms = EXPECTED_FRAME_LAT_MS.get(cam_mode, 15.8)
        tolerance = 0.20  # ±20%
        
        # Pass criteria matching IMX258:
        # 1. Frame latency within ±20% of expected
        # 2. Jitter < 10%
        # 3. Inter-frame interval stability (< 10% of frames outside tolerance)
        ptp_pass = (
            (expected_lat_ms * (1 - tolerance) <= mean_frame_latency <= expected_lat_ms * (1 + tolerance)) and
            (jitter_pct < 10.0) and
            (interval_fail_count <= frame_lim * 0.1)
        )
        
        stats = {
            "camera_ip": cam_ip,
            "camera_mode": cam_mode,
            "frame_limit": frame_lim,
            "frames_captured": result['frames_captured'],
            "frames_with_missing_metadata": result['frames_with_missing_metadata'],
            "frames_analyzed": result['frames_analyzed'],
            
            # Frame Latency (FPGA processing)
            "mean_frame_latency_ms": result['mean_frame_latency_ms'],
            "expected_frame_latency_ms": expected_lat_ms,
            "min_frame_latency_ms": result['min_frame_latency_ms'],
            "max_frame_latency_ms": result['max_frame_latency_ms'],
            "p95_frame_latency_ms": result['p95_frame_latency_ms'],
            "p99_frame_latency_ms": result['p99_frame_latency_ms'],
            
            # CPU Wake Up Time
            "mean_cpu_wakeup_ms": result['mean_cpu_wakeup_ms'],
            "min_cpu_wakeup_ms": result['min_cpu_wakeup_ms'],
            "max_cpu_wakeup_ms": result['max_cpu_wakeup_ms'],
            "p95_cpu_wakeup_ms": result['p95_cpu_wakeup_ms'],
            "p99_cpu_wakeup_ms": result['p99_cpu_wakeup_ms'],
            
            # Receiver Latency
            "mean_receiver_latency_ms": result['mean_receiver_latency_ms'],
            "min_receiver_latency_ms": result['min_receiver_latency_ms'],
            "max_receiver_latency_ms": result['max_receiver_latency_ms'],
            "p95_receiver_latency_ms": result['p95_receiver_latency_ms'],
            "p99_receiver_latency_ms": result['p99_receiver_latency_ms'],
            
            # ISP + Visualizer Latency
            "mean_isp_viz_latency_ms": result['mean_isp_viz_latency_ms'],
            "min_isp_viz_latency_ms": result['min_isp_viz_latency_ms'],
            "max_isp_viz_latency_ms": result['max_isp_viz_latency_ms'],
            "p95_isp_viz_latency_ms": result['p95_isp_viz_latency_ms'],
            "p99_isp_viz_latency_ms": result['p99_isp_viz_latency_ms'],
            
            # Total Latency (Complete frame processing time)
            "mean_total_latency_ms": result['mean_total_latency_ms'],
            "min_total_latency_ms": result['min_total_latency_ms'],
            "max_total_latency_ms": result['max_total_latency_ms'],
            "p95_total_latency_ms": result['p95_total_latency_ms'],
            "p99_total_latency_ms": result['p99_total_latency_ms'],
            
            # Inter-frame jitter (PTP domain)
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
                         f"Total latency={mean_total_latency:.2f}ms, Jitter={jitter_pct:.2f}%)"), stats
        else:
            failure_reasons = []
            if not (expected_lat_ms * (1 - tolerance) <= mean_frame_latency <= expected_lat_ms * (1 + tolerance)):
                failure_reasons.append(f"Frame latency={mean_frame_latency:.2f}ms (expected {expected_lat_ms}±{int(tolerance*100)}% for mode {cam_mode})")
            if jitter_pct >= 10.0:
                failure_reasons.append(f"Jitter={jitter_pct:.2f}% (max 10%)")
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
