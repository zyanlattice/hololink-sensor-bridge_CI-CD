#!/usr/bin/env python3
"""
Test pattern validation script for IMX258 camera.

Captures a test pattern frame (color bar) and compares it bit-by-bit 
against a golden reference image stored in CI_CD/images/.

Hardcoded test parameters:
- 300 frames captured (saves frame 150)
- Test pattern mode enabled (color bar)
- Headless operation (no GUI)
- Camera ID: 0
- MIPI lanes: 4, rate: 371 Mbps

Usage:
    python verify_test_pattern_imx258.py --camera-ip 192.168.0.2 --camera-mode 0

IMX258 Modes:
    0: 1920x1080 @ 60fps
    1: 1920x1080 @ 30fps
    2: 1920x1080 @ 60fps (custom)
    3: 1920x1080 @ 30fps (custom)
    4: 1920x1080 @ 60fps (new)
    5: 4K @ 30fps
"""

import argparse
import ctypes
import logging
import math
import re
import sys
import time
import threading
import os
from typing import Tuple
from pathlib import Path
import numpy as np
import terminal_print_formating as tpf


import holoscan
import cuda.bindings.driver as cuda
from holoscan.operators import BayerDemosaicOp
from holoscan.resources import UnboundedAllocator

import hololink as hololink_module


def _find_project_root() -> Path:
    """
    Find the project root directory (where CI_CD/ should be created).
    
    Walks up from the script location looking for workspace markers:
    - cicd_host/ directory
    - Pytest/ directory  
    - .git directory
    Or stops at a directory named 'CI_CD' and returns its parent.
    
    Returns the parent directory where CI_CD/ should be created.
    """
    current = Path(__file__).resolve().parent
    
    # Walk up the directory tree
    for parent in [current] + list(current.parents):
        # If we're inside CI_CD already, return its parent to avoid CI_CD/CI_CD/
        if parent.name == "CI_CD":
            return parent.parent
            
        # Look for workspace markers that indicate the root
        if any([
            (parent / "cicd_host").exists(),
            (parent / "Pytest").exists(),
            (parent / ".git").exists(),
        ]):
            return parent
    
    # Fallback: parent of scripts directory
    return current.parent if current.name == "scripts" else current


# Default save directory: [project_root]/CI_CD/tmp_img_folder
_PROJECT_ROOT = _find_project_root()
DEFAULT_SAVE_DIR = str(_PROJECT_ROOT / "CI_CD" / "tmp_img_folder")


class TimeoutError(Exception):
    """Raised when verification times out."""
    pass

