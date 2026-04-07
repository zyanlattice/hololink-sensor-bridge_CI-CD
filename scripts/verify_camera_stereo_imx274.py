#!/usr/bin/env python3
"""
Automated functional verification script for STEREO IMX274 cameras after bitstream programming.
Tests dual-camera setup with side-by-side display.
Based on linux_single_network_stereo_imx274_player.py architecture.

IMX274_MODE_3840X2160_60FPS = 0
IMX274_MODE_1920X1080_60FPS = 1
IMX274_MODE_3840X2160_60FPS_12BITS = 2
Unknown = 3

PERFORMANCE NOTES:
    Image saving operations (--save-images) are performed asynchronously to minimize
    pipeline blocking. However, some performance impact is expected:
    
    - Normal operation: ~60 FPS maintained per camera
    - With --save-images: Brief lag during GPU->CPU transfer, async disk I/O
    - With --holoviz: ~40-50 FPS due to visualization overhead (15-20 FPS drop)
    - With --holoviz --save-images: ~40 FPS (combines both overheads)
    
    The frame counter measures frames BEFORE save operations, so FPS metrics
    reflect actual camera throughput, not save performance.
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
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import math
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
    """Operator to save frames as images asynchronously to avoid blocking pipeline."""
    
    def __init__(self, *args, save_dir=None, max_saves=5, frames_to_save=None, camera_name="", **kwargs):
        super().__init__(*args, **kwargs)
        self.save_dir = save_dir or DEFAULT_SAVE_DIR
        self.max_saves = max_saves
        self.saved_count = 0
        self.frames_to_save = frames_to_save or []  # List of frame numbers to save
        self.current_frame = 0  # Track which frame we're on
        self.camera_name = camera_name  # "left" or "right"
        os.makedirs(self.save_dir, exist_ok=True)
        
        # Thread pool for async saving (prevents blocking pipeline)
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix=f"ImageSaver_{camera_name}")
        self._futures = []
        
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
            
            # For stereo cameras, tensors are named ("left" or "right")
            tensor = in_message.get(self.camera_name)
            
            # FAST: GPU → CPU transfer (must be synchronous, but fast ~5-10ms)
            cuda_array = cp.asarray(tensor)
            host_array = cp.asnumpy(cuda_array).copy()  # .copy() to detach from GPU memory
            
            timestamp = time.time()
            frame_num = self.current_frame
            save_count = self.saved_count
            
            # ASYNC: Submit save operation to thread pool (returns immediately)
            future = self._executor.submit(
                self._save_frame_async,
                host_array,
                frame_num,
                timestamp,
                save_count
            )
            self._futures.append(future)
            
            self.saved_count += 1
            logging.info(f"  [{self.camera_name}] Queued frame {save_count + 1}/{self.max_saves} for async save (frame {frame_num})")

        except Exception as e:
            logging.error(f"[{self.camera_name}] Failed to queue frame for saving: {e}", exc_info=True)
    
    def _save_frame_async(self, host_array, frame_num, timestamp, save_count):
        """Background thread function - performs slow I/O operations."""
        try:
            filename = os.path.join(self.save_dir, f"{self.camera_name}_frame_{frame_num:04d}_{timestamp:.3f}.npy")
            
            # Save .npy file (SLOW: disk I/O)
            np.save(filename, host_array)
            
            logging.info(f"  [{self.camera_name}][ASYNC] Saved frame {save_count + 1}: {filename}")
            logging.info(f"  [{self.camera_name}][ASYNC] Shape: {host_array.shape}, dtype: {host_array.dtype}, "
                        f"min: {host_array.min()}, max: {host_array.max()}")
            
            # Save PNG preview (SLOW: processing + disk I/O)
            try:
                from PIL import Image
                png_filename = filename.replace('.npy', '.png')
                
                # Normalize to 8-bit
                if host_array.dtype == np.uint16:
                    arr_min = host_array.min()
                    arr_max = host_array.max()
                    
                    if arr_max > arr_min:
                        normalized = ((host_array.astype(np.float32) - arr_min) / (arr_max - arr_min) * 255)
                        img_8bit = normalized.astype(np.uint8)
                    else:
                        img_8bit = np.zeros_like(host_array, dtype=np.uint8)
                    
                    logging.info(f"  [{self.camera_name}][ASYNC] Normalized from [{arr_min}, {arr_max}] to [0, 255]")
                    
                elif np.issubdtype(host_array.dtype, np.floating):
                    img_8bit = (np.clip(host_array, 0, 1) * 255).astype(np.uint8)
                else:
                    img_8bit = host_array.astype(np.uint8)
                
                img = Image.fromarray(img_8bit)
                img.save(png_filename)
                logging.info(f"  [{self.camera_name}][ASYNC] Saved PNG: {png_filename}")

            except Exception as e:
                logging.warning(f"  [{self.camera_name}][ASYNC] Could not save PNG: {e}")

        except Exception as e:
            logging.error(f"[{self.camera_name}][ASYNC] Failed to save frame: {e}", exc_info=True)
    
    def stop(self):
        """Wait for all pending saves to complete."""
        if self._futures:
            logging.info(f"[{self.camera_name}] Waiting for {len(self._futures)} pending image saves to complete...")
            for future in self._futures:
                try:
                    future.result(timeout=5.0)  # Wait up to 5s per save
                except Exception as e:
                    logging.warning(f"[{self.camera_name}] Save operation failed or timed out: {e}")
        self._executor.shutdown(wait=True)
        logging.info(f"[{self.camera_name}] All image saves completed")


class ScreenShotOp(holoscan.core.Operator):
    """Operator to capture screenshots of HolovizOp display asynchronously.
    
    WARNING: Screenshot capture is SLOW (~200-500ms per capture) due to:
    - PIL ImageGrab capturing entire screen (not just window)
    - Screen-to-file encoding
    
    Expected performance impact with --holoviz:
    - ~15-20 FPS drop from visualization overhead
    - Additional freeze during screenshot saves
    
    Use async thread pool to minimize pipeline blocking.
    """
    
    def __init__(self, *args, save_dir=None, max_saves=5, frames_to_save=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.save_dir = save_dir or DEFAULT_SAVE_DIR
        self.max_saves = max_saves
        self.saved_count = 0
        self.frames_to_save = frames_to_save or []  # List of frame numbers to save
        self.current_frame = 0  # Track which frame we're on
        os.makedirs(self.save_dir, exist_ok=True)
        
        # Thread pool for async screenshot capture
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="Screenshot")
        self._futures = []
        
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
            timestamp = time.time()
            filename = os.path.join(self.save_dir, f"stereo_screenshot_{self.current_frame:04d}_{timestamp:.3f}.png")
            save_count = self.saved_count
            
            # Submit screenshot to background thread (returns immediately)
            future = self._executor.submit(self._capture_screenshot_async, filename, save_count)
            self._futures.append(future)
            
            self.saved_count += 1
            logging.info(f"Queued screenshot {save_count + 1}/{self.max_saves} for async capture")

        except Exception as e:
            logging.warning(f"Could not queue screenshot: {e}")
    
    def _capture_screenshot_async(self, filename, save_count):
        """Background thread - captures and saves screenshot."""
        try:
            from PIL import ImageGrab
            
            # SLOW: Captures entire screen (200-500ms)
            screenshot = ImageGrab.grab()
            screenshot.save(filename)
            logging.info(f"[ASYNC] Saved screenshot {save_count + 1}: {filename}")
            
        except Exception as e:
            logging.warning(f"[ASYNC] Screenshot capture failed: {e}")
    
    def stop(self):
        """Wait for all pending screenshots to complete."""
        if self._futures:
            logging.info(f"Waiting for {len(self._futures)} pending screenshots to complete...")
            for future in self._futures:
                try:
                    future.result(timeout=10.0)  # Screenshots are slow, wait longer
                except Exception as e:
                    logging.warning(f"Screenshot operation failed or timed out: {e}")
        self._executor.shutdown(wait=True)
        logging.info("All screenshots completed")


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

    def calculate_frame_gaps(self, expected_fps=60.0):
        """Calculate frame gap statistics."""
        if len(self.timestamps) < 2:
            return {
                "max_gap_ms": 0,
                "avg_gap_ms": 0,
                "num_large_gaps": 0,
            }
        
        expected_interval = 1.0 / expected_fps
        intervals = [self.timestamps[i+1] - self.timestamps[i] 
                    for i in range(len(self.timestamps) - 1)]
        
        gaps_ms = [interval * 1000 for interval in intervals]
        expected_interval_ms = expected_interval * 1000
        large_gaps = [g for g in gaps_ms if g > expected_interval_ms * 1.5]
        
        max_gap = max(gaps_ms) if gaps_ms else 0
        avg_gap = round(sum(gaps_ms) / len(gaps_ms), 2)

        return {
            "max_gap_ms": round(max_gap, 2),
            "avg_gap_ms": avg_gap,
            "expected_interval_ms": round(expected_interval_ms, 2),
            "num_large_gaps": len(large_gaps),
            "frame_gap_test_result": "pass" if avg_gap <= expected_interval_ms * 1.2 else "fail"    
        }


class StereoVerificationApplication(holoscan.core.Application):
    """Stereo camera application for dual IMX274 verification."""
    
    def __init__(
        self,
        headless,
        cuda_context,
        cuda_device_ordinal,
        hololink_channel_left,
        camera_left,
        hololink_channel_right,
        camera_right,
        camera_mode,
        frame_limit,
        window_height,
        window_width,
        window_title,
        save_images=False,
        save_dir=None,
        max_saves=5,
        frames_to_save=None,
        save_combined=True,  # Save combined side-by-side stereo images
    ):
        super().__init__()
        self._headless = headless
        self._cuda_context = cuda_context
        self._cuda_device_ordinal = cuda_device_ordinal
        self._hololink_channel_left = hololink_channel_left
        self._camera_left = camera_left
        self._hololink_channel_right = hololink_channel_right
        self._camera_right = camera_right
        self._camera_mode = camera_mode
        self._frame_limit = frame_limit
        self._window_height = window_height
        self._window_width = window_width
        self._window_title = window_title
        self._save_images = save_images
        self._save_dir = save_dir or DEFAULT_SAVE_DIR
        self._max_saves = max_saves
        self._frames_to_save = frames_to_save or []
        self._save_combined = save_combined
        
        # Stereo-specific: metadata policy to handle duplicate names
        self.is_metadata_enabled = True
        self.metadata_policy = holoscan.core.MetadataPolicy.REJECT
        
        self._frame_counter_left = None
        self._frame_counter_right = None
        self._image_saver_left = None
        self._image_saver_right = None
        self._screenshot_saver = None  # Saves screenshots when using holoviz

    def compose(self):
        # DUPLICATE CONDITIONS - one for each camera
        if self._frame_limit:
            self._count_left = holoscan.conditions.CountCondition(
                self,
                name="count_left",
                count=self._frame_limit,
            )
            condition_left = self._count_left
            
            self._count_right = holoscan.conditions.CountCondition(
                self,
                name="count_right",
                count=self._frame_limit,
            )
            condition_right = self._count_right
        else:
            self._ok_left = holoscan.conditions.BooleanCondition(
                self, name="ok_left", enable_tick=True
            )
            condition_left = self._ok_left
            
            self._ok_right = holoscan.conditions.BooleanCondition(
                self, name="ok_right", enable_tick=True
            )
            condition_right = self._ok_right
        
        # Set SAME mode for BOTH cameras (shared clock requirement)
        self._camera_left.set_mode(self._camera_mode)
        self._camera_right.set_mode(self._camera_mode)

        # SHARED memory pool for csi_to_bayer (6 blocks for 2 cameras)
        csi_to_bayer_pool = holoscan.resources.BlockMemoryPool(
            self,
            name="csi_pool",
            storage_type=1,
            block_size=self._camera_left._width
            * ctypes.sizeof(ctypes.c_uint16)
            * self._camera_left._height,
            num_blocks=6,  # More blocks for dual cameras
        )
        
        # LEFT PIPELINE
        csi_to_bayer_operator_left = hololink_module.operators.CsiToBayerOp(
            self,
            name="csi_to_bayer_left",
            allocator=csi_to_bayer_pool,
            cuda_device_ordinal=self._cuda_device_ordinal,
            out_tensor_name="left",  # Named tensor
        )
        self._camera_left.configure_converter(csi_to_bayer_operator_left)
        
        # RIGHT PIPELINE
        csi_to_bayer_operator_right = hololink_module.operators.CsiToBayerOp(
            self,
            name="csi_to_bayer_right",
            allocator=csi_to_bayer_pool,
            cuda_device_ordinal=self._cuda_device_ordinal,
            out_tensor_name="right",  # Named tensor
        )
        self._camera_right.configure_converter(csi_to_bayer_operator_right)

        # Frame size should be same for both cameras (same mode)
        frame_size = csi_to_bayer_operator_left.get_csi_length()
        assert frame_size == csi_to_bayer_operator_right.get_csi_length()

        frame_context = self._cuda_context
        
        # LEFT RECEIVER
        receiver_operator_left = hololink_module.operators.LinuxReceiverOp(
            self,
            condition_left,
            name="receiver_left",
            frame_size=frame_size,
            frame_context=frame_context,
            hololink_channel=self._hololink_channel_left,
            device=self._camera_left,
        )

        # RIGHT RECEIVER
        receiver_operator_right = hololink_module.operators.LinuxReceiverOp(
            self,
            condition_right,
            name="receiver_right",
            frame_size=frame_size,
            frame_context=frame_context,
            hololink_channel=self._hololink_channel_right,
            device=self._camera_right,
        )

        # Get bayer/pixel formats (should be same for both)
        bayer_format = self._camera_left.bayer_format()
        assert bayer_format == self._camera_right.bayer_format()
        pixel_format = self._camera_left.pixel_format()
        assert pixel_format == self._camera_right.pixel_format()
        
        # LEFT IMAGE PROCESSOR
        image_processor_left = hololink_module.operators.ImageProcessorOp(
            self,
            name="image_processor_left",
            optical_black=50,  # IMX274 optical black
            bayer_format=bayer_format.value,
            pixel_format=pixel_format.value,
        )
        
        # RIGHT IMAGE PROCESSOR
        image_processor_right = hololink_module.operators.ImageProcessorOp(
            self,
            name="image_processor_right",
            optical_black=50,  # IMX274 optical black
            bayer_format=bayer_format.value,
            pixel_format=pixel_format.value,
        )

        # SHARED memory pool for demosaic (6 blocks for 2 cameras)
        rgba_components_per_pixel = 4
        bayer_pool = holoscan.resources.BlockMemoryPool(
            self,
            name="bayer_pool",
            storage_type=1,
            block_size=self._camera_left._width
            * rgba_components_per_pixel
            * ctypes.sizeof(ctypes.c_uint16)
            * self._camera_left._height,
            num_blocks=6,  # More blocks for dual cameras
        )
        
        # LEFT DEMOSAIC
        demosaic_left = holoscan.operators.BayerDemosaicOp(
            self,
            name="demosaic_left",
            pool=bayer_pool,
            generate_alpha=True,
            alpha_value=65535,
            bayer_grid_pos=bayer_format.value,
            interpolation_mode=0,
            in_tensor_name="left",
            out_tensor_name="left",
        )
        
        # RIGHT DEMOSAIC
        demosaic_right = holoscan.operators.BayerDemosaicOp(
            self,
            name="demosaic_right",
            pool=bayer_pool,
            generate_alpha=True,
            alpha_value=65535,
            bayer_grid_pos=bayer_format.value,
            interpolation_mode=0,
            in_tensor_name="right",
            out_tensor_name="right",
        )

        # SIDE-BY-SIDE VISUALIZATION
        # Left view - left half of window
        left_spec = holoscan.operators.HolovizOp.InputSpec(
            "left", holoscan.operators.HolovizOp.InputType.COLOR
        )
        left_spec_view = holoscan.operators.HolovizOp.InputSpec.View()
        left_spec_view.offset_x = 0
        left_spec_view.offset_y = 0
        left_spec_view.width = 0.5  # Left 50%
        left_spec_view.height = 1
        left_spec.views = [left_spec_view]

        # Right view - right half of window
        right_spec = holoscan.operators.HolovizOp.InputSpec(
            "right", holoscan.operators.HolovizOp.InputType.COLOR
        )
        right_spec_view = holoscan.operators.HolovizOp.InputSpec.View()
        right_spec_view.offset_x = 0.5  # Right 50%
        right_spec_view.offset_y = 0
        right_spec_view.width = 0.5
        right_spec_view.height = 1
        right_spec.views = [right_spec_view]

        # Use fullscreen for visualization when saving images (better screenshots)
        use_fullscreen = self._save_images and not self._headless
        
        visualizer = holoscan.operators.HolovizOp(
            self,
            name="holoviz",
            headless=self._headless,
            fullscreen=use_fullscreen,
            framebuffer_srgb=True,
            tensors=[left_spec, right_spec],
            height=self._window_height,
            width=self._window_width,
            window_title=self._window_title,
        )

        # SCREENSHOT SAVER (if save_images enabled with holoviz)
        if self._save_images and not self._headless:
            self._screenshot_saver = ScreenShotOp(
                self,
                name="screenshot_saver",
                save_dir=self._save_dir,
                max_saves=self._max_saves,
                frames_to_save=self._frames_to_save,
            )

        # FRAME COUNTERS (optional, for statistics)
        self._frame_counter_left = FrameCounterOp(
            self,
            name="frame_counter_left",
            frame_limit=self._frame_limit,
            pass_through=True,
        )
        
        self._frame_counter_right = FrameCounterOp(
            self,
            name="frame_counter_right",
            frame_limit=self._frame_limit,
            pass_through=True,
        )

        # IMAGE SAVERS (if save_images enabled)
        if self._save_images:
            self._image_saver_left = ImageSaverOp(
                self,
                name="image_saver_left",
                save_dir=self._save_dir,
                max_saves=self._max_saves,
                frames_to_save=self._frames_to_save,
                camera_name="left",
            )
            
            self._image_saver_right = ImageSaverOp(
                self,
                name="image_saver_right",
                save_dir=self._save_dir,
                max_saves=self._max_saves,
                frames_to_save=self._frames_to_save,
                camera_name="right",
            )

        # CONNECT LEFT PIPELINE
        self.add_flow(
            receiver_operator_left, csi_to_bayer_operator_left, {("output", "input")}
        )
        self.add_flow(
            csi_to_bayer_operator_left, image_processor_left, {("output", "input")}
        )
        self.add_flow(image_processor_left, demosaic_left, {("output", "receiver")})
        self.add_flow(demosaic_left, self._frame_counter_left, {("transmitter", "input")})
        self.add_flow(self._frame_counter_left, visualizer, {("output", "receivers")})
        
        # If saving images, also branch to image saver
        if self._save_images:
            self.add_flow(demosaic_left, self._image_saver_left, {("transmitter", "input")})

        # CONNECT RIGHT PIPELINE
        self.add_flow(
            receiver_operator_right, csi_to_bayer_operator_right, {("output", "input")}
        )
        self.add_flow(
            csi_to_bayer_operator_right, image_processor_right, {("output", "input")}
        )
        self.add_flow(image_processor_right, demosaic_right, {("output", "receiver")})
        self.add_flow(demosaic_right, self._frame_counter_right, {("transmitter", "input")})
        self.add_flow(self._frame_counter_right, visualizer, {("output", "receivers")})
        
        # If saving images, also branch to image saver
        if self._save_images:
            self.add_flow(demosaic_right, self._image_saver_right, {("transmitter", "input")})
            
            # Connect screenshot saver (captures fullscreen holoviz display)
            if self._screenshot_saver:
                # Screenshots triggered by frame counter output
                self.add_flow(self._frame_counter_left, self._screenshot_saver, {("output", "input")})

    def get_frame_count_left(self) -> int:
        return self._frame_counter_left.frame_count if self._frame_counter_left else 0
    
    def get_frame_count_right(self) -> int:
        return self._frame_counter_right.frame_count if self._frame_counter_right else 0
    
    def get_fps_left(self) -> float:
        if not self._frame_counter_left or not self._frame_counter_left.start_time:
            return 0.0
        return self._frame_counter_left.fps
    
    def get_fps_right(self) -> float:
        if not self._frame_counter_right or not self._frame_counter_right.start_time:
            return 0.0
        return self._frame_counter_right.fps
    
    def get_frame_gap_stats_left(self, ex_fps=60.0) -> dict:
        if not self._frame_counter_left:
            return {}
        return self._frame_counter_left.calculate_frame_gaps(expected_fps=ex_fps)
    
    def get_frame_gap_stats_right(self, ex_fps=60.0) -> dict:
        if not self._frame_counter_right:
            return {}
        return self._frame_counter_right.calculate_frame_gaps(expected_fps=ex_fps)
    
    def get_saved_count_left(self) -> int:
        """Get the number of images saved from left camera."""
        return self._image_saver_left.saved_count if self._image_saver_left else 0
    
    def get_saved_count_right(self) -> int:
        """Get the number of images saved from right camera."""
        return self._image_saver_right.saved_count if self._image_saver_right else 0
    
    def get_saved_count_screenshot(self) -> int:
        """Get the number of holoviz screenshots saved."""
        return self._screenshot_saver.saved_count if self._screenshot_saver else 0
    
    def interrupt(self):
        try:
            if hasattr(super(), 'interrupt'):
                super().interrupt()
        except Exception as e:
            logging.warning(f"Error calling interrupt: {e}")


def verify_stereo_camera_functional(
    holoviz: bool = False,
    camera_ip: str = "192.168.0.2",
    camera_mode: int = 1,  # Default to 1080p for better performance
    frame_limit: int = 50,
    timeout_seconds: int = 10,
    min_fps: float = 10.0,
    log_level: int = logging.INFO,
    window_height: int = 1080,  # Default window size
    window_width: int = 1920,
    save_images: bool = False,
    save_dir: str = None,
    max_saves: int = 5,
    save_combined: bool = True,  # Save fullscreen screenshots with --holoviz
    test_frame: bool = True,
    tp_mode_left: str = "vbar",
    tp_mode_right: str = "vbar"
) -> Tuple[bool, str, dict]:
    """
    Verify STEREO IMX274 camera functionality.
    
    Args:
        holoviz: Whether to run with holoviz (GUI)
        camera_ip: IP address of the Hololink device
        camera_mode: Camera mode for both cameras (see Imx274_Mode enum)
        frame_limit: Number of frames to capture per camera
        timeout_seconds: Maximum time to wait for frames
        min_fps: Minimum acceptable FPS per camera
        log_level: Logging level
        window_height: Window height for visualization
        window_width: Window width for visualization
        save_images: Whether to save captured frames as images (per camera)
        save_dir: Directory to save images
        max_saves: Maximum number of images to save per camera
        save_combined: Whether to save fullscreen screenshots with --holoviz (stereo_screenshot_*.png)
        test_frame: Enable test pattern mode (uses pattern ID 10 - shaded color bar)
        tp_mode_left: Test pattern mode for left camera ("hbar" for horizontal bars, "vbar" for vertical bars)
        tp_mode_right: Test pattern mode for right camera ("hbar" for horizontal bars, "vbar" for vertical bars)

    Returns:
        Tuple of (success: bool, message: str, stats: dict)
    """
    
    # Calculate which frames to save (evenly distributed)
    def _compute_img_fac(frame_limit: int, max_saves: int) -> list:
        """Compute which frame numbers to save, evenly distributed."""
        if max_saves <= 0 or frame_limit <= 0:
            return []
        interval = math.floor(frame_limit / (max_saves + 1))
        return [int((i+1) * interval) for i in range(max_saves)]
    
    frames_to_save = _compute_img_fac(frame_limit, max_saves) if save_images else []
    logging.info(f"Frames to save: {frames_to_save}")  # Debug
    
    # Use default save directory if not specified
    if save_dir is None:
        save_dir = DEFAULT_SAVE_DIR
    
    if tp_mode_left == "vbar":
        test_pattern_id_left = 10  # Shaded vertical bars
    elif tp_mode_left == "hbar":
        test_pattern_id_left = 11  # Shaded horizontal bars

    if tp_mode_right == "vbar":
        test_pattern_id_right = 10  # Shaded vertical bars
    elif tp_mode_right == "hbar":
        test_pattern_id_right = 11  # Shaded horizontal bars

    hololink_module.logging_level(log_level)
    
    logging.info("=" * 80)
    logging.info(f"Starting STEREO IMX274 Camera Functional Verification")
    logging.info(f"Camera IP: {camera_ip}, Camera: STEREO IMX274, Mode: {camera_mode}")
    logging.info(f"Frame limit: {frame_limit} per camera, Timeout: {timeout_seconds}s")
    if test_frame:
        logging.info(f"Test pattern mode: ENABLED (left pattern ID {test_pattern_id_left} - {'shaded horizontal bars' if tp_mode_left == 'hbar' else 'shaded vertical bars'}, right pattern ID {test_pattern_id_right} - {'shaded horizontal bars' if tp_mode_right == 'hbar' else 'shaded vertical bars'})")
    if save_images:
        logging.info(f"Image saving: ENABLED (max {max_saves} images per camera to {save_dir})")
    logging.info("=" * 80)
    
    # Create save directory early to catch permission/path errors before camera setup
    if save_images:
        try:
            os.makedirs(save_dir, exist_ok=True)
            logging.info(f"Created/verified save directory: {save_dir}")
        except Exception as e:
            return False, f"Failed to create save directory '{save_dir}': {str(e)}", {}
    
    hololink = None
    camera_left = None
    camera_right = None
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
        
        # CREATE SEPARATE METADATA FOR LEFT AND RIGHT
        logging.info("Creating dual data channels for stereo cameras...")
        channel_metadata_left = hololink_module.Metadata(channel_metadata)
        hololink_module.DataChannel.use_sensor(channel_metadata_left, 0)  # Sensor 0
        
        channel_metadata_right = hololink_module.Metadata(channel_metadata)
        hololink_module.DataChannel.use_sensor(channel_metadata_right, 1)  # Sensor 1
        
        # Create SEPARATE data channels
        hololink_channel_left = hololink_module.DataChannel(channel_metadata_left)
        hololink_channel_right = hololink_module.DataChannel(channel_metadata_right)
        
        # Create TWO cameras with different expander configurations
        logging.info("Initializing left camera (expander_configuration=0)...")
        camera_left = hololink_module.sensors.imx274.dual_imx274.Imx274Cam(
            hololink_channel_left, expander_configuration=0
        )
        
        logging.info("Initializing right camera (expander_configuration=1)...")
        camera_right = hololink_module.sensors.imx274.dual_imx274.Imx274Cam(
            hololink_channel_right, expander_configuration=1
        )
        
        camera_mode_enum = hololink_module.sensors.imx274.imx274_mode.Imx274_Mode(camera_mode)
        
        headless = not holoviz
        window_title = f"Stereo IMX274 - {camera_ip}"

        # Create stereo application
        application = StereoVerificationApplication(
            headless,
            cu_context,
            cu_device_ordinal,
            hololink_channel_left,
            camera_left,
            hololink_channel_right,
            camera_right,
            camera_mode_enum,
            frame_limit,
            window_height,
            window_width,
            window_title,
            save_images=save_images,
            save_dir=save_dir,
            max_saves=max_saves,
            frames_to_save=frames_to_save,
            save_combined=save_combined,
        )

        # CRITICAL: Both channels share the SAME hololink instance
        logging.info("Starting Hololink (shared control plane)...")
        hololink = hololink_channel_left.hololink()
        assert hololink is hololink_channel_right.hololink()  # Verify they're the same
        
        hololink.start()
        hololink.reset()
        
        # Configure BOTH cameras (same mode - shared clock requirement)
        logging.info("Configuring cameras...")
        camera_left.setup_clock()  # This also sets camera_right's clock (shared)
        camera_left.configure(camera_mode_enum)
        camera_left.set_digital_gain_reg(0x4)
        
        camera_right.configure(camera_mode_enum)
        camera_right.set_digital_gain_reg(0x4)

        version_left = camera_left.get_version()
        version_right = camera_right.get_version()
        logging.info(f"Camera versions - Left: {version_left}, Right: {version_right}")

         # Enable test pattern if requested (for golden image capture)
        if test_frame:
            logging.info(f"Enabling test pattern (left pattern ID {test_pattern_id_left} - {'shaded horizontal bars' if tp_mode_left == 'hbar' else 'shaded vertical bars'}, right pattern ID {test_pattern_id_right} - {'shaded horizontal bars' if tp_mode_right == 'hbar' else 'shaded vertical bars'})")
            camera_left.test_pattern(test_pattern_id_left)
            camera_right.test_pattern(test_pattern_id_right)

        # Run verification
        logging.info(f"Capturing {frame_limit} frames from each camera...")
        start_time = time.time()
        
        def run_app():
            try:
                application.run()
            except Exception as e:
                logging.warning(f"Application exception: {e}")
        
        app_thread = threading.Thread(target=run_app, daemon=True)
        app_thread.start()
        
        # Monitor for completion
        poll_interval = 0.1
        first_frame_time = None
        last_frame_time = None
        max_wait_time = timeout_seconds + 30
        start_wait = time.time()
        
        while app_thread.is_alive():
            time.sleep(poll_interval)
            
            frames_left = application.get_frame_count_left()
            frames_right = application.get_frame_count_right()
            
            if (frames_left > 0 or frames_right > 0) and first_frame_time is None:
                first_frame_time = time.time()
                logging.info(f"First frame received after {time.time() - start_time:.2f}s")
            
            if frames_left > 0 or frames_right > 0:
                last_frame_time = time.time()
            
            # Safety timeout
            if last_frame_time is not None and (time.time() - last_frame_time) > timeout_seconds:
                logging.error(f"No new frames for {timeout_seconds}s, aborting...")
                try:
                    application.interrupt()
                except Exception as e:
                    logging.warning(f"Error interrupting app: {e}")
                break
            
            if (time.time() - start_wait) > max_wait_time:
                logging.error(f"Total wait time exceeded {max_wait_time}s, aborting...")
                try:
                    application.interrupt()
                except Exception as e:
                    logging.warning(f"Error interrupting app: {e}")
                break
        
        if app_thread.is_alive():
            logging.info("Waiting for application thread to finish...")
            app_thread.join(timeout=3.0)
        
        elapsed_time = time.time() - start_time
        
        # Collect statistics from BOTH cameras
        frame_count_left = application.get_frame_count_left()
        frame_count_right = application.get_frame_count_right()
        avg_fps_left = application.get_fps_left()
        avg_fps_right = application.get_fps_right()
        
        def get_cam_mode_name(cam_mode):
            for mode in hololink_module.sensors.imx274.imx274_mode.Imx274_Mode:
                if mode.value == cam_mode: 
                    return mode.name
            return None

        mode_name = get_cam_mode_name(int(camera_mode))
        expected_fps = 0
        if mode_name:
            m = re.search(r'_(\d+)\s*fps', str(mode_name), flags=re.IGNORECASE)
            expected_fps = int(m.group(1)) if m else None

        computed_min_fps = expected_fps * 0.8 if expected_fps else min_fps
        
        logging.info(f"Left camera - Frames: {frame_count_left}, FPS: {avg_fps_left:.2f}")
        logging.info(f"Right camera - Frames: {frame_count_right}, FPS: {avg_fps_right:.2f}")
        logging.info(f"Expected FPS: {expected_fps}, Min FPS: {computed_min_fps:.2f}")

        stats = {
            "frame_count_left": frame_count_left,
            "frame_count_right": frame_count_right,
            "elapsed_time": elapsed_time,
            "avg_fps_left": avg_fps_left,
            "avg_fps_right": avg_fps_right,
            "expected_fps": expected_fps,
            "min_fps": computed_min_fps,
        }
        
        if save_images:
            saved_count_left = application.get_saved_count_left()
            saved_count_right = application.get_saved_count_right()
            stats["saved_images_left"] = saved_count_left
            stats["saved_images_right"] = saved_count_right
            # Add screenshot count if using holoviz
            if holoviz:
                saved_count_screenshot = application.get_saved_count_screenshot()
                stats["saved_images_screenshot"] = saved_count_screenshot
            stats["save_dir"] = save_dir
        
        gap_stats_left = application.get_frame_gap_stats_left(ex_fps=expected_fps)
        gap_stats_right = application.get_frame_gap_stats_right(ex_fps=expected_fps)
        
        stats["left_max_gap_ms"] = gap_stats_left.get("max_gap_ms", 0)
        stats["left_avg_gap_ms"] = gap_stats_left.get("avg_gap_ms", 0)
        stats["left_gap_test"] = gap_stats_left.get("frame_gap_test_result", "unknown")
        
        stats["right_max_gap_ms"] = gap_stats_right.get("max_gap_ms", 0)
        stats["right_avg_gap_ms"] = gap_stats_right.get("avg_gap_ms", 0)
        stats["right_gap_test"] = gap_stats_right.get("frame_gap_test_result", "unknown")

        # Print to stdout for subprocess capture
        print(f"Left Camera FPS: {avg_fps_left:.2f}")
        print(f"Right Camera FPS: {avg_fps_right:.2f}")
        
        # Determine success
        if frame_count_left < frame_limit * 0.9:
            return False, f"Insufficient frames from left camera: {frame_count_left}/{frame_limit}", stats
        
        if frame_count_right < frame_limit * 0.9:
            return False, f"Insufficient frames from right camera: {frame_count_right}/{frame_limit}", stats
        
        if avg_fps_left < computed_min_fps and frame_count_left > 10:
            return False, f"Left camera FPS too low: {avg_fps_left:.2f} < {computed_min_fps:.2f}", stats
        
        if avg_fps_right < computed_min_fps and frame_count_right > 10:
            return False, f"Right camera FPS too low: {avg_fps_right:.2f} < {computed_min_fps:.2f}", stats
        
        if gap_stats_left.get("frame_gap_test_result") == "fail":
            return False, f"Left camera frame gap test failed: avg {gap_stats_left.get('avg_gap_ms')}ms", stats
        
        if gap_stats_right.get("frame_gap_test_result") == "fail":
            return False, f"Right camera frame gap test failed: avg {gap_stats_right.get('avg_gap_ms')}ms", stats
        
        stats["fps_test_result"] = "pass"
        return True, "Stereo camera verification passed", stats
        
    except Exception as e:
        logging.error(f"Verification failed with exception: {e}", exc_info=True)
        return False, f"Exception during verification: {str(e)}", {}
    
    finally:
        stop_event.set()
        
        # Wait for pending async image saves to complete FIRST
        if application and application._image_saver_left:
            try:
                logging.info("Waiting for pending left camera image saves to complete...")
                application._image_saver_left.stop()
            except Exception as e:
                logging.warning(f"Error waiting for left camera image saves: {e}")
        
        if application and application._image_saver_right:
            try:
                logging.info("Waiting for pending right camera image saves to complete...")
                application._image_saver_right.stop()
            except Exception as e:
                logging.warning(f"Error waiting for right camera image saves: {e}")
        
        if application and application._screenshot_saver:
            try:
                logging.info("Waiting for pending screenshot saves to complete...")
                application._screenshot_saver.stop()
            except Exception as e:
                logging.warning(f"Error waiting for screenshot saves: {e}")
        
        # CLEANUP SEQUENCE
        if hololink:
            try:
                logging.info("Stopping Hololink...")
                hololink.stop()
            except Exception as e:
                logging.error(f"Error stopping hololink: {e}", exc_info=True)
        
        if app_thread and app_thread.is_alive():
            logging.info("Waiting for application thread to finish...")
            app_thread.join(timeout=5.0)
        
        try:
            logging.info("Resetting Hololink framework...")
            hololink_module.Hololink.reset_framework()
        except Exception as e:
            logging.warning(f"Error resetting hololink framework: {e}")
        
        if cu_context:
            try:
                logging.info("Destroying CUDA context...")
                cuda.cuCtxDestroy(cu_context)
            except Exception as e:
                logging.error(f"Error destroying CUDA context: {e}", exc_info=True)
        
        logging.info("Cleanup complete")


def main() -> bool:
    parser = argparse.ArgumentParser(description="Verify STEREO IMX274 camera functionality")
    parser.add_argument("--camera-ip", type=str, default="192.168.0.2", help="Hololink device IP")
    parser.add_argument("--camera-mode", type=int, default=1, help="Camera mode for both cameras (1=1080p recommended)")
    parser.add_argument("--frame-limit", type=int, default=300, help="Frames per camera")
    parser.add_argument("--timeout", type=int, default=15, help="Timeout in seconds")
    parser.add_argument("--min-fps", type=float, default=30.0, help="Minimum acceptable FPS")
    parser.add_argument("--log-level", type=int, default=logging.INFO, help="Logging level")
    parser.add_argument("--window-height", type=int, default=1080, help="Window height")
    parser.add_argument("--window-width", type=int, default=1920, help="Window width")
    parser.add_argument("--list-mode", action="store_true", help="List camera modes and exit")
    parser.add_argument("--holoviz", action="store_true", help="Run with holoviz (GUI)")
    parser.add_argument("--save-images", action="store_true", default=False, help="Save captured frames as images")
    parser.add_argument("--save-dir", type=str, default=None, help=f"Directory to save images (default: {DEFAULT_SAVE_DIR})")
    parser.add_argument("--max-saves", type=int, default=1, help="Maximum number of images to save per camera")
    parser.add_argument("--save-combined", action="store_true", default=True, help="Save fullscreen screenshots with --holoviz (default: True)")
    parser.add_argument("--no-save-combined", dest="save_combined", action="store_false", help="Don't save fullscreen screenshots")
    parser.add_argument("--test-frame", action="store_true", help="Enable test pattern mode (pattern ID 10 - shaded color bar) for golden image capture")
    parser.add_argument("--tp-mode-left", choices=["hbar","vbar"], default="vbar", help="Test pattern mode for left camera: horizontal bars (hbar) or vertical bars (vbar)")
    parser.add_argument("--tp-mode-right", choices=["hbar","vbar"], default="vbar", help="Test pattern mode for right camera: horizontal bars (hbar) or vertical bars (vbar)")
    
    args = parser.parse_args()
    
    if args.list_mode:
        print("Available IMX274 Camera Modes:")
        for mode in hololink_module.sensors.imx274.imx274_mode.Imx274_Mode:
            print(f"  {mode.value}: {mode.name}")
        sys.exit(0)

    # Setup logging
    logging.basicConfig(
        level=args.log_level,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Verify stereo cameras
    success, message, stats = verify_stereo_camera_functional(
        holoviz=args.holoviz,
        camera_ip=args.camera_ip,
        camera_mode=args.camera_mode,
        frame_limit=args.frame_limit,
        timeout_seconds=args.timeout,
        min_fps=args.min_fps,
        log_level=args.log_level,
        window_height=args.window_height,
        window_width=args.window_width,
        save_images=args.save_images,
        save_dir=args.save_dir,
        max_saves=args.max_saves,
        save_combined=args.save_combined,
        test_frame=args.test_frame,
        tp_mode_left=args.tp_mode_left,
        tp_mode_right=args.tp_mode_right,
    )
    
    # Print summary
    print(tpf.header_footer(90, "STEREO CAMERA VERIFICATION SUMMARY"))
    
    status = "✓ PASS" if success else "✗ FAIL"
    print(f"\n{status}: Stereo Camera Functionality")
    print(f"  {message}")
    if stats:
        for key, value in stats.items():
            print(f"  {key}: {value}")
    
    print(f"\n📊 Metrics: {stats}")
    print("\n" + "=" * 90)
    
    if success:
        print(" Stereo camera verification PASSED")
        return success, message, stats
    else:
        print(" TESTS FAILED")
        return success, message, stats


if __name__ == "__main__":
    success, message, stats = main()
    if success:
        print(f"[PASS] {message}")
        sys.exit(0)
    else:
        print(f"[FAIL] {message}")
        sys.exit(1)
