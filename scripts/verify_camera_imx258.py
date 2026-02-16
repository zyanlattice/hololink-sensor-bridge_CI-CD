#!/usr/bin/env python3
"""
Automated functional verification script for IMX258 camera after bitstream programming.
Runs headless, captures frames, performs basic validation, and exits automatically.
Can be run standalone without pytest.

IMX258_MODE_1920X1080_60FPS = 0
    IMX258_MODE_1920X1080_30FPS = 1
    IMX258_MODE_1920X1080_60FPS_cus = 2
    IMX258_MODE_1920X1080_30FPS_cus = 3
    IMX258_MODE_1920X1080_60FPS_new = 4
    IMX258_MODE_4K_30FPS = 5
    Unknown = -1

"""

import argparse
import ctypes
import logging
import re
import sys
import time
import threading
import os
from typing import Tuple
import numpy as np
import terminal_print_formating as tpf


import holoscan
import cuda.bindings.driver as cuda
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
            
            # Convert Holoscan Tensor (GPU object) → CuPy array (GPU array) → NumPy array (CPU array)
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

class ScreenShotOp(holoscan.core.Operator):
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
        
        from PIL import ImageGrab
        try:
            
            timestamp = time.time()
            filename = os.path.join(self.save_dir, f"frame_{self.current_frame:04d}_{timestamp:.3f}.png")
            
            
            screenshot = ImageGrab.grab()
            screenshot_path = filename
            screenshot.save(screenshot_path)
            logging.info(f"Saved HolovizOp screenshot: {screenshot_path}")

            self.saved_count += 1

        except Exception as e:
            logging.warning(f"Could not capture screenshot: {e}")


class FrameCounterOp(holoscan.core.Operator):
    """Operator to count received frames and track timestamps."""
    
    def __init__(self, *args, frame_limit=50, pass_through=False, **kwargs):
        self.pass_through = pass_through
        self.frame_limit = frame_limit
        self.frame_count = 0
        self.start_time = None
        self.timestamps = []
        self.fps = 0.0
        
        super().__init__(*args, **kwargs)
        
    def setup(self, spec):
        spec.input("input")
        if self.pass_through:
            spec.output("output")
        
    def compute(self, op_input, op_output, context):
        # Check BEFORE incrementing to prevent off-by-one errors
        if self.frame_count >= self.frame_limit:
            # Already at limit - receive frame to unblock pipeline but don't count it
            in_message = op_input.receive("input")
            return
        
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
                
        elapsed = time.time() - self.start_time
        fps = self.frame_count / elapsed if elapsed > 0 else 0

        if self.frame_count % 10 == 0:
            logging.info(f"Frames received: {self.frame_count}, FPS: {fps:.2f}")

        if self.frame_count == self.frame_limit:
            self.fps = self.frame_count / elapsed if elapsed > 0 else 0

        # Frame counting complete - CountCondition will stop graph after frame_limit

    def calculate_frame_gaps(self, expected_fps=60.0):
        """
        Calculate frame gaps/dropped frames based on timestamp analysis.
        
        Args:
            expected_fps: Expected frames per second (default 60)
        
        Returns:
            dict with gap statistics
        """
        if len(self.timestamps) < 2:
            return {
                "max_gap_ms": 0,
                "avg_gap_ms": 0,
                "num_large_gaps": 0,
                "dropped_frames_estimate": 0
            }
        
        expected_interval = 1.0 / expected_fps  # seconds between frames
        
        # Calculate intervals between consecutive frames
        intervals = [self.timestamps[i+1] - self.timestamps[i] 
                    for i in range(len(self.timestamps) - 1)]
        
        # Find gaps (convert to ms for readability)
        gaps_ms = [interval * 1000 for interval in intervals]
        expected_interval_ms = expected_interval * 1000
        
        # Gaps larger than 1.5x expected interval indicate dropped frames
        large_gaps = [g for g in gaps_ms if g > expected_interval_ms * 1.5]
        
        # Estimate dropped frames (gap / expected_interval)
        max_gap = max(gaps_ms) if gaps_ms else 0
        #dropped_estimate = sum((g / expected_interval_ms - 1) for g in large_gaps)
        
        avg_gap = round(sum(gaps_ms) / len(gaps_ms), 2)

        return {
            "max_gap_ms": round(max_gap, 2),
            "avg_gap_ms": avg_gap,
            "expected_interval_ms": round(expected_interval_ms, 2),
            "num_large_gaps": len(large_gaps),
            #"dropped_frames_estimate": int(dropped_estimate),
            "frame_gap_test_result": "pass" if avg_gap <= expected_interval_ms * 1.2 else "fail"    
        }

