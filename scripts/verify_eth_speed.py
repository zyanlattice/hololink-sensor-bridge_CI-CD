
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


from cuda import cuda, cudart
import holoscan
import hololink as hololink_module
    

# Network speed detection functions from conftest.py
def _read_ethtool_speed(interface: str) -> Optional[int]:
    """Read link speed using ethtool command."""
    try:
        proc = subprocess.run(["ethtool", interface], capture_output=True, text=True, check=False)
        out = (proc.stdout or "") + (proc.stderr or "")
        m = re.search(r"Speed:\s*(\d+)\s*Mb/s", out)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return None

def _read_sysfs_speed(interface: str) -> Optional[int]:
    """Read link speed from sysfs."""
    try:
        speed_path = Path(f"/sys/class/net/{interface}/speed")
        if speed_path.is_file():
            with open(speed_path, "r") as f:
                speed_str = f.read().strip()
                return int(speed_str)
    except Exception:
        pass
    return None


class FrameCounterOp(holoscan.core.Operator):
    """Operator to count received frames and track timestamps (system clock + PTP)."""
    
    def __init__(self, *args, frame_limit=50, app=None, pass_through=False, camera=None, hololink=None, save_images=False, **kwargs):
        self.pass_through = pass_through
        self.frame_limit = frame_limit
        self.frame_count = 0
        self.start_time = None
        self.timestamps = []  # System clock timestamps
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


def _measure_hololink_throughput(camera_ip: str = "192.168.0.2", frame_limit: int = 300, timeout_seconds: int = 15, camera_mode: int = 4 ) -> Tuple[Optional[int], Optional[int]]:
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
        
        cu_result, cu_context = cuda.cuCtxCreate(0, cu_device)
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

                
                # Frame counter as terminal operator (like MonitorOperator in latency.py)
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
        )
        
        # Start Hololink and camera (exactly like verify_camera_imx258.py)
        logging.info("Starting Hololink and camera...")
        hololink = hololink_channel.hololink()
        hololink.start()
        
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
        
        elapsed_time = time.time() - start_time
        frame_count = application.get_frame_count()
        avg_fps = application.get_fps()
        
        stop_event.set()
        
        # Calculate throughput
        if elapsed_time > 0 and frame_count > 0:
            # Frame size: 1920x1080 RAW10 = 1920*1080*10/8 = 2,592,000 bytes
            frame_size = camera._width * camera._height * 10   # RAW10 = 10 bits per pixel
            total_bytes = frame_count * frame_size // 8
            throughput = (total_bytes * 8) / (elapsed_time * 1_000_000)

            def get_cam_mode_name(cam_mode):
                for mode in hololink_module.sensors.imx258.Imx258_Mode:
                    if mode.value == cam_mode: 
                        logging.info(f"Camera mode: {mode.name}")
                        logging.info(f"Mode number: {mode.value}")
                        return mode.name
                logging.warning(f"Unknown camera mode: {cam_mode}")
                return None

            mode_name = get_cam_mode_name(int(camera_mode))
            #logging.info(f"Camera mode: {mode_name}")
            
            fps = None
            expected_throughput = 0
            if mode_name:
                m = re.search(r'_(\d+)\s*fps_', str(mode_name), flags=re.IGNORECASE)
                fps = int(m.group(1)) if m else None
                logging.info(f"Extracted FPS from camera mode name: {fps}")
                if fps:
                    expected_throughput = (frame_size * fps) / 1_000_000
                else:
                    logging.warning("Could not extract FPS from camera mode name")

            logging.info(f"Throughput measurement complete:")
            logging.info(f"  Frames collected: {frame_count}")
            logging.info(f"  Frame size: {frame_size} bytes")
            logging.info(f"  Total data: {total_bytes / 1_000_000:.1f} MB")
            logging.info(f"  Elapsed time: {elapsed_time:.2f}s")
            logging.info(f"  Average FPS: {avg_fps:.2f}")
            logging.info(f"  Calculated throughput: {throughput:.1f} Mbps")
            logging.info(f"  Expected throughput: {expected_throughput:.1f} Mbps")
            
            # PTP timing stats now measured in verify_PTP.py
            return int(throughput), int(expected_throughput)
        
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
    parser.add_argument("--camera-mode", type=int, default=4, help="Camera mode")
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
    
    # Detect interface
    iface = vdd_main(timeout_seconds=10)
    if not iface:
        return False, "Could not detect Hololink network interface", {}
    
    logging.info(f"Detected Hololink interface: {iface}")
    
    # Try multiple methods to read hardware speed
    hw_speed = _read_ethtool_speed(iface)
    if hw_speed is None:
        hw_speed = _read_sysfs_speed(iface)
    
    if hw_speed is None or hw_speed <= 0:
        return False, f"Link speed unavailable for interface '{iface}'", {"interface": iface}
    
    # Measure actual throughput (requires running hardware)
    result = _measure_hololink_throughput(camera_ip=cam_ip, frame_limit=frame_lim, timeout_seconds=15, camera_mode=cam_mode)
    if result is None:
        actual_throughput, expected_throughput = 0, 0
    else:
        actual_throughput, expected_throughput = result
    if actual_throughput is None: 
        actual_throughput = 0  # Measurement failed
    
    stats = {
        "interface": iface,
        "HW_speed": hw_speed,
        "Throughput_mbps": actual_throughput,
        "Expected_mbps": expected_throughput,
    }
    
    # Check if hardware speed meets minimum
    logging.info(f"Interface: {iface}, HW speed: {hw_speed} Throughput: {actual_throughput} Mbps (min: {expected_throughput} Mbps)")
    
    # Allow 5% tolerance for rounding
    if actual_throughput >= int(0.7 * expected_throughput):
        return True, f"Hololink throughput OK: {actual_throughput} Mbps (expected: {expected_throughput} Mbps)", stats
    else:
        return False, f"Hololink throughput {actual_throughput} Mbps below minimum expected {expected_throughput} Mbps", stats
    

if __name__ == "__main__":
    success, message, stats = main()
    if success:
        print(f"[PASS] {message}")
        sys.exit(0)
    else:
        print(f"[FAIL] {message}")
        sys.exit(1)