class ImageSaverOp(holoscan.core.Operator):
    """Operator to save frames as .npy and .png files."""
    
    def __init__(self, *args, save_dir=None, max_saves=1, frames_to_save=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.save_dir = save_dir or DEFAULT_SAVE_DIR
        self.max_saves = max_saves
        self.saved_count = 0
        self.frames_to_save = frames_to_save or []
        self.current_frame = 0
        os.makedirs(self.save_dir, exist_ok=True)
        
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
                
                # PIL automatically handles RGB/RGBA based on array shape
                img = Image.fromarray(img_8bit)
                
                
                img.save(png_filename)
                logging.info(f"  Saved PNG: {png_filename}")

            except Exception as e:
                logging.warning(f"  Could not save PNG: {e}")

            
            self.saved_count += 1

        except Exception as e:
            logging.error(f"Failed to save frame: {e}", exc_info=True)

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
    """Headless application for test pattern validation."""
    
    def __init__(
        self,
        cuda_context,
        cuda_device_ordinal,
        hololink_channel,
        camera,
        camera_mode,
        frame_limit,
        hololink=None,
        save_dir=None,
        max_saves=1,
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
        self._save_dir = save_dir or DEFAULT_SAVE_DIR
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
        
        # Image processing pipeline (always enabled for test pattern validation)
        pixel_format = self._camera.pixel_format()
        bayer_format = self._camera.bayer_format()

        image_processor_operator = hololink_module.operators.ImageProcessorOp(
            self,
            name="image_processor",
            optical_black=50,  # IMX258 optical black value
            bayer_format=bayer_format.value,
            pixel_format=pixel_format.value,
        )

        # RGBA pool for HolovizOp display
        rgba_components_per_pixel = 4
        rgb_pool = holoscan.resources.BlockMemoryPool(
            self,
            name="rgb_pool",
            storage_type=1,
            block_size=self._camera._width 
            * self._camera._height 
            * rgba_components_per_pixel
            * ctypes.sizeof(ctypes.c_uint16),  # RGBA8888
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
        
        # Frame counter for statistics
        self._frame_counter = FrameCounterOp(
            self, 
            name="frame_counter",
            frame_limit=self._frame_limit,
            pass_through=True
        )
        
        # HolovizOp for fullscreen display
        visualizer = holoscan.operators.HolovizOp(
            self,
            name="holoviz",
            fullscreen=True,
            headless=False,
            framebuffer_srgb=True,
        )
        
        # Image saver for capturing test pattern
        self._image_saver = ImageSaverOp(
            self,
            name="image_saver",
            save_dir=self._save_dir,
            max_saves=self._max_saves,
            frames_to_save=self._frames_to_save,
        )
        
        # Connect the pipeline: CSI → ImageProcessor → BayerDemosaic → FrameCounter → HolovizOp + ImageSaver
        self.add_flow(csi_to_bayer_operator, image_processor_operator, {("output", "input")})
        self.add_flow(image_processor_operator, bayer_to_rgb_operator, {("output", "receiver")})
        self.add_flow(bayer_to_rgb_operator, self._frame_counter, {("transmitter", "input")})
        self.add_flow(self._frame_counter, visualizer, {("output", "receivers")})
        self.add_flow(self._frame_counter, self._image_saver, {("output", "input")})

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
    camera_ip: str = "192.168.0.2",
    camera_mode: int = 0,
    tp_mode: str = "bar",
    log_level: int = logging.INFO,
) -> Tuple[bool, str, dict]:
    """
    Verify IMX258 test pattern against golden reference.
    
    Hardcoded test parameters:
    - camera_id: 0
    - frame_limit: 100
    - max_saves: 1 (only saves one frame for comparison)
    - test_frame: True (always uses color bar test pattern)
    - holoviz: False (headless)
    - save_images: True
    - timeout: 15 seconds
    
    Args:
        camera_ip: IP address of the Hololink device
        camera_mode: Camera mode (see Imx258_Mode enum)
        log_level: Logging level
    
    Returns:
        Tuple of (success: bool, message: str, stats: dict)
    """
    
    # Hardcoded test pattern parameters
    camera_id = 0
    frame_limit = 100
    max_saves = 1
    timeout_seconds = 15
    lane_num = 4
    lane_rate = 371
    save_dir = DEFAULT_SAVE_DIR
    
    # Calculate which frames to save (evenly distributed)
    def _compute_img_fac(frame_limit: int, max_saves: int) -> list:
        """Compute which frame numbers to save, evenly distributed."""
        if max_saves <= 0 or frame_limit <= 0:
            return []
        interval = math.floor(frame_limit / (max_saves + 1))
        return [int((i+1) * interval) for i in range(max_saves)]
    
    frames_to_save = _compute_img_fac(frame_limit, max_saves)
    logging.info(f"Frames to save: {frames_to_save}")

    hololink_module.logging_level(log_level)
    
    logging.info("=" * 80)
    logging.info(f"Starting IMX258 Test Pattern Validation")
    logging.info(f"Camera IP: {camera_ip}, Camera ID: {camera_id}, Mode: {camera_mode}")
    logging.info(f"Frame limit: {frame_limit}, Timeout: {timeout_seconds}s")
    logging.info(f"Test pattern: ENABLED (color bar)")
    logging.info(f"Image saving: {save_dir}")
    logging.info(f"Golden reference: {_PROJECT_ROOT / 'CI_CD' / 'images' / 'golden_color_bar_imx258.npy'}")
    logging.info("=" * 80)
    
    # Create save directory early to catch permission/path errors before camera setup
    try:
        os.makedirs(save_dir, exist_ok=True)
        logging.info(f"Created/verified save directory: {save_dir}")
    except Exception as e:
        return False, f"Failed to create save directory '{save_dir}': {str(e)}", {}
    
    hololink = None
    camera = None
    cu_context = None
    application = None
    app_thread = None
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
        
        # Initialize IMX258 camera
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
            save_dir=save_dir,
            max_saves=max_saves,
            frames_to_save=frames_to_save,
        )
        
        # Start Hololink and camera
        logging.info("Starting Hololink and camera...")
        hololink = hololink_channel.hololink()
        hololink.start()
        hololink.reset()

        application._hololink = hololink  # ← Set hololink reference
        
        reg602, reg603, reg604, reg605, reg606, reg607, reg608, reg609 = 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00  # Default to 0

        if tp_mode == "bar":
            reg601 = 0x03
        elif tp_mode == "red":
            reg601 = 0x01
            reg602, reg603 = 0x03, 0xFF
            reg604, reg605 = 0x00, 0x00
            reg606, reg607 = 0x00, 0x00
            reg608, reg609 = 0x00, 0x00
        elif tp_mode == "orange":
            reg601 = 0x01
            reg602, reg603 = 0x03, 0xFF
            reg604, reg605 = 0x00, 0x00
            reg606, reg607 = 0x00, 0x00
            reg608, reg609 = 0x03, 0xFF
        elif tp_mode == "yellow":
            reg601 = 0x01
            reg602, reg603 = 0x03, 0xFF
            reg604, reg605 = 0x03, 0xFF
            reg606, reg607 = 0x00, 0x00
            reg608, reg609 = 0x03, 0xFF
        elif tp_mode == "green":
            reg601 = 0x01
            reg602, reg603 = 0x00, 0x00
            reg604, reg605 = 0x03, 0xFF
            reg606, reg607 = 0x00, 0x00
            reg608, reg609 = 0x03, 0xFF
        elif tp_mode == "cyan":
            reg601 = 0x01
            reg604, reg605 = 0x03, 0xFF
            reg606, reg607 = 0x03, 0xFF
            reg608, reg609 = 0x03, 0xFF
        elif tp_mode == "blue":
            reg601 = 0x01
            reg602, reg603 = 0x00, 0x00
            reg604, reg605 = 0x00, 0x00
            reg606, reg607 = 0x03, 0xFF
            reg608, reg609 = 0x00, 0x00
        elif tp_mode == "magenta":
            reg601 = 0x01
            reg602, reg603 = 0x03, 0xFF
            reg604, reg605 = 0x00, 0x00
            reg606, reg607 = 0x03, 0xFF
            reg608, reg609 = 0x00, 0x00
        elif tp_mode == "pn9":
            reg601 = 0x04
        else:
            reg601 = 0x03

        # Enable test frame (color bar)
        logging.info("Enabling color bar test frame")
        camera.set_register(0x600, 0x0)
        camera.set_register(0x601, reg601)
        camera.set_register(0x602, reg602)
        camera.set_register(0x603, reg603)
        camera.set_register(0x604, reg604)
        camera.set_register(0x605, reg605)
        camera.set_register(0x606, reg606)
        camera.set_register(0x607, reg607)
        camera.set_register(0x608, reg608)
        camera.set_register(0x609, reg609)

        camera.configure_mipi_lane(lane_num, lane_rate)
        camera.configure(camera_mode_enum)

        version = camera.get_version()
        logging.info(f"Camera version: {version}")

      
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
        saved_count = application.get_saved_count()
        
        logging.info(f"Capture complete: {saved_count} images saved in {elapsed_time:.2f}s")

        stats = {
            "camera_mode": camera_mode,
            "camera_id": camera_id,
            "save_dir": save_dir,
        }
        
        # Check if frame was captured
        if saved_count < 1:
            return False, f"No frames saved: {saved_count}/1", stats
        
        # Golden file for reference
        if tp_mode == "bar":
            golden_filename = "golden_color_bar_imx258.npy"
        elif tp_mode == "red":
            golden_filename = "golden_red_imx258.npy"
        elif tp_mode == "orange":
            golden_filename = "golden_orange_imx258.npy"
        elif tp_mode == "yellow":   
            golden_filename = "golden_yellow_imx258.npy"
        elif tp_mode == "green":
            golden_filename = "golden_green_imx258.npy"
        elif tp_mode == "cyan":
            golden_filename = "golden_cyan_imx258.npy"
        elif tp_mode == "blue":
            golden_filename = "golden_blue_imx258.npy"
        elif tp_mode == "magenta":
            golden_filename = "golden_magenta_imx258.npy"
        elif tp_mode == "pn9":
            golden_filename = "golden_pn9_imx258.npy"
        else:
            golden_filename = "golden_color_bar_imx258.npy"

        # Compare captured frame to golden reference
        golden_path = _PROJECT_ROOT / "CI_CD" / "images" / golden_filename
        
        if not golden_path.exists():
            return False, f"Golden reference not found: {golden_path}", stats
        
        # Load golden reference
        gold_img = np.load(golden_path)
        logging.info(f"Loaded golden reference: {golden_path}")
        logging.info(f"  Shape: {gold_img.shape}, dtype: {gold_img.dtype}")
        
        # Find captured .npy file - get the newest one by modification time
        from pathlib import Path as PathLib
        npy_files = list(PathLib(save_dir).glob("*.npy"))
        
        if not npy_files:
            return False, f"No captured .npy files found in {save_dir}", stats
        
        # Sort by modification time (newest first) and take the most recent
        captured_file = max(npy_files, key=lambda x: x.stat().st_mtime)
        logging.info(f"Found {len(npy_files)} .npy files, loading newest: {captured_file.name}")
        
        captured_img = np.load(captured_file)
        logging.info(f"Loaded captured image: {captured_file.name}")
        logging.info(f"  Shape: {captured_img.shape}, dtype: {captured_img.dtype}")
        
        # Add captured image metadata to stats
        stats["captured_shape"] = str(captured_img.shape)
        stats["captured_dtype"] = str(captured_img.dtype)
        stats["captured_size_bytes"] = captured_img.nbytes
        stats["golden_shape"] = str(gold_img.shape)
        stats["golden_dtype"] = str(gold_img.dtype)
        
        # Bit-by-bit comparison
        if captured_img.shape != gold_img.shape:
            stats["comparison_result"] = "shape_mismatch"
            return False, f"Shape mismatch: captured {captured_img.shape} vs golden {gold_img.shape}", stats
        
        if captured_img.dtype != gold_img.dtype:
            stats["comparison_result"] = "dtype_mismatch"
            return False, f"Dtype mismatch: captured {captured_img.dtype} vs golden {gold_img.dtype}", stats
        
        # Calculate total bits compared
        bits_per_element = captured_img.itemsize * 8  # bytes to bits
        total_elements = captured_img.size
        total_bits = total_elements * bits_per_element
        
        stats["total_elements_compared"] = total_elements
        stats["bits_per_element"] = bits_per_element
        stats["total_bits_compared"] = total_bits
        
        # Exact comparison
        is_exact_match = np.array_equal(captured_img, gold_img)
        
        if is_exact_match:
            stats["comparison_result"] = "exact_match"
            stats["identical_elements"] = total_elements
            stats["identical_rate_percent"] = 100.0
            logging.info(f"✓ EXACT MATCH with golden reference")
            logging.info(f"  Total elements compared: {total_elements:,}")
            logging.info(f"  Total bits compared: {total_bits:,}")
            logging.info(f"  Identical rate: 100.00%")
            return True, "Test pattern matches golden reference exactly", stats
        else:
            diff_count = np.sum(captured_img != gold_img)
            identical_count = total_elements - diff_count
            identical_rate = 100.0 * (identical_count / total_elements)
            
            stats["comparison_result"] = "mismatch"
            stats["identical_elements"] = int(identical_count)
            stats["different_elements"] = int(diff_count)
            stats["identical_rate_percent"] = round(identical_rate, 4)
            
            logging.error(f"✗ MISMATCH with golden reference")
            logging.error(f"  Total elements compared: {total_elements:,}")
            logging.error(f"  Total bits compared: {total_bits:,}")
            logging.error(f"  Identical elements: {identical_count:,}")
            logging.error(f"  Different elements: {diff_count:,}")
            logging.error(f"  Identical rate: {identical_rate:.4f}%")
            return False, f"Test pattern mismatch: {identical_rate:.4f}% identical (expected 100%)", stats
        
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
    parser = argparse.ArgumentParser(
        description="Verify IMX258 test pattern against golden reference",
        epilog="Captures 100 frames with test pattern enabled and compares to golden reference."
    )
    parser.add_argument("--camera-ip", type=str, default="192.168.0.2", 
                       help="Hololink device IP address")
    parser.add_argument("--camera-mode", type=int, default=0, 
                       help="Camera mode (0=1080p60, 1=1080p30, etc.)")
    parser.add_argument("--log-level", type=int, default=logging.INFO, 
                       help="Logging level (10=DEBUG, 20=INFO, 30=WARNING, 40=ERROR)")
    parser.add_argument("--tp-mode", choices=["bar", "red", "orange", "yellow", "green", "cyan", "blue", "magenta", "pn9"], default="bar",
                       help="Test pattern mode to use during validation")

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=args.log_level,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Run test pattern validation
    cam_success, cam_message, cam_stats = verify_camera_functional(
        camera_ip=args.camera_ip,
        camera_mode=args.camera_mode,
        log_level=args.log_level,
        tp_mode=args.tp_mode
    )
    
    
    # Print summary
    print(tpf.header_footer(90, "TEST PATTERN VALIDATION SUMMARY"))
    
    status = "✓ PASS" if cam_success else "✗ FAIL"
    print(f"\n{status}: Test Pattern Comparison")
    print(f"  {cam_message}")
    
    if cam_stats:
        print("\n📊 Statistics:")
        for key, value in cam_stats.items():
            print(f"  {key}: {value}")
    
    print("\n" + "=" * 90)
    
    return cam_success, cam_message, cam_stats

if __name__ == "__main__":
    success, message, stats = main()
    if success:
        print(f"[PASS] {message}")
        sys.exit(0)
    else:
        print(f"[FAIL] {message}")
        sys.exit(1)



"""
red
# 0x00-Ori, 0x01-SolidColor, 0x02-ColorBar, 0x03-ShadedColorBar
camera_0.set_register(0x600,0x0)
camera_0.set_register(0x601,0x01) 
# Red
camera_0.set_register(0x602,0x03)
camera_0.set_register(0x603,0xFF)
# Green-Red
camera_0.set_register(0x604,0x00)
camera_0.set_register(0x605,0x00)
# Blue
camera_0.set_register(0x606,0x00)
camera_0.set_register(0x607,0x00)
# Green-Blue
camera_0.set_register(0x608,0x00)
camera_0.set_register(0x609,0x00)
    
orange (pixelated)
# 0x00-Ori, 0x01-SolidColor, 0x02-ColorBar, 0x03-ShadedColorBar
camera_0.set_register(0x600,0x0)
camera_0.set_register(0x601,0x01) 
# Red
camera_0.set_register(0x602,0x03)
camera_0.set_register(0x603,0xFF)
# Green-Red
camera_0.set_register(0x604,0x00)
camera_0.set_register(0x605,0x00)
# Blue
camera_0.set_register(0x606,0x00)
camera_0.set_register(0x607,0x00)
# Green-Blue
camera_0.set_register(0x608,0x03)
camera_0.set_register(0x609,0xFF)

yellow
# 0x00-Ori, 0x01-SolidColor, 0x02-ColorBar, 0x03-ShadedColorBar
camera_0.set_register(0x600,0x0)
camera_0.set_register(0x601,0x01) 
# Red
camera_0.set_register(0x602,0x03)
camera_0.set_register(0x603,0xFF)
# Green-Red
camera_0.set_register(0x604,0x03)
camera_0.set_register(0x605,0xFF)
# Blue
camera_0.set_register(0x606,0x00)
camera_0.set_register(0x607,0x00)
# Green-Blue
camera_0.set_register(0x608,0x03)
camera_0.set_register(0x609,0xFF)
    
green
# 0x00-Ori, 0x01-SolidColor, 0x02-ColorBar, 0x03-ShadedColorBar
camera_0.set_register(0x600,0x0)
camera_0.set_register(0x601,0x01) 
# Red
camera_0.set_register(0x602,0x00)
camera_0.set_register(0x603,0x00)
# Green-Red
camera_0.set_register(0x604,0x03)
camera_0.set_register(0x605,0xFF)
# Blue
camera_0.set_register(0x606,0x00)
camera_0.set_register(0x607,0x00)
# Green-Blue
camera_0.set_register(0x608,0x03)
camera_0.set_register(0x609,0xFF)
    
Cyan
# 0x00-Ori, 0x01-SolidColor, 0x02-ColorBar, 0x03-ShadedColorBar
camera_0.set_register(0x600,0x0)
camera_0.set_register(0x601,0x01) 
# Red
camera_0.set_register(0x602,0x00)
camera_0.set_register(0x603,0x00)
# Green-Red
camera_0.set_register(0x604,0x03)
camera_0.set_register(0x605,0xFF)
# Blue
camera_0.set_register(0x606,0x03)
camera_0.set_register(0x607,0xFF)
# Green-Blue
camera_0.set_register(0x608,0x03)
camera_0.set_register(0x609,0xFF)
    
Blue
# 0x00-Ori, 0x01-SolidColor, 0x02-ColorBar, 0x03-ShadedColorBar
camera_0.set_register(0x600,0x0)
camera_0.set_register(0x601,0x01) 
# Red
camera_0.set_register(0x602,0x00)
camera_0.set_register(0x603,0x00)
# Green-Red
camera_0.set_register(0x604,0x00)
camera_0.set_register(0x605,0x00)
# Blue
camera_0.set_register(0x606,0x03)
camera_0.set_register(0x607,0xFF)
# Green-Blue
camera_0.set_register(0x608,0x00)
camera_0.set_register(0x609,0x00)
    
Magenta
# 0x00-Ori, 0x01-SolidColor, 0x02-ColorBar, 0x03-ShadedColorBar
camera_0.set_register(0x600,0x0)
camera_0.set_register(0x601,0x01) 
# Red
camera_0.set_register(0x602,0x03)
camera_0.set_register(0x603,0xFF)
# Green-Red
camera_0.set_register(0x604,0x00)
camera_0.set_register(0x605,0x00)
# Blue
camera_0.set_register(0x606,0x03)
camera_0.set_register(0x607,0xFF)
# Green-Blue
camera_0.set_register(0x608,0x00)
camera_0.set_register(0x609,0x00)
    
"""