class VerificationApplication(holoscan.core.Application):
    """Headless application for quick functional verification."""
    
    def __init__(
        self,
        headless,
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
        fullscreen=False,
    ):
        super().__init__()
        self._cuda_context = cuda_context
        self._headless = headless
        self._fullscreen = fullscreen
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
        # Use CountCondition to limit frames (like linux_imx258_player.py)
        # This allows the receiver to stop naturally and GXF graph to complete
        if self._frame_limit:
            self._count = holoscan.conditions.CountCondition(
                self,
                name="count",
                count=self._frame_limit,
            )
            count_condition = self._count
        else:
            # If no frame limit, use a boolean condition for continuous operation
            self._ok = holoscan.conditions.BooleanCondition(
                self, name="ok", enable_tick=True
            )
            count_condition = self._ok
                
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
            count_condition,
            name="receiver",
            frame_size=frame_size,
            frame_context=self._cuda_context,
            hololink_channel=self._hololink_channel,
            device=self._camera
        )
        
        self.add_flow(receiver_operator, csi_to_bayer_operator, {("output", "input")})
        
        if self._save_images and not self._fullscreen:

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
            
            # Simple frame counter for stats only - no stop logic needed
            self._frame_counter = FrameCounterOp(
                self, 
                name="frame_counter",
                frame_limit=self._frame_limit,
                pass_through=True
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
                     

            self.add_flow(csi_to_bayer_operator, image_processor_operator, {("output", "input")})
            self.add_flow(image_processor_operator, bayer_to_rgb_operator, {("output", "receiver")})
            self.add_flow(bayer_to_rgb_operator, self._frame_counter, {("transmitter", "input")})
            self.add_flow(self._frame_counter, self._image_saver, {("output", "input")})

        elif self._fullscreen:
            pixel_format = self._camera.pixel_format()
            bayer_format = self._camera.bayer_format()

            image_processor_operator = hololink_module.operators.ImageProcessorOp(
                self,
                name="image_processor",
                optical_black=50,  # IMX258 optical black value
                bayer_format=bayer_format.value,
                pixel_format=pixel_format.value,
            )

            rgba_components_per_pixel = 4
            rgb_pool = holoscan.resources.BlockMemoryPool(
                self,
                name="rgb_pool",
                storage_type=1,
                block_size=self._camera._width 
                * self._camera._height 
                * rgba_components_per_pixel
                * ctypes.sizeof(ctypes.c_uint16),  # RGA8888
                num_blocks=2,
            )
            
            bayer_to_rgb_operator = BayerDemosaicOp(
                self,
                name="bayer_to_rgb",
                pool=rgb_pool,
                generate_alpha=True,
                alpha_value=65535,
                bayer_grid_pos=bayer_format.value,
                interpolation_mode=0,
            )
            
            self._frame_counter = FrameCounterOp(
                self, 
                name="frame_counter",
                frame_limit=self._frame_limit,
                pass_through=True
            )

            self._image_saver = ScreenShotOp(
                self,
                name="image_saver",
                save_dir=self._save_dir,
                max_saves=self._max_saves,
                frames_to_save=self._frames_to_save,
                app=self,
                camera=self._camera,  # ← Pass camera
                hololink=self._hololink  # ← Pass hololink
            )

            visualizer = holoscan.operators.HolovizOp(
                self,
                name="holoviz",
                fullscreen=self._fullscreen,
                headless=self._headless,
                framebuffer_srgb=True,
            )

            self.add_flow(csi_to_bayer_operator, image_processor_operator, {("output", "input")})
            self.add_flow(image_processor_operator, bayer_to_rgb_operator, {("output", "receiver")})
            self.add_flow(bayer_to_rgb_operator, self._frame_counter, {("transmitter", "input")})
            self.add_flow(self._frame_counter, visualizer, {("output", "receivers")})
            if self._save_images:
                self.add_flow(self._frame_counter, self._image_saver, {("output", "input")})

        else:
            # Simple frame counter for stats only
            self._frame_counter = FrameCounterOp(
                self, 
                name="frame_counter",
                frame_limit=self._frame_limit,
                pass_through=False
            )
            self.add_flow(csi_to_bayer_operator, self._frame_counter, {("output", "input")})

    def get_frame_count(self) -> int:
        return self._frame_counter.frame_count if self._frame_counter else 0
    
    def get_fps(self) -> float:
        if not self._frame_counter or not self._frame_counter.start_time:
            return 0.0
        #elapsed = time.time() - self._frame_counter.start_time
        #return self._frame_counter.frame_count / elapsed if elapsed > 0 else 0.0
        return self._frame_counter.fps
    
    def get_saved_count(self) -> int:
        """Get the number of images saved."""
        return self._image_saver.saved_count if self._image_saver else 0
    
    def get_frame_gap_stats(self, ex_fps=60.0) -> dict:
        """Get frame gap statistics from the frame counter."""
        if not self._frame_counter:
            return {}
        return self._frame_counter.calculate_frame_gaps(expected_fps=ex_fps)
    
    def interrupt(self):
        try:
            if hasattr(super(), 'interrupt'):
                super().interrupt()
        except Exception as e:
            logging.warning(f"Error calling interrupt: {e}")


def verify_camera_functional(
    holoviz: bool = False,
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
        holoviz: Whether to run with holoviz (GUI)
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
        
        cu_result, cu_context = cuda.cuDevicePrimaryCtxRetain(cu_device)
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
        
        headless = not holoviz

        # Create application
        application = VerificationApplication(
            headless,
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
            fullscreen=holoviz,              # Use fullscreen args as flag if holoviz is enabled
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
        
        # Run verification
        logging.info(f"Capturing {frame_limit} frames...")
        start_time = time.time()
        
        def run_app():
            try:
                application.run()  # Will complete naturally when CountCondition reaches frame_limit
            except Exception as e:
                logging.warning(f"Application exception: {e}")
        
        # Run in daemon thread so GXF graph executes
        app_thread = threading.Thread(target=run_app, daemon=True)
        app_thread.start()
        
        # Monitor for completion - the graph will naturally complete when it reaches frame_limit
        poll_interval = 0.1
        first_frame_time = None
        last_frame_time = None
        
        # Wait for application thread to complete (with timeout safety)
        max_wait_time = timeout_seconds + 30  # Extra time for GXF setup + frame capture
        start_wait = time.time()
        
        while app_thread.is_alive():
            time.sleep(poll_interval)
            
            # Track frame timing for timeout monitoring
            frames = application.get_frame_count()
            
            if frames > 0 and first_frame_time is None:
                first_frame_time = time.time()
                logging.info(f"First frame received after {time.time() - start_time:.2f}s")
            
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
                # Thread is stuck - this is the bug we need to fix
                # Continue anyway since we have the frame data we need
        
        elapsed_time = time.time() - start_time
        
        # Collect statistics
        frame_count = application.get_frame_count()
        avg_fps = application.get_fps()
        
        def get_cam_mode_name(cam_mode):
                for mode in hololink_module.sensors.imx258.Imx258_Mode:
                    if mode.value == cam_mode: 
                        logging.info(f"Camera mode: {mode.name}")
                        logging.info(f"Mode number: {mode.value}")
                        return mode.name
                logging.warning(f"Unknown camera mode: {cam_mode}")
                return None

        frame_size = camera._width * camera._height * 10   # RAW10 = 10 bits per pixel
        mode_name = get_cam_mode_name(int(camera_mode))
        expected_fps = 0
        if mode_name:
            m = re.search(r'_(\d+)\s*fps', str(mode_name), flags=re.IGNORECASE)
            expected_fps = int(m.group(1)) if m else None
            logging.info(f"Extracted FPS from camera mode name: {expected_fps}")


        stats = {
            "frame_count": frame_count,
            "elapsed_time": elapsed_time,
            "avg_fps": avg_fps,
            "expected_fps": expected_fps,
            "fps_test_result": (test_result := "pass" if (frame_count >= frame_limit * 0.9 and avg_fps >= expected_fps) else "fail"),
        }
        
        if save_images:
            saved_count = application.get_saved_count()  # Use the new method
            stats["saved_images"] = saved_count
            stats["save_dir"] = save_dir
        
        gap_stats = application.get_frame_gap_stats(ex_fps=60.0)
        stats.update(gap_stats)

        # logging.info("=" * 80)
        # logging.info(f"Verification complete: {frame_count}/{frame_limit} frames received")
        # logging.info(f"Elapsed time: {elapsed_time:.2f}s")
        # logging.info(f"Average FPS: {avg_fps:.2f}")
        # if save_images:
        #     logging.info(f"Saved images: {saved_count}/{max_saves}")
        # logging.info("=" * 80)
        
        # Print to stdout for subprocess capture
        print(f"Average FPS: {avg_fps:.2f}")
        
        # Determine success based on what we captured
        if save_images and saved_count < max_saves:
            return False, f"Insufficient images saved: {saved_count}/{max_saves}", stats
        
        if not save_images and frame_count < frame_limit * 0.9:
            return False, f"Insufficient frames received: {frame_count}/{frame_limit}", stats
        
        if avg_fps < expected_fps and frame_count > 10:  # Only check FPS if we got enough frames
            if gap_stats.get("frame_gap_test_result") == "fail":
                return False, f"FPS too low: {avg_fps:.2f} < {expected_fps} & Frame gap test failed: avg gap {gap_stats.get('avg_gap_ms')}ms >= {gap_stats.get('expected_interval_ms') * 1.2} ({gap_stats.get('expected_interval_ms')} + 20%)", stats
            return False, f"FPS too low: {avg_fps:.2f} < {expected_fps}", stats
        
        if gap_stats.get("frame_gap_test_result") == "fail":
                return False, f"Frame gap test failed: avg gap {gap_stats.get('avg_gap_ms')}ms >= {gap_stats.get('expected_interval_ms') * 1.2}", stats
        return True, "Camera verification passed", stats
        
    except Exception as e:
        logging.error(f"Verification failed with exception: {e}", exc_info=True)
        return False, f"Exception during verification: {str(e)}", {}
    
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
                # At this point hololink socket is closed, so receiver will eventually error
                # But we can't wait forever
        
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
        
        logging.info("Cleanup complete")



def main() -> bool:
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
    parser.add_argument("--list-mode", action="store_true", help="List available camera modes and exit")
    parser.add_argument("--holoviz", action="store_true", help="Run with holoviz (GUI)")
    
    args = parser.parse_args()
    
    # If listing modes, do that and exit
    if args.list_mode:
        print("Available IMX258 Camera Modes:")
        for mode in hololink_module.sensors.imx258.Imx258_Mode:
            print(f"  {mode.value}: {mode.name}")
        sys.exit(0)

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
    
    # Verify camera
    cam_success, cam_message, cam_stats = verify_camera_functional(
        holoviz=args.holoviz,
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
    
    
    # Print summary
    print(tpf.header_footer(90, "CAMERA VERIFICATION SUMMARY"))
    
    for test_name, success, message, stats in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"\n{status}: {test_name}")
        print(f"  {message}")
        if stats:
            for key, value in stats.items():
                print(f"  {key}: {value}")
    
    # Print metrics in capture-friendly format for pytest
    print(f"\n📊 Metrics: {cam_stats}")

    print("\n" + "=" * 90)
    if cam_success:
        print(" Camera verification PASSED")
        return cam_success, cam_message, cam_stats
    else:
        print(" TESTS FAILED")
        print(" camera_ok:", cam_success)
        return cam_success, cam_message, cam_stats

    return cam_success

if __name__ == "__main__":
    success, message, stats = main()
    if success:
        print(f"[PASS] {message}")
        sys.exit(0)
    else:
        print(f"[FAIL] {message}")
        sys.exit(1)