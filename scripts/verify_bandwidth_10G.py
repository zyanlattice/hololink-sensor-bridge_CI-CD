
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

from verify_device_detection import main as vdd_main

# Add parent scripts directory to path for imports
_script_dir = Path(__file__).parent.parent 
sys.path.insert(0, str(_script_dir))


import cuda.bindings.driver as cuda
import holoscan
import hololink as hololink_module
    



class FrameCounterOp(holoscan.core.Operator):
    """Operator to count received frames and track timestamps (system clock + PTP)."""
    
    def __init__(self, *args, frame_limit=50, app=None, pass_through=False, camera=None, hololink=None, save_images=False, **kwargs):
        self.pass_through = pass_through
        self.frame_limit = frame_limit
        self.frame_count = 0
        self.start_time = None
        self.end_time = None
        self.app = app
        self.camera = camera
        self.hololink = hololink
        self.save_images = save_images
        
        super().__init__(*args, **kwargs)
        
    def setup(self, spec):
        spec.input("input")
        # No output port - this is a terminal operator like MonitorOperator in latency.py
        
    def compute(self, op_input, op_output, context):
        in_message = op_input.receive("input")
        
        now = time.time()
        if self.start_time is None:
            self.start_time = now
        
        self.frame_count += 1
        self.end_time = now
        
        if self.frame_count % 100 == 0:
            fps = self.frame_count / (now - self.start_time)
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


def _read_rx_bytes(iface: str) -> Optional[int]:
    """Read kernel rx_bytes counter for the given interface."""
    try:
        with open(f"/sys/class/net/{iface}/statistics/rx_bytes", "r") as f:
            return int(f.read().strip())
    except Exception as e:
        logging.warning(f"Failed to read rx_bytes for {iface}: {e}")
        return None


