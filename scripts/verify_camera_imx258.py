#!/usr/bin/env python3
"""
Automated functional verification script for IMX258 camera after bitstream programming.
Runs headless, captures frames, performs basic validation, and exits automatically.
Can be run standalone without pytest.
"""

import argparse
import ctypes
import logging
import sys
import time
import threading
import os
import re
import subprocess
from datetime import timedelta
from typing import Tuple, Optional
import numpy as np
import terminal_print_formating as tpf


import holoscan
from cuda import cuda, cudart
from holoscan.operators import BayerDemosaicOp
from holoscan.resources import UnboundedAllocator

import hololink as hololink_module


class TimeoutError(Exception):
    """Raised when verification times out."""
    pass


class ImageSaverOp(holoscan.core.Operator):
    """Operator to save frames as images."""
    
    def __init__(self, *args, save_dir="/tmp/camera_verification", max_saves=5, frames_to_save=None, app=None, camera=None, hololink=None, save_images=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.save_dir = save_dir
        self.max_saves = max_saves
        self.saved_count = 0
        self.frames_to_save = frames_to_save or []  # List of frame numbers to save
        self.current_frame = 0  # Track which frame we're on
        self.app = app
        self.camera = camera  # ← Add camera reference
        self.hololink = hololink  # ← Add hololink reference
        self.save_images = save_images
        os.makedirs(save_dir, exist_ok=True)
        
    def setup(self, spec):
        spec.input("input")
        
    def compute(self, op_input, op_output, context):
        in_message = op_input.receive("input")
        self.current_frame += 1
        
        # Check if this frame should be saved
        if self.current_frame not in self.frames_to_save:
            return  # Don't save this frame
        
        if self.saved_count >= self.max_saves:
            return  # Already saved enough
        
        try:
            import cupy as cp
            
            tensor = in_message.get("")
            
            # Convert Holoscan Tensor → CuPy array (GPU) → NumPy array (CPU)
            cuda_array = cp.asarray(tensor)
            host_array = cp.asnumpy(cuda_array)
            
            timestamp = time.time()
            filename = os.path.join(self.save_dir, f"frame_{self.current_frame:04d}_{timestamp:.3f}.npy")
            
            # Save .npy file
            np.save(filename, host_array)
                        
            logging.info(f"  Saved frame {self.saved_count + 1}/{self.max_saves}: {filename}")
            logging.info(f"  Shape: {host_array.shape}, dtype: {host_array.dtype}, "
                        f"min: {host_array.min()}, max: {host_array.max()}")
            
            # Save PNG preview
            try:
                from PIL import Image
                png_filename = filename.replace('.npy', '.png')
                
                # Normalize to 8-bit - PROPERLY handle the dynamic range
                if host_array.dtype == np.uint16:
                    # Find actual min/max for proper normalization
                    arr_min = host_array.min()
                    arr_max = host_array.max()
                    
                    # Normalize to 0-255 range
                    if arr_max > arr_min:
                        normalized = ((host_array.astype(np.float32) - arr_min) / (arr_max - arr_min) * 255)
                        img_8bit = normalized.astype(np.uint8)
                    else:
                        img_8bit = np.zeros_like(host_array, dtype=np.uint8)
                    
                    logging.info(f"  Normalized from [{arr_min}, {arr_max}] to [0, 255]")
                    
                elif np.issubdtype(host_array.dtype, np.floating):
                    img_8bit = (np.clip(host_array, 0, 1) * 255).astype(np.uint8)
                else:
                    img_8bit = host_array.astype(np.uint8)
                
                # Handle RGB/RGBA
                if len(img_8bit.shape) == 3:
                    if img_8bit.shape[2] == 4:
                        img_8bit = img_8bit[:, :, :3]  # Drop alpha
                    img = Image.fromarray(img_8bit, mode='RGB')
                else:
                    img = Image.fromarray(img_8bit, mode='L')  # Grayscale
                
                
                img.save(png_filename)
                logging.info(f"  Saved PNG: {png_filename}")

            except Exception as e:
                logging.warning(f"  Could not save PNG: {e}")
                
            self.saved_count += 1

        except Exception as e:
            logging.error(f"Failed to save frame: {e}", exc_info=True)

class FrameCounterOp(holoscan.core.Operator):
    """Operator to count received frames and track timestamps."""
    
    def __init__(self, *args, frame_limit=50, app=None, pass_through=False, camera=None, hololink=None, save_images=False, **kwargs):
        self.pass_through = pass_through
        self.frame_limit = frame_limit
        self.frame_count = 0
        self.start_time = None
        self.timestamps = []
        self.app = app
        self.camera = camera  # ← Add camera reference
        self.hololink = hololink  # ← Add hololink reference
        self.save_images = save_images
        
        super().__init__(*args, **kwargs)
        
    def setup(self, spec):
        spec.input("input")
        if self.pass_through:
            spec.output("output")
        
    def compute(self, op_input, op_output, context):
        if self.start_time is None:
            self.start_time = time.time()
        
        self.frame_count += 1
        self.timestamps.append(time.time())
        
        # Pass through only if needed
        if self.pass_through:
            in_message = op_input.receive("input")
            op_output.emit(in_message, "output")
        else:
            in_message = op_input.receive("input")
        
        if self.frame_count % 10 == 0:
            elapsed = time.time() - self.start_time
            fps = self.frame_count / elapsed if elapsed > 0 else 0
            logging.info(f"Frames received: {self.frame_count}, FPS: {fps:.2f}")

        # CRITICAL: Stop the application when we reach frame_limit
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
                    
                    if self.app:
                        try:
                            self.app.interrupt()
                        except Exception as e:
                            logging.warning(f"Error interrupting app: {e}")

                threading.Thread(target=stop_everything, daemon=True).start()

class VerificationApplication(holoscan.core.Application):
    """Headless application for quick functional verification."""
    
    def __init__(
        self,
        cuda_context,
        cuda_device_ordinal,
        hololink_channel,
        camera,
        camera_mode,
        frame_limit,
        hololink=None,
        save_images=False,
        save_dir="/tmp/camera_verification",
        max_saves=5,
        frames_to_save=None,
    ):
        super().__init__()
        self._cuda_context = cuda_context
        self._cuda_device_ordinal = cuda_device_ordinal
        self._hololink_channel = hololink_channel
        self._camera = camera
        self._hololink = hololink
        self._camera_mode = camera_mode
        self._frame_limit = frame_limit
        self._save_images = save_images
        self._save_dir = save_dir
        self._max_saves = max_saves
        self._frames_to_save = frames_to_save or []
        self._frame_counter = None
        self._image_saver = None

    def compose(self):
                
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
        
        # Pass CountCondition to receiver - IT STOPS AFTER frame_limit FRAMES
        receiver_operator = hololink_module.operators.LinuxReceiverOperator(
            self,
            name="receiver",
            frame_size=frame_size,
            frame_context=self._cuda_context,
            hololink_channel=self._hololink_channel,
            device=self._camera
        )
        
        self.add_flow(receiver_operator, csi_to_bayer_operator, {("output", "input")})
        
        if self._save_images:

            pixel_format = self._camera.pixel_format()
            bayer_format = self._camera.bayer_format()

            image_processor_operator = hololink_module.operators.ImageProcessorOp(
                self,
                name="image_processor",
                optical_black=50,  # IMX258 optical black value
                bayer_format=bayer_format.value,
                pixel_format=pixel_format.value,
            )

            rgb_pool = holoscan.resources.BlockMemoryPool(
                self,
                name="rgb_pool",
                storage_type=1,
                block_size=self._camera._width * self._camera._height * 6,  # RGB888
                num_blocks=2,
            )
            
            bayer_to_rgb_operator = BayerDemosaicOp(
                self,
                name="bayer_to_rgb",
                pool=rgb_pool,
                generate_alpha=False,
                bayer_grid_pos=bayer_format.value,
                interpolation_mode=0,
            )
            
            self._image_saver = ImageSaverOp(
                self,
                name="image_saver",
                save_dir=self._save_dir,
                max_saves=self._max_saves,
                frames_to_save=self._frames_to_save,
                app=self,
                camera=self._camera,  # ← Pass camera
                hololink=self._hololink  # ← Pass hololink
            )
            
            # Simple frame counter for stats only - no stop logic needed
            self._frame_counter = FrameCounterOp(
                self, 
                name="frame_counter",
                frame_limit=self._frame_limit,
                app=self,
                camera=self._camera,  # ← Pass camera
                hololink=self._hololink,  # ← Pass hololink  
                save_images=self._save_images,
                pass_through=True
            )
            
            self.add_flow(csi_to_bayer_operator, image_processor_operator, {("output", "input")})
            self.add_flow(image_processor_operator, bayer_to_rgb_operator, {("output", "receiver")})
            self.add_flow(bayer_to_rgb_operator, self._frame_counter, {("transmitter", "input")})
            self.add_flow(self._frame_counter, self._image_saver, {("output", "input")})
        else:
            # Simple frame counter for stats only
            self._frame_counter = FrameCounterOp(
                self, 
                name="frame_counter",
                frame_limit=self._frame_limit,
                app=self, 
                camera=self._camera,  # ← Pass camera
                hololink=self._hololink,  # ← Pass hololink
                save_images=self._save_images,
                pass_through=False
            )
            self.add_flow(csi_to_bayer_operator, self._frame_counter, {("output", "input")})

    def get_frame_count(self) -> int:
        return self._frame_counter.frame_count if self._frame_counter else 0
    
    def get_fps(self) -> float:
        if not self._frame_counter or not self._frame_counter.start_time:
            return 0.0
        elapsed = time.time() - self._frame_counter.start_time
        return self._frame_counter.frame_count / elapsed if elapsed > 0 else 0.0
    
    def get_saved_count(self) -> int:
        """Get the number of images saved."""
        return self._image_saver.saved_count if self._image_saver else 0
    
    def interrupt(self):
        try:
            if hasattr(super(), 'interrupt'):
                super().interrupt()
        except Exception as e:
            logging.warning(f"Error calling interrupt: {e}")

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
        path = f"/sys/class/net/{interface}/speed"
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                s = f.read().strip()
                if s and s.isdigit():
                    return int(s)
    except Exception:
        pass
    return None


def _read_psutil_speed(interface: str) -> Optional[int]:
    """Read link speed using psutil."""
    try:
        import psutil
        stats = psutil.net_if_stats()
        info = stats.get(interface)
        if info and info.isup and info.speed:
            return int(info.speed)
    except Exception:
        pass
    return None


def _detect_interface_from_hololink(timeout_seconds: int = 10) -> Optional[str]:
    """Detect network interface connected to Hololink device."""
    try:
        devices = {}
        def on_meta(m):
            sn = m.get("serial_number")
            if sn and sn not in devices:
                devices[sn] = m
            return True
        hololink_module.Enumerator().enumerated(on_meta, hololink_module.Timeout(timeout_seconds))
        for _sn, meta in devices.items():
            iface = meta.get("interface") or meta.get("interface_name")
            if isinstance(iface, str) and iface:
                return iface
    except Exception:
        pass
    return None


def verify_ethernet_link_speed(min_mbps: int = 1000) -> Tuple[bool, str, dict]:
    """
    Verify that the Ethernet link speed meets minimum requirements.
    
    Args:
        min_mbps: Minimum expected link speed in Mbps
        
    Returns:
        Tuple of (success: bool, message: str, stats: dict)
    """
    logging.info("Verifying Ethernet link speed...")
    
    # Detect interface
    iface = _detect_interface_from_hololink(timeout_seconds=10)
    if not iface:
        return False, "Could not detect Hololink network interface", {}
    
    logging.info(f"Detected Hololink interface: {iface}")
    
    # Try multiple methods to read speed
    speed = _read_psutil_speed(iface)
    if speed is None:
        speed = _read_ethtool_speed(iface)
    if speed is None:
        speed = _read_sysfs_speed(iface)
    
    if speed is None or speed <= 0:
        return False, f"Link speed unavailable for interface '{iface}'", {"interface": iface}
    
    stats = {
        "interface": iface,
        "speed_mbps": speed,
        "min_expected_mbps": min_mbps,
    }
    
    logging.info(f"Interface: {iface}, Link speed: {speed} Mbps (min: {min_mbps} Mbps)")
    
    # Allow 5% tolerance for rounding
    if speed >= int(0.95 * min_mbps):
        return True, f"Link speed OK: {speed} Mbps", stats
    else:
        return False, f"Link speed {speed} Mbps below minimum {min_mbps} Mbps", stats


def verify_camera_functional(
    camera_ip: str = "192.168.0.2",
    camera_id: int = 0,
    camera_mode: int = 0,
    frame_limit: int = 50,
    timeout_seconds: int = 10,
    min_fps: float = 10.0,
    log_level: int = logging.INFO,
    save_images: bool = False,
    save_dir: str = "/tmp/camera_verification",
    max_saves: int = 5,
) -> Tuple[bool, str, dict]:
    """
    Verify camera functionality after bitstream programming.
    
    Args:
        camera_ip: IP address of the Hololink device
        camera_id: Camera index (0 or 1)
        camera_mode: Camera mode (see Imx258_Mode enum)
        frame_limit: Number of frames to capture
        timeout_seconds: Maximum time to wait for frames
        min_fps: Minimum acceptable FPS
        log_level: Logging level
        save_images: Whether to save captured frames as images
        save_dir: Directory to save images
        max_saves: Maximum number of images to save
        
    Returns:
        Tuple of (success: bool, message: str, stats: dict)
    """
    
    # Calculate which frames to save (evenly distributed)
    def _compute_img_fac(frame_limit: int, max_saves: int) -> list:
        """Compute which frame numbers to save, evenly distributed."""
        if max_saves <= 0 or frame_limit <= 0:
            return []
        interval = frame_limit / max_saves
        return [int((i + 1) * interval) for i in range(max_saves)]
    
    frames_to_save = _compute_img_fac(frame_limit, max_saves) if save_images else []
    logging.info(f"Frames to save: {frames_to_save}")  # Debug

    hololink_module.logging_level(log_level)
    
    logging.info("=" * 80)
    logging.info("Starting IMX258 Camera Functional Verification")
    logging.info(f"Camera IP: {camera_ip}, Camera ID: {camera_id}, Mode: {camera_mode}")
    logging.info(f"Frame limit: {frame_limit}, Timeout: {timeout_seconds}s")
    if save_images:
        logging.info(f"Image saving: ENABLED (max {max_saves} images to {save_dir})")
    logging.info("=" * 80)
    
    hololink = None
    camera = None
    cu_context = None
    application = None
    stop_event = threading.Event()
    
    def timeout_thread():
        if stop_event.wait(timeout_seconds):
            return
        logging.error(f"Timeout after {timeout_seconds} seconds")
        if application:
            application.interrupt()
    
    try:
        # Initialize CUDA
        logging.info("Initializing CUDA...")
        (cu_result,) = cuda.cuInit(0)
        if cu_result != cuda.CUresult.CUDA_SUCCESS:
            return False, f"CUDA initialization failed: {cu_result}", {}
        
        cu_device_ordinal = 0
        cu_result, cu_device = cuda.cuDeviceGet(cu_device_ordinal)
        if cu_result != cuda.CUresult.CUDA_SUCCESS:
            return False, f"Failed to get CUDA device: {cu_result}", {}
        
        cu_result, cu_context = cuda.cuCtxCreate(0, cu_device)
        if cu_result != cuda.CUresult.CUDA_SUCCESS:
            return False, f"Failed to create CUDA context: {cu_result}", {}
        
        logging.info("CUDA initialized successfully")
        
        # Find Hololink channel
        logging.info(f"Searching for Hololink device at {camera_ip}...")
        channel_metadata = hololink_module.Enumerator.find_channel(channel_ip=camera_ip)
        if not channel_metadata:
            return False, f"Failed to find Hololink device at {camera_ip}", {}
        
        logging.info("Hololink device found")
        
        # Initialize camera
        hololink_channel = hololink_module.DataChannel(channel_metadata)
        camera = hololink_module.sensors.imx258.Imx258(hololink_channel, camera_id)
        camera_mode_enum = hololink_module.sensors.imx258.Imx258_Mode(camera_mode)
        
        # Create application
        application = VerificationApplication(
            cu_context,
            cu_device_ordinal,
            hololink_channel,
            camera,
            camera_mode_enum,
            frame_limit,
            hololink=None,
            save_images=save_images,
            save_dir=save_dir,
            max_saves=max_saves,
            frames_to_save=frames_to_save,
        )
        
        # Start Hololink and camera
        logging.info("Starting Hololink and camera...")
        hololink = hololink_channel.hololink()
        hololink.start()
        application._hololink = hololink  # ← Set hololink reference
        
        
        camera.configure(camera_mode_enum)
        version = camera.get_version()
        logging.info(f"Camera version: {version}")
        
        # Set focus
        camera.set_focus(-140)
        
        # Increase brightness: boost exposure and gain
        # Exposure: 0x0600 (1536 lines, up from default 0x0438=1080)
        # Analog gain: 0x0180 (384 = 1.5x gain = 3.5dB, up from default 0x0100=256)
        # 
        # Brightness adjustment guide:
        # - Too dark: Increase exposure (0x0700, 0x0800) or gain (0x0200=2x, 0x0300=3x)
        # - Too bright: Decrease exposure (0x0400, 0x0300) or gain (0x0080=0.5x)
        # - Prefer exposure over gain for better image quality (less noise)
        camera.set_exposure(0x0600)
        camera.set_analog_gain(0x0180)
        logging.info("Applied exposure=0x0600 and analog_gain=0x0180 for better brightness")
        
        camera.start()
        
        # Start timeout thread
        timeout_t = threading.Thread(target=timeout_thread, daemon=True)
        timeout_t.start()
        
        # Run verification
        logging.info(f"Capturing {frame_limit} frames...")
        start_time = time.time()
        
        # Flag to track if we should force shutdown
        force_shutdown = threading.Event()
        
        def run_app():
            try:
                application.run()
            except Exception as e:
                logging.warning(f"Application exception: {e}")
        
        # Run in daemon thread so we can kill it
        app_thread = threading.Thread(target=run_app, daemon=True)
        app_thread.start()
        
        # Monitor for completion
        max_wait = timeout_seconds + 3  # Add grace period
        
        # Wait for either:
        # 1. App completes naturally (unlikely with our blocking receiver)
        # 2. Timeout expires
        # 3. We detect we've saved enough images
        
        poll_interval = 0.1
        waited = 0
        
        while app_thread.is_alive() and waited < max_wait:
            time.sleep(poll_interval)
            waited += poll_interval
            
            # Check if we've received/saved enough
            if save_images:
                saved = application.get_saved_count()
                if saved >= max_saves:
                    logging.info(f"Saved {saved}/{max_saves} images, forcing shutdown...")
                    force_shutdown.set()
                    break
            else:
                frames = application.get_frame_count()
                if frames >= frame_limit:
                    logging.info(f"Received {frames}/{frame_limit} frames, forcing shutdown...")
                    force_shutdown.set()
                    break
        
        # If we hit timeout or saved enough, force exit
        if force_shutdown.is_set() or waited >= max_wait:
            logging.info("Forcing application shutdown, daemon thread will be terminated - waiting for GXF to deactivate gracefully...")
            
            if app_thread.is_alive():
                logging.warning("Application still running after 5s grace period, exiting anyway")
        else:
            # App completed naturally (unlikely)
            app_thread.join(timeout=1.0)
        
        elapsed_time = time.time() - start_time
        
        stop_event.set()
        
        # Collect statistics
        frame_count = application.get_frame_count()
        avg_fps = application.get_fps()
        
        stats = {
            "frame_count": frame_count,
            "elapsed_time": elapsed_time,
            "avg_fps": avg_fps,
            "camera_version": version,
        }
        
        if save_images:
            saved_count = application.get_saved_count()  # Use the new method
            stats["saved_images"] = saved_count
            stats["save_dir"] = save_dir
        
        logging.info("=" * 80)
        logging.info(f"Verification complete: {frame_count}/{frame_limit} frames received")
        logging.info(f"Elapsed time: {elapsed_time:.2f}s")
        logging.info(f"Average FPS: {avg_fps:.2f}")
        if save_images:
            logging.info(f"Saved images: {saved_count}/{max_saves}")
        logging.info("=" * 80)
        
        # Determine success based on what we captured
        if save_images and saved_count < max_saves:
            return False, f"Insufficient images saved: {saved_count}/{max_saves}", stats
        
        if not save_images and frame_count < frame_limit * 0.9:
            return False, f"Insufficient frames received: {frame_count}/{frame_limit}", stats
        
        if avg_fps < min_fps and frame_count > 10:  # Only check FPS if we got enough frames
            return False, f"FPS too low: {avg_fps:.2f} < {min_fps}", stats
        
        return True, "Camera verification passed", stats
        
    except Exception as e:
        logging.error(f"Verification failed with exception: {e}", exc_info=True)
        return False, f"Exception during verification: {str(e)}", {}
    
    finally:
        stop_event.set()
        
        # Cleanup - these may already be stopped from the monitoring loop above
        if camera:
            try:
                logging.info("Final cleanup - ensuring camera is stopped...")
                camera.stop()
            except Exception:
                # Already stopped, ignore
                pass
        
        if hololink:
            try:
                logging.info("Ensuring Hololink is stopped...")
                hololink.stop()
            except Exception:
                # Already stopped, ignore
                pass
        

        if cu_context:
            try:
                logging.info("Destroying CUDA context...")
                cuda.cuCtxDestroy(cu_context)
            except Exception as e:
                logging.warning(f"Error destroying CUDA context: {e}")
        
        logging.info("Cleanup complete")



def main() -> tuple[bool, bool]:
    parser = argparse.ArgumentParser(description="Verify IMX258 camera functionality")
    parser.add_argument("--camera-ip", type=str, default="192.168.0.2", help="Hololink device IP")
    parser.add_argument("--camera-id", type=int, default=0, choices=[0, 1], help="Camera index")
    parser.add_argument("--camera-mode", type=int, default=0, help="Camera mode")
    parser.add_argument("--frame-limit", type=int, default=300, help="Number of frames to capture")
    parser.add_argument("--timeout", type=int, default=10, help="Timeout in seconds")
    parser.add_argument("--min-fps", type=float, default=30.0, help="Minimum acceptable FPS")
    parser.add_argument("--log-level", type=int, default=logging.INFO, help="Logging level")
    parser.add_argument("--save-images", action="store_true", default=False, help="Save captured frames as images")
    parser.add_argument("--save-dir", type=str, default="/home/lattice/HSB/CI_CD/test_image_folder", help="Directory to save images")
    parser.add_argument("--max-saves", type=int, default=1, help="Maximum number of images to save")
    parser.add_argument("--min-eth-speed", type=int, default=10000, help="Minimum Ethernet speed in Mbps")
    
    args = parser.parse_args()
    
    if args.max_saves > args.frame_limit:
        logging.error(f"Max_saves {args.max_saves} cannot be greater than frame_limit {args.frame_limit}!")
        sys.exit(2)

    # Setup logging
    logging.basicConfig(
        level=args.log_level,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    all_passed = True
    results = []
    
    # Always check Ethernet speed
    eth_success, eth_message, eth_stats = verify_ethernet_link_speed(args.min_eth_speed)
    results.append(("Ethernet Link Speed", eth_success, eth_message, eth_stats))
    all_passed = all_passed and eth_success
    
    # Verify camera
    cam_success, cam_message, cam_stats = verify_camera_functional(
        camera_ip=args.camera_ip,
        camera_id=args.camera_id,
        camera_mode=args.camera_mode,
        frame_limit=args.frame_limit,
        timeout_seconds=args.timeout,
        min_fps=args.min_fps,
        log_level=args.log_level,
        save_images=args.save_images,
        save_dir=args.save_dir,
        max_saves=args.max_saves,
    )
    results.append(("Camera Functionality", cam_success, cam_message, cam_stats))
    all_passed = all_passed and cam_success
    
    # Print summary
    print(tpf.header_footer(90, "CAMERA VERIFICATION SUMMARY"))
    
    for test_name, success, message, stats in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"\n{status}: {test_name}")
        print(f"  {message}")
        if stats:
            for key, value in stats.items():
                print(f"  {key}: {value}")
    

    print("\n" + "=" * 90)
    if all_passed:
        print(" ALL TESTS PASSED")
        #sys.exit(0)
    else:
        print(" TESTS FAILED")
        print(" camera_ok:", cam_success, "ethernet_ok:", eth_success)
        #sys.exit(1)
    print("\n" + "=" * 90)

    return eth_success, cam_success

if __name__ == "__main__":
    main()