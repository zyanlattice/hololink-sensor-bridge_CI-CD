
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


class InstrumentedTimeProfiler(holoscan.core.Operator):
    """Pass-through operator that records operator_timestamp for latency analysis."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
    
    def setup(self, spec):
        spec.input("input")
        spec.output("output")
    
    def compute(self, op_input, op_output, context):
        # Record when this operator executes (pipeline scheduler overhead measurement)
        operator_timestamp = datetime.datetime.now(datetime.UTC)
        
        in_message = op_input.receive("input")
        
        # Write operator_timestamp to metadata for downstream operators
        save_timestamp(self.metadata, "operator_timestamp", operator_timestamp)
        
        # Forward the message unchanged (pass-through)
        op_output.emit(in_message, "output")
    

class FrameCounterOp(holoscan.core.Operator):
    """Terminal operator to count frames and perform complete PTP latency analysis."""
    
    def __init__(self, *args, frame_limit=50, app=None, pass_through=False, camera=None, hololink=None, save_images=False, camera_mode=0, **kwargs):
        self.pass_through = pass_through
        self.frame_limit = frame_limit
        self.frame_count = 0
        self.start_time = None
        self.timestamps = []  # System clock timestamps
        self.ptp_timestamps = []  # PTP timestamps from FPGA
        self.camera_mode = camera_mode  # Store for mode-aware tolerance checking
        
        # Store all 5 timestamp types for complete latency analysis
        self.frame_start_times = []      # timestamp: FPGA first byte
        self.frame_end_times = []        # metadata: FPGA last byte
        self.received_times = []         # received: Host background thread wakeup
        self.operator_times = []         # operator_timestamp: Pipeline operator execution
        self.complete_times = []         # complete_timestamp: This operator execution
        
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
        
        # Record when THIS operator executes (complete_timestamp)
        complete_timestamp = datetime.datetime.now(datetime.UTC)
        
        # Receive message FIRST - this makes self.metadata available
        in_message = op_input.receive("input")
        
        # Write complete_timestamp to metadata
        save_timestamp(self.metadata, "complete_timestamp", complete_timestamp)
        
        if self.start_time is None:
            self.start_time = time.time()
        
        self.frame_count += 1
        self.timestamps.append(time.time())
        
        # Read ALL 5 timestamp types for complete latency analysis
        try:
            frame_start_s = get_timestamp(self.metadata, "timestamp")      # FPGA: first data byte
            frame_end_s = get_timestamp(self.metadata, "metadata")         # FPGA: last data byte + metadata
            received_s = get_timestamp(self.metadata, "received")          # Host: background thread wakeup
            operator_s = get_timestamp(self.metadata, "operator_timestamp") # Host: profiler operator execution
            complete_s = get_timestamp(self.metadata, "complete_timestamp") # Host: this operator execution
            
            self.frame_start_times.append(frame_start_s)
            self.frame_end_times.append(frame_end_s)
            self.received_times.append(received_s)
            self.operator_times.append(operator_s)
            self.complete_times.append(complete_s)
            
            # Keep legacy ptp_timestamps for backward compatibility (jitter analysis)
            self.ptp_timestamps.append(frame_end_s)
            
            if self.frame_count == 1 and frame_end_s > 0:
                logging.info(f"✓ PTP metadata available (all 5 timestamps recorded)")
            elif self.frame_count == 1:
                logging.warning(f"⚠️  PTP timestamp is {frame_end_s} (may not be populated by receiver)")
        except Exception as e:
            logging.warning(f"Could not read all PTP timestamps from metadata: {e}")
            # Append None for missing data
            self.frame_start_times.append(None)
            self.frame_end_times.append(None)
            self.received_times.append(None)
            self.operator_times.append(None)
            self.complete_times.append(None)
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
    
    def get_ptp_timing_stats(self) -> dict:
        """Analyze complete PTP latency from all 5 timestamp types."""
        import statistics
        
        # Filter out None values (frames where PTP metadata wasn't available)
        valid_indices = [i for i in range(len(self.frame_start_times)) 
                        if self.frame_start_times[i] is not None 
                        and self.frame_end_times[i] is not None
                        and self.received_times[i] is not None
                        and self.operator_times[i] is not None
                        and self.complete_times[i] is not None]
        
        if len(valid_indices) < 2:
            return {"error": "Insufficient PTP timestamp data"}
        
        # Calculate all 5 latency metrics for each frame (like linux_imx258_latency.py)
        frame_acquisition_times = []  # Sensor readout + FPGA processing (expected ~20ms)
        cpu_latencies = []            # Network + CPU wakeup latency
        operator_latencies = []       # Pipeline scheduler overhead
        processing_times = []         # Processing time (minimal in this test)
        overall_latencies = []        # Total end-to-end latency
        
        for i in valid_indices:
            frame_start = self.frame_start_times[i]
            frame_end = self.frame_end_times[i]
            received = self.received_times[i]
            operator = self.operator_times[i]
            complete = self.complete_times[i]
            
            # Calculate latencies (in seconds)
            frame_time_dt = frame_end - frame_start                 # Sensor readout (~15.8ms) + FPGA processing (~4-5ms)
            cpu_latency_dt = received - frame_end                   # Network + CPU wakeup
            operator_latency_dt = operator - received               # Pipeline scheduler
            processing_time_dt = complete - operator                # Processing time
            overall_time_dt = complete - frame_start                # Total latency
            
            frame_acquisition_times.append(frame_time_dt)
            cpu_latencies.append(cpu_latency_dt)
            operator_latencies.append(operator_latency_dt)
            processing_times.append(processing_time_dt)
            overall_latencies.append(overall_time_dt)
        
        # Also calculate inter-frame jitter (legacy metric)
        valid_ptp_timestamps = [self.frame_end_times[i] for i in valid_indices]
        ptp_intervals = [valid_ptp_timestamps[i+1] - valid_ptp_timestamps[i] 
                        for i in range(len(valid_ptp_timestamps) - 1)]
        
        # Mode-aware tolerance: 60fps (mode 0) = 16.67ms, 30fps (mode 1) = 33.33ms
        expected_interval_ms = 16.67 if self.camera_mode == 0 else 33.33
        tolerance = 1.05  # 5% tolerance
        fail_cnt = sum(1 for intv in ptp_intervals if intv*1000 >= expected_interval_ms * tolerance)
        
        return {
            "frame_count": self.frame_count,
            "valid_frames": len(valid_indices),
            
            # Frame acquisition time (sensor → FPGA, includes ~4-5ms FPGA overhead)
            "mean_frame_acquisition_ms": statistics.mean(frame_acquisition_times) * 1000,
            "min_frame_acquisition_ms": min(frame_acquisition_times) * 1000,
            "max_frame_acquisition_ms": max(frame_acquisition_times) * 1000,
            "stdev_frame_acquisition_us": statistics.stdev(frame_acquisition_times) * 1000000 if len(frame_acquisition_times) > 1 else 0,
            
            # CPU latency (FPGA → host thread wakeup)
            "mean_cpu_latency_us": statistics.mean(cpu_latencies) * 1000000,
            "min_cpu_latency_us": min(cpu_latencies) * 1000000,
            "max_cpu_latency_us": max(cpu_latencies) * 1000000,
            "stdev_cpu_latency_us": statistics.stdev(cpu_latencies) * 1000000 if len(cpu_latencies) > 1 else 0,
            
            # Operator latency (thread wakeup → operator execution)
            "mean_operator_latency_ms": statistics.mean(operator_latencies) * 1000,
            "min_operator_latency_ms": min(operator_latencies) * 1000,
            "max_operator_latency_ms": max(operator_latencies) * 1000,
            "stdev_operator_latency_us": statistics.stdev(operator_latencies) * 1000000 if len(operator_latencies) > 1 else 0,
            
            # Processing time (operator → complete)
            "mean_processing_time_us": statistics.mean(processing_times) * 1000000,
            "min_processing_time_us": min(processing_times) * 1000000,
            "max_processing_time_us": max(processing_times) * 1000000,
            "stdev_processing_time_us": statistics.stdev(processing_times) * 1000000 if len(processing_times) > 1 else 0,
            
            # Overall latency (frame start → complete)
            "mean_overall_latency_ms": statistics.mean(overall_latencies) * 1000,
            "min_overall_latency_ms": min(overall_latencies) * 1000,
            "max_overall_latency_ms": max(overall_latencies) * 1000,
            "stdev_overall_latency_us": statistics.stdev(overall_latencies) * 1000000 if len(overall_latencies) > 1 else 0,
            
            # Inter-frame jitter (legacy metric)
            "mean_frame_interval_ms": statistics.mean(ptp_intervals) * 1000 if ptp_intervals else 0,
            "stdev_frame_interval_ms": statistics.stdev(ptp_intervals) * 1000 if len(ptp_intervals) > 1 else 0,
            "frame_jitter_pct": (statistics.stdev(ptp_intervals) / statistics.mean(ptp_intervals) * 100) if ptp_intervals and statistics.mean(ptp_intervals) > 0 else 0,
            "interval_fail_count": fail_cnt,
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
            
            def __init__(self, cuda_ctx, cuda_dev_ord, hl_chan, cam, frame_limit, camera_mode=0):
                super().__init__()
                self._cuda_context = cuda_ctx
                self._cuda_device_ordinal = cuda_dev_ord
                self._hololink_channel = hl_chan
                self._camera = cam
                self._frame_limit = frame_limit
                self._camera_mode = camera_mode
                self._frame_counter = None
                # Enable metadata access from C++ receiver (required for PTP timestamps)
                self.enable_metadata(True)
            
            def compose(self):
                # Use CountCondition to limit frames (like linux_imx258_player.py)
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

                
                # Profiler operator to record operator_timestamp (like InstrumentedTimeProfiler)
                profiler = InstrumentedTimeProfiler(
                    self,
                    name="profiler",
                )
                
                # Frame counter as terminal operator (like MonitorOperator in latency.py)
                self._frame_counter = FrameCounterOp(
                    self,
                    name="frame_counter",
                    frame_limit=self._frame_limit,
                    pass_through=False,
                    camera_mode=self._camera_mode
                )
                
                # Pipeline flow: receiver → profiler → frame_counter (terminal)
                self.add_flow(receiver_operator, profiler, {("output", "input")})
                self.add_flow(profiler, self._frame_counter, {("output", "input")})
            
            def get_frame_count(self) -> int:
                return self._frame_counter.frame_count if self._frame_counter else 0
            
            def get_fps(self) -> float:
                if not self._frame_counter or not self._frame_counter.start_time:
                    return 0.0
                elapsed = time.time() - self._frame_counter.start_time
                return self._frame_counter.frame_count / elapsed if elapsed > 0 else 0.0
        
        # Create application
        application = ThroughputApplication(
            cu_context,
            cu_device_ordinal,
            hololink_channel,
            camera,
            frame_limit,
            camera_mode,
        )
        
        # Start Hololink and camera (MUST follow official sequence for PTP)
        logging.info("Starting Hololink...")
        hololink = hololink_channel.hololink()
        hololink.start()
        

        # NOW configure camera AFTER PTP is ready
        logging.info("Configuring camera...")
        camera.configure(camera_mode)
        camera.set_focus(-140)
        camera.set_exposure(0x0600)
        camera.set_analog_gain(0x0180)
        camera.start()
        
        logging.info(f"Capturing {frame_limit} frames...")
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
            
        # Report complete PTP latency analysis (all 5 metrics)
        ptp_stats = application._frame_counter.get_ptp_timing_stats()
        if ptp_stats and "error" not in ptp_stats:
            logging.info(f"\n{'='*70}")
            logging.info(f"Complete PTP Latency Analysis (from LinuxReceiverOp metadata)\n{'='*70}")
            logging.info(f"Frames analyzed: {ptp_stats['valid_frames']}/{ptp_stats['frame_count']}")
            logging.info(f"")
            
            logging.info(f"1. Frame Acquisition Time (sensor → FPGA + processing):")
            logging.info(f"   Mean: {ptp_stats['mean_frame_acquisition_ms']:.3f} ms (sensor ~15.8ms + FPGA ~4-5ms)")
            logging.info(f"   Min/Max: {ptp_stats['min_frame_acquisition_ms']:.3f} / {ptp_stats['max_frame_acquisition_ms']:.3f} ms")
            logging.info(f"   Std Dev: {ptp_stats['stdev_frame_acquisition_us']:.3f} µs")
            logging.info(f"")
            
            logging.info(f"2. CPU Latency (FPGA → host thread wakeup):")
            logging.info(f"   Mean: {ptp_stats['mean_cpu_latency_us']:.3f} µs")
            logging.info(f"   Min/Max: {ptp_stats['min_cpu_latency_us']:.3f} / {ptp_stats['max_cpu_latency_us']:.3f} µs")
            logging.info(f"   Std Dev: {ptp_stats['stdev_cpu_latency_us']:.3f} µs")
            logging.info(f"")
            
            logging.info(f"3. Operator Latency (thread wakeup → operator execution):")
            logging.info(f"   Mean: {ptp_stats['mean_operator_latency_ms']:.3f} ms")
            logging.info(f"   Min/Max: {ptp_stats['min_operator_latency_ms']:.3f} / {ptp_stats['max_operator_latency_ms']:.3f} ms")
            logging.info(f"   Std Dev: {ptp_stats['stdev_operator_latency_us']:.3f} µs")
            logging.info(f"")
            
            logging.info(f"4. Processing Time (operator → complete):")
            logging.info(f"   Mean: {ptp_stats['mean_processing_time_us']:.3f} µs")
            logging.info(f"   Min/Max: {ptp_stats['min_processing_time_us']:.3f} / {ptp_stats['max_processing_time_us']:.3f} µs")
            logging.info(f"   Std Dev: {ptp_stats['stdev_processing_time_us']:.3f} µs")
            logging.info(f"")
            
            logging.info(f"5. Overall Latency (frame start → complete):")
            logging.info(f"   Mean: {ptp_stats['mean_overall_latency_ms']:.3f} ms")
            logging.info(f"   Min/Max: {ptp_stats['min_overall_latency_ms']:.3f} / {ptp_stats['max_overall_latency_ms']:.3f} ms")
            logging.info(f"   Std Dev: {ptp_stats['stdev_overall_latency_us']:.3f} µs")
            logging.info(f"")
            
            logging.info(f"6. Inter-Frame Jitter (PTP clock stability):")
            logging.info(f"   Mean interval: {ptp_stats['mean_frame_interval_ms']:.3f} ms (expected: ~16.67 ms for 60fps)")
            logging.info(f"   Jitter: {ptp_stats['frame_jitter_pct']:.6f}%")
            logging.info(f"   Std Dev: {ptp_stats['stdev_frame_interval_ms']:.3f} ms")
            logging.info(f"   Frames outside tolerance (>20ms): {ptp_stats['interval_fail_count']}")
            
            if ptp_stats['frame_jitter_pct'] > 5.0:
                logging.warning(f"   ⚠️  High PTP jitter detected ({ptp_stats['frame_jitter_pct']:.2f}%) - FPGA clock may not be stable")
            else:
                logging.info(f"   ✓ FPGA clock timing is stable")
            
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
            "mean_frame_acquisition_ms": 0,
            "min_frame_acquisition_ms": 0,
            "max_frame_acquisition_ms": 0,
            "stdev_frame_acquisition_us": 0,
            "mean_cpu_latency_us": 0,
            "min_cpu_latency_us": 0,
            "max_cpu_latency_us": 0,
            "stdev_cpu_latency_us": 0,
            "mean_operator_latency_ms": 0,
            "min_operator_latency_ms": 0,
            "max_operator_latency_ms": 0,
            "stdev_operator_latency_us": 0,
            "mean_processing_time_us": 0,
            "min_processing_time_us": 0,
            "max_processing_time_us": 0,
            "stdev_processing_time_us": 0,
            "mean_overall_latency_ms": 0,
            "min_overall_latency_ms": 0,
            "max_overall_latency_ms": 0,
            "stdev_overall_latency_us": 0,
            "mean_frame_interval_ms": 0,
            "stdev_frame_interval_ms": 0,
            "frame_jitter_pct": 0,
            "interval_fail_count": 0,
        }
        print(f"📊 Metrics: {stats}")
        return ptp_pass, f"Hololink PTP measurement failed", stats
    else:
        # Extract all metrics for validation
        mean_ptp_int = result['mean_frame_acquisition_ms']
        jitter = result['frame_jitter_pct']
        std_dev = result['stdev_frame_interval_ms']
        interval_fail_count = result['interval_fail_count']
        overall_latency = result['mean_overall_latency_ms']
        cpu_latency = result['mean_cpu_latency_us']
        mean_frame_interval = result['mean_frame_interval_ms']
        
        # Pass criteria: interval within tolerance and overall latency reasonable
        ptp_pass = (mean_ptp_int >= 15.8*0.9) and (mean_ptp_int <= 15.8*1.1)  
                   #interval_fail_count <= frame_lim * 0.1)  # Max 10% failures
                   
        
        stats = {
            "camera_ip": cam_ip,
            "camera_mode": cam_mode,
            "frame_limit": frame_lim,
            "frames_captured": result['frame_count'],
            "valid_frames": result['valid_frames'],
            # Frame acquisition time (sensor → FPGA)
            "mean_frame_acquisition_ms": result['mean_frame_acquisition_ms'],
            "min_frame_acquisition_ms": result['min_frame_acquisition_ms'],
            "max_frame_acquisition_ms": result['max_frame_acquisition_ms'],
            "stdev_frame_acquisition_us": result['stdev_frame_acquisition_us'],
            # CPU latency (FPGA → host thread)
            "mean_cpu_latency_us": result['mean_cpu_latency_us'],
            "min_cpu_latency_us": result['min_cpu_latency_us'],
            "max_cpu_latency_us": result['max_cpu_latency_us'],
            "stdev_cpu_latency_us": result['stdev_cpu_latency_us'],
            # Operator latency (thread → operator)
            "mean_operator_latency_ms": result['mean_operator_latency_ms'],
            "min_operator_latency_ms": result['min_operator_latency_ms'],
            "max_operator_latency_ms": result['max_operator_latency_ms'],
            "stdev_operator_latency_us": result['stdev_operator_latency_us'],
            # Processing time (operator → complete)
            "mean_processing_time_us": result['mean_processing_time_us'],
            "min_processing_time_us": result['min_processing_time_us'],
            "max_processing_time_us": result['max_processing_time_us'],
            "stdev_processing_time_us": result['stdev_processing_time_us'],
            # Overall latency (frame start → complete)
            "mean_overall_latency_ms": result['mean_overall_latency_ms'],
            "min_overall_latency_ms": result['min_overall_latency_ms'],
            "max_overall_latency_ms": result['max_overall_latency_ms'],
            "stdev_overall_latency_us": result['stdev_overall_latency_us'],
            # Inter-frame jitter (legacy metric)
            "mean_frame_interval_ms": result['mean_frame_interval_ms'],
            "stdev_frame_interval_ms": result['stdev_frame_interval_ms'],
            "frame_jitter_pct": result['frame_jitter_pct'],
            "interval_fail_count": result['interval_fail_count'],
        }
        
        print(f"📊 Metrics: {stats}")
        
        if ptp_pass:
            return ptp_pass, f"Hololink PTP measurement passed (PTP frame latency={mean_ptp_int:.2f}ms, Expected: 15.8±10% ms)", stats
        else:
            return False, f"Hololink PTP measurement failed: PTP frame latency={mean_ptp_int:.3f}ms, Expected: 15.8±10% ms)", stats
    

if __name__ == "__main__":
    success, message, stats = main()
    if success:
        print(f"[PASS] {message}")
        sys.exit(0)
    else:
        print(f"[FAIL] {message}")
        sys.exit(1)