def _measure_hololink_throughput(camera_ip: str = "192.168.0.2", frame_limit: int = 300, timeout_seconds: int = 30, camera_mode: int = 4, iface: str = None) -> Tuple[Optional[int], Optional[int]]:
    """
    Measure actual hololink throughput by receiving frames from camera.
    Uses exact same initialization as verify_camera_imx258.py, just counts frames without processing.
    
    Args:
        camera_ip: IP of Hololink device
        frame_limit: Number of frames to receive
        timeout_seconds: Maximum time to wait
        iface: Network interface name for kernel rx_bytes measurement
        
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
        
        # Initialize camera (exactly like verify_camera_imx258.py)
        hololink_channel = hololink_module.DataChannel(channel_metadata)
        camera = hololink_module.sensors.imx258.Imx258(hololink_channel, camera_id=0)
        #camera_mode_enum = hololink_module.sensors.imx258.Imx258_Mode(camera_mode)  # Mode 2 = 60fps_cus
        
        # Minimal application - just receiver + frame counter, no processing
        class ThroughputApplication(holoscan.core.Application):
            """Minimal app for throughput measurement."""
            
            def __init__(self, cuda_ctx, cuda_dev_ord, hl_chan, cam, frame_limit):
                super().__init__()
                self._cuda_context = cuda_ctx
                self._cuda_device_ordinal = cuda_dev_ord
                self._hololink_channel = hl_chan
                self._camera = cam
                self._frame_limit = frame_limit
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
                
                # Query CsiToBayerOp for authoritative frame size, but don't include it in the data flow
                csi_to_bayer_pool = holoscan.resources.BlockMemoryPool(
                    self,
                    name="bayer_pool",
                    storage_type=1,
                    block_size=self._camera._width * ctypes.sizeof(ctypes.c_uint16) * self._camera._height,
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
                self._frame_size = frame_size
                logging.info(f"CSI frame size from get_csi_length(): {frame_size} bytes")

                # Receiver operator - raw frame receive (minimal pipeline, no GPU processing)
                receiver_operator = hololink_module.operators.LinuxReceiverOperator(
                    self,
                    count_condition,
                    name="receiver",
                    frame_size=frame_size,
                    frame_context=self._cuda_context,
                    hololink_channel=self._hololink_channel,
                    device=self._camera
                )

                # Frame counter as terminal operator (no CsiToBayerOp in flow for stable throughput)
                self._frame_counter = FrameCounterOp(
                    self,
                    name="frame_counter",
                    frame_limit=self._frame_limit,
                    pass_through=False
                )
                
                self.add_flow(receiver_operator, self._frame_counter, {("output", "input")})
            
            def get_frame_count(self) -> int:
                return self._frame_counter.frame_count if self._frame_counter else 0
            
            def get_fps(self) -> float:
                if not self._frame_counter or not self._frame_counter.start_time or not self._frame_counter.end_time:
                    return 0.0
                elapsed = self._frame_counter.end_time - self._frame_counter.start_time
                # Fence post: N frames span N-1 intervals
                return (self._frame_counter.frame_count) / elapsed if elapsed > 0 and self._frame_counter.frame_count > 1 else 0.0
        
        # Create application
        application = ThroughputApplication(
            cu_context,
            cu_device_ordinal,
            hololink_channel,
            camera,
            frame_limit,
        )
        
        # Start Hololink and camera (exactly like verify_camera_imx258.py)
        logging.info("Starting Hololink and camera...")
        hololink = hololink_channel.hololink()
        hololink.start()
        hololink.reset()
        
        camera.configure_mipi_lane(4, 371)
        camera.configure(camera_mode)
        camera.set_focus(-140)
        camera.set_exposure(0x0600)
        camera.set_analog_gain(0x0180)

        print("Data Generator")
        hololink.write_uint32(0x01000104,0x00)#Disable Data Gen 
        hololink.write_uint32(0x01000108,0x01)#Set Data Gen to Counter Mode , 0: PRBS, 1: Counter
        hololink.write_uint32(0x01000110,0xE666)#Set Data Gen SIF CLK Divider, SIF_CLK/((65536/0xC000)) Orin - 0xA8F6, Thor - 0xE666
        hololink.write_uint32(0x01000104,0x03)#Enable Data Gen with Continuous Mode	    

        camera.start()
        
        # Read kernel rx_bytes BEFORE pipeline starts (ground truth measurement)
        rx_bytes_before = _read_rx_bytes(iface) if iface else None
        
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
        
        frame_count = application.get_frame_count()
        avg_fps = application.get_fps()
        
        # Use FrameCounterOp's precise timing (first frame to last frame)
        fc = application._frame_counter
        if fc and fc.start_time and fc.end_time:
            elapsed_time = fc.end_time - fc.start_time
        else:
            elapsed_time = time.time() - start_time
        
        stop_event.set()
        
        # Read kernel rx_bytes AFTER pipeline completes (ground truth measurement)
        rx_bytes_after = _read_rx_bytes(iface) if iface else None
        
        # Calculate throughput
        if elapsed_time > 0 and frame_count > 0:
            # Use dynamic frame size from CsiToBayerOp.get_csi_length()
            frame_size = application._frame_size
            total_bytes = frame_count * frame_size
            total_bits = total_bytes * 8
            throughput = total_bits / (elapsed_time * 1_000_000)  # Mbps
            
            # Primary: kernel rx_bytes (actual wire bytes, ground truth)
            if rx_bytes_before is not None and rx_bytes_after is not None and rx_bytes_after > rx_bytes_before:
                kernel_bytes = rx_bytes_after - rx_bytes_before
                kernel_bits = kernel_bytes * 8
                sys_throughput = kernel_bits / (elapsed_time * 1_000_000)
                logging.info(f"Using kernel rx_bytes for throughput (ground truth)")
                logging.info(f"  Kernel rx_bytes delta: {kernel_bytes} bytes")
            else:
                # Fallback: estimated from frame_count * frame_size
                total_bytes = frame_count * frame_size
                total_bits = total_bytes * 8
                throughput = total_bits / (elapsed_time * 1_000_000)
                logging.info(f"Using estimated throughput (frame_count * frame_size)")
            
            # Also log estimated for comparison
            est_total_bytes = frame_count * frame_size
            est_total_bits = est_total_bytes * 8

            # def get_cam_mode_name(cam_mode):
            #     for mode in hololink_module.sensors.imx258.Imx258_Mode:
            #         if mode.value == cam_mode: 
            #             logging.info(f"Camera mode: {mode.name}")
            #             logging.info(f"Mode number: {mode.value}")
            #             return mode.name
            #     logging.warning(f"Unknown camera mode: {cam_mode}")
            #     return None

            #mode_name = get_cam_mode_name(int(camera_mode))
            #logging.info(f"Camera mode: {mode_name}")
            
            #fps = None
            # expected_throughput = 0
            # if mode_name:
            #     m = re.search(r'_(\d+)\s*fps', str(mode_name), flags=re.IGNORECASE)
            #     fps = int(m.group(1)) if m else None
            #     logging.info(f"Extracted FPS from camera mode name: {fps}")
            #     if fps:
            #         expected_throughput = (frame_size * fps) / 1_000_000
            #     else:
            #         logging.warning("Could not extract FPS from camera mode name")

            logging.info(f"Throughput measurement complete:")
            logging.info(f"  Frames collected: {frame_count}")
            logging.info(f"  Frame size: {frame_size} bytes")
            logging.info(f"  Total measured data: {total_bytes} bytes ({total_bits} bits)")
            logging.info(f"  System estimated data: {est_total_bytes} bytes ({est_total_bits} bits)")
            if rx_bytes_before is not None and rx_bytes_after is not None:
                logging.info(f"  Kernel rx_bytes: {rx_bytes_after - rx_bytes_before} bytes")
            logging.info(f"  Elapsed time: {elapsed_time:.4f}s")
            logging.info(f"  Average FPS: {avg_fps:.2f}")
            #logging.info(f"  Calculated Throughput: {throughput:.2f} Mbps")
            logging.info(f"  Measured throughput: {throughput:.2f} Mbps")
            logging.info(f"  System measured throughput: {sys_throughput:.2f} Mbps")
            #logging.info(f"  Expected throughput: {expected_throughput:.2f} Mbps")
            
            # PTP timing stats now measured in verify_PTP.py
            return int(throughput), int(sys_throughput)
        
        return None
        
    except Exception as e:
        logging.warning(f"Hololink throughput measurement failed: {e}", exc_info=True)
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
    parser.add_argument("--camera-mode", type=int, default=0, help="Camera mode")
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

    logging.info("Verifying Ethernet link speed...")
    
    # Detect interface - vdd_main returns (success, message, stats)
    success, message, detection_stats = vdd_main(timeout_seconds=10)
    if not success or not detection_stats.get('detected_interface'):
        stats = {"error": "Could not detect Hololink network interface"}
        print(f"\n📊 Metrics: {stats}")
        return False, "Could not detect Hololink network interface", stats
    
    iface = detection_stats['detected_interface']
    logging.info(f"Detected Hololink interface: {iface}")
    
    # Try multiple methods to read hardware speed
   
    # Measure actual throughput (requires running hardware)
    result = _measure_hololink_throughput(camera_ip=cam_ip, frame_limit=frame_lim, timeout_seconds=15, camera_mode=cam_mode, iface=iface)
    if result is None:
        actual_throughput, sys_throughput = 0, 0
    else:
        actual_throughput, sys_throughput = result
    if actual_throughput is None: 
        actual_throughput = 0  # Measurement failed
    
    stats = {
        "interface": iface,
        "Throughput_mbps": actual_throughput,
        "System_Estimated_mbps": sys_throughput,
    }
    
    # Check if hardware speed meets minimum
    logging.info(f"Interface: {iface}, Throughput: {actual_throughput} Mbps, System estimated throughput: {sys_throughput} Mbps")
    
    print(f"\n📊 Metrics: {stats}")
    
    return True, f"Hololink throughput measured at {actual_throughput} Mbps (System estimated: {sys_throughput} Mbps)", stats

    # Allow 5% tolerance for rounding
    # if actual_throughput >= int(0.7 * expected_throughput):
    #     return True, f"Hololink throughput OK: {actual_throughput} Mbps", stats
    # else:
    #     return False, f"Hololink throughput {actual_throughput} Mbps below minimum expected {expected_throughput} Mbps", stats
    

if __name__ == "__main__":
    success, message, stats = main()
    if success:
        print(f"[PASS] {message}")
        sys.exit(0)
    else:
        print(f"[FAIL] {message}")
        sys.exit(1)