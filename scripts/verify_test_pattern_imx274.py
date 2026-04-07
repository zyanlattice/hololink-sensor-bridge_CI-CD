#!/usr/bin/env python3
"""
Test pattern validation script for IMX274 camera (single sensor or dual sensors).

Captures test pattern frames and compares them bit-by-bit against golden 
reference images stored in CI_CD/images/.

=== ARCHITECTURE OVERVIEW ===

Bajoran Board Setup:
- Has 2 SFP ports: 192.168.0.2 and 192.168.0.3
- Each SFP port provides access to 2 sensors (sensor 0 and sensor 1)
- Sensors are accessed via DataChannel.use_sensor(metadata, sensor_id)

AGX Orin Limitation:
- Only has 1 network interface (can't connect to both SFPs simultaneously)
- Tests are run sequentially: first 192.168.0.2, then 192.168.0.3

NVIDIA Pytest Test Types (in test_imx274_pattern.py):
1. test_imx274_pattern:
   - Two SEPARATE cameras at 192.168.0.2 and 192.168.0.3
   - Each camera has its own Infiniband interface
   - Requires AGX Orin with 2 network interfaces (dual ConnectX)
   - NOT applicable to your setup

2. test_imx274_multicast:
   - Uses multicast addressing (224.0.0.x)
   - Allows multiple receivers to subscribe to ONE camera stream
   - Useful for broadcasting same video to multiple servers
   - Example: One camera → multiple monitoring stations
   - NOT needed for your use case

3. test_imx274_stereo_single_interface: ← THIS IS YOUR ARCHITECTURE
   - ONE network interface (e.g., 192.168.0.2)
   - Accesses BOTH sensor 0 and sensor 1 on that single IP
   - Uses DataChannel.use_sensor(channel, 0) for left
   - Uses DataChannel.use_sensor(channel, 1) for right
   - This is what Bajoran board supports per SFP port
   
4. test_linux_imx274_stereo_single_interface:
   - Same as #3 but uses Linux sockets instead of Infiniband
   - Doesn't validate image data (expects packet loss)

Your Testing Workflow:
  Step 1: Test 192.168.0.2 with sensor 0 only
          python verify_test_pattern_imx274.py --camera-ip 192.168.0.2
          
  Step 2: Test 192.168.0.2 with both sensors (0 and 1)
          python verify_test_pattern_imx274.py --stereo --camera-ip 192.168.0.2
          
  Step 3: Test 192.168.0.3 with sensor 0 only
          python verify_test_pattern_imx274.py --camera-ip 192.168.0.3
          
  Step 4: Test 192.168.0.3 with both sensors (0 and 1)
          python verify_test_pattern_imx274.py --stereo --camera-ip 192.168.0.3

=== END ARCHITECTURE OVERVIEW ===

Features:
- Single sensor mode (default): Tests sensor 0 only
- Stereo mode (--stereo flag): Tests BOTH sensors (0 and 1) on the SAME IP
- Multiple test pattern types (color bar, solid colors)
- Side-by-side stereo visualization
- Golden reference comparison

Usage:
    # Single sensor (sensor 0 only) with vertical bar pattern
    python verify_test_pattern_imx274.py --camera-ip 192.168.0.2 --camera-mode 0 --tp-mode1 vbar
    
    # Dual sensors with different patterns (left=vbar, right=hbar)
    python verify_test_pattern_imx274.py --stereo --camera-ip 192.168.0.2 --camera-mode 0 --tp-mode1 vbar --tp-mode2 hbar
    
    # Single sensor on second SFP port with horizontal bar
    python verify_test_pattern_imx274.py --camera-ip 192.168.0.3 --camera-mode 0 --tp-mode1 hbar
    
    # Dual sensors on second SFP port
    python verify_test_pattern_imx274.py --stereo --camera-ip 192.168.0.3 --camera-mode 0 --tp-mode1 vbar --tp-mode2 hbar

IMX274 Modes:
    0: 3840x2160 @ 60fps (4K)
    1: 1920x1080 @ 60fps (1080p)
    2: 1920x1080 @ 120fps (high frame rate)

Test Pattern Modes (--tp-mode1 and --tp-mode2):
    vbar: Vertical bar / shaded color bar (pattern ID 10) → golden_vbar_imx274.npy
    hbar: Horizontal bar / solid fade (pattern ID 11) → golden_hbar_imx274.npy
    
    In single mode: Only --tp-mode1 is used
    In stereo mode: --tp-mode1 for sensor 0 (left), --tp-mode2 for sensor 1 (right)
"""

import argparse
import ctypes
import logging
import math
import os
import sys
import time
import threading
from pathlib import Path
from typing import Tuple, Optional
import numpy as np

try:
    import terminal_print_formating as tpf
except ImportError:
    # Fallback if terminal_print_formating is not available
    class tpf:
        @staticmethod
        def header_footer(width, text):
            return "=" * width + f"\n{text.center(width)}\n" + "=" * width

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
    
    def __init__(self, *args, save_dir=None, max_saves=1, frames_to_save=None, camera_name="camera", **kwargs):
        super().__init__(*args, **kwargs)
        self.save_dir = save_dir or DEFAULT_SAVE_DIR
        self.max_saves = max_saves
        self.saved_count = 0
        self.frames_to_save = frames_to_save or []
        self.current_frame = 0
        self.camera_name = camera_name
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
            
            # For stereo cameras, tensors are named ("left" or "right")
            # For single camera, camera_name might be generic ("imx274"), so try both
            if self.camera_name in ["left", "right"]:
                tensor = in_message.get(self.camera_name)
            else:
                tensor = in_message.get("")
            
            # Convert Holoscan Tensor (GPU object) → CuPy array (GPU array) → NumPy array (CPU array)
            cuda_array = cp.asarray(tensor)
            host_array = cp.asnumpy(cuda_array).copy()  # .copy() to detach from GPU memory
            
            timestamp = time.time()
            filename = os.path.join(
                self.save_dir, 
                f"{self.camera_name}_frame_{self.current_frame:04d}_{timestamp:.3f}.npy"
            )
            
            # Save .npy file
            np.save(filename, host_array)
                        
            logging.info(f"  [{self.camera_name}] Saved frame {self.saved_count + 1}/{self.max_saves}: {filename}")
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
    
    def __init__(self, *args, frame_limit=50, pass_through=False, name_prefix="", **kwargs):
        self.pass_through = pass_through
        self.frame_limit = frame_limit
        self.frame_count = 0
        self.start_time = None
        self.timestamps = []
        self.fps = 0.0
        self.name_prefix = name_prefix
        
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
            prefix = f"[{self.name_prefix}] " if self.name_prefix else ""
            logging.info(f"{prefix}Frames received: {self.frame_count}, FPS: {fps:.2f}")

        if self.frame_count == self.frame_limit:
            self.fps = self.frame_count / elapsed if elapsed > 0 else 0


class VerificationApplicationSingle(holoscan.core.Application):
    """Single camera verification application."""
    
    def __init__(
        self,
        cuda_context,
        cuda_device_ordinal,
        hololink_channel,
        camera,
        camera_mode,
        frame_limit,
        save_dir=None,
        max_saves=1,
        frames_to_save=None,
    ):
        super().__init__()
        self._cuda_context = cuda_context
        self._cuda_device_ordinal = cuda_device_ordinal
        self._hololink_channel = hololink_channel
        self._camera = camera
        self._camera_mode = camera_mode
        self._frame_limit = frame_limit
        self._save_dir = save_dir or DEFAULT_SAVE_DIR
        self._max_saves = max_saves
        self._frames_to_save = frames_to_save or []
        self._frame_counter = None
        self._image_saver = None
        self._hololink = None

    def compose(self):
        # Use CountCondition to limit frames
        self._count = holoscan.conditions.CountCondition(
            self,
            name="count",
            count=self._frame_limit,
        )
                
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
        
        # Receiver with CountCondition
        receiver_operator = hololink_module.operators.LinuxReceiverOp(
            self,
            self._count,
            name="receiver",
            frame_size=frame_size,
            frame_context=self._cuda_context,
            hololink_channel=self._hololink_channel,
            device=self._camera
        )
        
        self.add_flow(receiver_operator, csi_to_bayer_operator, {("output", "input")})
        
        # Image processor (matches verify_camera_imx274.py pipeline)
        pixel_format = self._camera.pixel_format()
        bayer_format = self._camera.bayer_format()
        
        image_processor_operator = hololink_module.operators.ImageProcessorOp(
            self,
            name="image_processor",
            optical_black=50,
            bayer_format=bayer_format.value,
            pixel_format=pixel_format.value,
        )
        
        # Bayer demosaic
        rgba_components_per_pixel = 4
        rgb_pool = holoscan.resources.BlockMemoryPool(
            self,
            name="rgb_pool",
            storage_type=1,
            block_size=self._camera._width 
            * self._camera._height 
            * rgba_components_per_pixel
            * ctypes.sizeof(ctypes.c_uint16),
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
        
        # Frame counter
        self._frame_counter = FrameCounterOp(
            self, 
            name="frame_counter",
            frame_limit=self._frame_limit,
            pass_through=True
        )
        
        # Visualizer
        visualizer = holoscan.operators.HolovizOp(
            self,
            name="holoviz",
            fullscreen=True,
            headless=False,
            framebuffer_srgb=True,
        )
        
        # Image saver
        self._image_saver = ImageSaverOp(
            self,
            name="image_saver",
            save_dir=self._save_dir,
            max_saves=self._max_saves,
            frames_to_save=self._frames_to_save,
            camera_name="imx274",
        )
        
        # Pipeline: CSI → ImageProcessor → BayerDemosaic → FrameCounter → Visualizer + ImageSaver
        self.add_flow(csi_to_bayer_operator, image_processor_operator, {("output", "input")})
        self.add_flow(image_processor_operator, bayer_to_rgb_operator, {("output", "receiver")})
        self.add_flow(bayer_to_rgb_operator, self._frame_counter, {("transmitter", "input")})
        self.add_flow(self._frame_counter, visualizer, {("output", "receivers")})
        self.add_flow(self._frame_counter, self._image_saver, {("output", "input")})

    def get_frame_count(self) -> int:
        return self._frame_counter.frame_count if self._frame_counter else 0
    
    def get_fps(self) -> float:
        return self._frame_counter.fps if self._frame_counter else 0.0
    
    def get_saved_count(self) -> int:
        return self._image_saver.saved_count if self._image_saver else 0
    
    def interrupt(self):
        try:
            if hasattr(super(), 'interrupt'):
                super().interrupt()
        except Exception as e:
            logging.warning(f"Error calling interrupt: {e}")

class VerificationApplicationStereo(holoscan.core.Application):
    """
    Stereo camera verification application.
    
    Uses ONE network interface to access BOTH sensors (0 and 1) on the same
    Bajoran SFP port. This matches test_imx274_stereo_single_interface architecture.
    """
    
    def __init__(
        self,
        cuda_context,
        cuda_device_ordinal,
        hololink_channel_left,
        camera_left,
        hololink_channel_right,
        camera_right,
        camera_mode,
        frame_limit,
        save_dir=None,
        max_saves=1,
        frames_to_save=None,
    ):
        super().__init__()
        self._cuda_context = cuda_context
        self._cuda_device_ordinal = cuda_device_ordinal
        self._hololink_channel_left = hololink_channel_left
        self._camera_left = camera_left
        self._hololink_channel_right = hololink_channel_right
        self._camera_right = camera_right
        self._camera_mode = camera_mode
        self._frame_limit = frame_limit
        self._save_dir = save_dir or DEFAULT_SAVE_DIR
        self._max_saves = max_saves
        self._frames_to_save = frames_to_save or []
        self._frame_counter_left = None
        self._frame_counter_right = None
        self._image_saver_left = None
        self._image_saver_right = None
        self._hololink = None
        
        # HSDK controls for stereo - avoid metadata conflicts
        self.is_metadata_enabled = True
        self.metadata_policy = holoscan.core.MetadataPolicy.REJECT

    def compose(self):
        # CountConditions for both cameras
        self._count_left = holoscan.conditions.CountCondition(
            self,
            name="count_left",
            count=self._frame_limit,
        )
        self._count_right = holoscan.conditions.CountCondition(
            self,
            name="count_right",
            count=self._frame_limit,
        )
        
        # Set SAME mode for BOTH cameras (shared clock requirement)
        self._camera_left.set_mode(self._camera_mode)
        self._camera_right.set_mode(self._camera_mode)
        
        # === SHARED MEMORY POOL for CSI (6 blocks for dual cameras) ===
        csi_to_bayer_pool = holoscan.resources.BlockMemoryPool(
            self,
            name="csi_pool",
            storage_type=1,
            block_size=self._camera_left._width * ctypes.sizeof(ctypes.c_uint16) * self._camera_left._height,
            num_blocks=6,  # More blocks for dual cameras
        )
        
        # === LEFT CAMERA PIPELINE ===
        csi_to_bayer_operator_left = hololink_module.operators.CsiToBayerOp(
            self,
            name="csi_to_bayer_left",
            allocator=csi_to_bayer_pool,
            cuda_device_ordinal=self._cuda_device_ordinal,
            out_tensor_name="left",  # Named tensor for holoviz
        )
        self._camera_left.configure_converter(csi_to_bayer_operator_left)
        
        frame_size_left = csi_to_bayer_operator_left.get_csi_length()
        
        receiver_operator_left = hololink_module.operators.LinuxReceiverOp(
            self,
            self._count_left,
            name="receiver_left",
            frame_size=frame_size_left,
            frame_context=self._cuda_context,
            hololink_channel=self._hololink_channel_left,
            device=self._camera_left
        )
        
        # Image processor for left camera (matches verify_camera_imx274.py pipeline)
        pixel_format_left = self._camera_left.pixel_format()
        bayer_format_left = self._camera_left.bayer_format()
        
        image_processor_operator_left = hololink_module.operators.ImageProcessorOp(
            self,
            name="image_processor_left",
            optical_black=50,
            bayer_format=bayer_format_left.value,
            pixel_format=pixel_format_left.value,
        )
        
        # === SHARED MEMORY POOL for demosaic (6 blocks for dual cameras) ===
        rgba_components_per_pixel = 4
        bayer_pool = holoscan.resources.BlockMemoryPool(
            self,
            name="bayer_pool",
            storage_type=1,
            block_size=self._camera_left._width 
            * self._camera_left._height 
            * rgba_components_per_pixel
            * ctypes.sizeof(ctypes.c_uint16),
            num_blocks=6,  # More blocks for dual cameras
        )
        
        bayer_to_rgb_operator_left = BayerDemosaicOp(
            self,
            name="bayer_to_rgb_left",
            pool=bayer_pool,
            generate_alpha=True,
            alpha_value=65535,
            bayer_grid_pos=bayer_format_left.value,
            interpolation_mode=0,
            in_tensor_name="left",
            out_tensor_name="left",
        )
        
        self._frame_counter_left = FrameCounterOp(
            self, 
            name="frame_counter_left",
            frame_limit=self._frame_limit,
            pass_through=True,
            name_prefix="LEFT"
        )
        
        self._image_saver_left = ImageSaverOp(
            self,
            name="image_saver_left",
            save_dir=self._save_dir,
            max_saves=self._max_saves,
            frames_to_save=self._frames_to_save,
            camera_name="left",
        )
        
        # === RIGHT CAMERA PIPELINE ===
        csi_to_bayer_operator_right = hololink_module.operators.CsiToBayerOp(
            self,
            name="csi_to_bayer_right",
            allocator=csi_to_bayer_pool,
            cuda_device_ordinal=self._cuda_device_ordinal,
            out_tensor_name="right",  # Named tensor for holoviz
        )
        self._camera_right.configure_converter(csi_to_bayer_operator_right)
        
        frame_size_right = csi_to_bayer_operator_right.get_csi_length()
        
        # Frame sizes must match (same mode for both cameras)
        assert frame_size_left == frame_size_right, f"Frame size mismatch: left={frame_size_left}, right={frame_size_right}"
        frame_size = frame_size_left
        
        receiver_operator_right = hololink_module.operators.LinuxReceiverOp(
            self,
            self._count_right,
            name="receiver_right",
            frame_size=frame_size,
            frame_context=self._cuda_context,
            hololink_channel=self._hololink_channel_right,
            device=self._camera_right
        )
        
        # Image processor for right camera (matches verify_camera_imx274.py pipeline)
        pixel_format_right = self._camera_right.pixel_format()
        bayer_format_right = self._camera_right.bayer_format()
        
        # Verify formats match between left and right cameras
        assert bayer_format_left == bayer_format_right, f"Bayer format mismatch: left={bayer_format_left}, right={bayer_format_right}"
        assert pixel_format_left == pixel_format_right, f"Pixel format mismatch: left={pixel_format_left}, right={pixel_format_right}"
        
        image_processor_operator_right = hololink_module.operators.ImageProcessorOp(
            self,
            name="image_processor_right",
            optical_black=50,
            bayer_format=bayer_format_right.value,
            pixel_format=pixel_format_right.value,
        )
        
        bayer_to_rgb_operator_right = BayerDemosaicOp(
            self,
            name="bayer_to_rgb_right",
            pool=bayer_pool,
            generate_alpha=True,
            alpha_value=65535,
            bayer_grid_pos=bayer_format_right.value,
            interpolation_mode=0,
            in_tensor_name="right",
            out_tensor_name="right",
        )
        
        self._frame_counter_right = FrameCounterOp(
            self, 
            name="frame_counter_right",
            frame_limit=self._frame_limit,
            pass_through=True,
            name_prefix="RIGHT"
        )
        
        self._image_saver_right = ImageSaverOp(
            self,
            name="image_saver_right",
            save_dir=self._save_dir,
            max_saves=self._max_saves,
            frames_to_save=self._frames_to_save,
            camera_name="right",
        )
        
        # === SIDE-BY-SIDE VISUALIZER ===
        left_spec = holoscan.operators.HolovizOp.InputSpec(
            "left", holoscan.operators.HolovizOp.InputType.COLOR
        )
        left_spec_view = holoscan.operators.HolovizOp.InputSpec.View()
        left_spec_view.offset_x = 0
        left_spec_view.offset_y = 0
        left_spec_view.width = 0.5
        left_spec_view.height = 1
        left_spec.views = [left_spec_view]

        right_spec = holoscan.operators.HolovizOp.InputSpec(
            "right", holoscan.operators.HolovizOp.InputType.COLOR
        )
        right_spec_view = holoscan.operators.HolovizOp.InputSpec.View()
        right_spec_view.offset_x = 0.5
        right_spec_view.offset_y = 0
        right_spec_view.width = 0.5
        right_spec_view.height = 1
        right_spec.views = [right_spec_view]

        visualizer = holoscan.operators.HolovizOp(
            self,
            name="holoviz",
            headless=False,
            fullscreen=True,
            tensors=[left_spec, right_spec],
            window_title="IMX274 Stereo Test Pattern",
            enable_camera_pose_output=False,
            framebuffer_srgb=True,
        )
        
        # === CONNECT PIPELINES ===
        # === CONNECT LEFT PIPELINE ===
        # CSI → ImageProcessor → BayerDemosaic → FrameCounter → Visualizer
        #                                     └→ ImageSaver (branched)
        self.add_flow(receiver_operator_left, csi_to_bayer_operator_left, {("output", "input")})
        self.add_flow(csi_to_bayer_operator_left, image_processor_operator_left, {("output", "input")})
        self.add_flow(image_processor_operator_left, bayer_to_rgb_operator_left, {("output", "receiver")})
        self.add_flow(bayer_to_rgb_operator_left, self._frame_counter_left, {("transmitter", "input")})
        self.add_flow(self._frame_counter_left, visualizer, {("output", "receivers")})
        
        # Branch image saver directly from demosaic (preserves named tensors)
        self.add_flow(bayer_to_rgb_operator_left, self._image_saver_left, {("transmitter", "input")})
        
        # === CONNECT RIGHT PIPELINE ===
        # CSI → ImageProcessor → BayerDemosaic → FrameCounter → Visualizer
        #                                     └→ ImageSaver (branched)
        self.add_flow(receiver_operator_right, csi_to_bayer_operator_right, {("output", "input")})
        self.add_flow(csi_to_bayer_operator_right, image_processor_operator_right, {("output", "input")})
        self.add_flow(image_processor_operator_right, bayer_to_rgb_operator_right, {("output", "receiver")})
        self.add_flow(bayer_to_rgb_operator_right, self._frame_counter_right, {("transmitter", "input")})
        self.add_flow(self._frame_counter_right, visualizer, {("output", "receivers")})
        
        # Branch image saver directly from demosaic (preserves named tensors)
        self.add_flow(bayer_to_rgb_operator_right, self._image_saver_right, {("transmitter", "input")})

    def get_frame_count(self) -> int:
        left = self._frame_counter_left.frame_count if self._frame_counter_left else 0
        right = self._frame_counter_right.frame_count if self._frame_counter_right else 0
        return min(left, right)  # Return minimum to ensure both cameras captured
    
    def get_fps(self) -> float:
        left = self._frame_counter_left.fps if self._frame_counter_left else 0.0
        right = self._frame_counter_right.fps if self._frame_counter_right else 0.0
        return (left + right) / 2  # Average FPS
    
    def get_saved_count(self) -> int:
        left = self._image_saver_left.saved_count if self._image_saver_left else 0
        right = self._image_saver_right.saved_count if self._image_saver_right else 0
        return left + right  # Total saved from both cameras
    
    def interrupt(self):
        try:
            if hasattr(super(), 'interrupt'):
                super().interrupt()
        except Exception as e:
            logging.warning(f"Error calling interrupt: {e}")


def _compute_img_fac(frame_limit: int, max_saves: int) -> list:
    """Compute which frame numbers to save, evenly distributed."""
    if max_saves <= 0 or frame_limit <= 0:
        return []
    interval = math.floor(frame_limit / (max_saves + 1))
    return [int((i+1) * interval) for i in range(max_saves)]


def verify_camera_functional(
    camera_ip: str = "192.168.0.2",
    stereo: bool = False,
    camera_mode: int = 0,
    pattern_left: str = "vbar",
    pattern_right: str = "vbar",
    log_level: int = logging.INFO,
) -> Tuple[bool, str, dict]:
    """
    Verify IMX274 test pattern against golden reference.
    
    Single Sensor Mode:
        Tests only sensor 0 on the specified IP address.
        
    Stereo Mode (--stereo):
        Tests BOTH sensor 0 and sensor 1 on the SAME IP address.
        This is the "stereo single interface" architecture where both
        sensors are accessed through one SFP port.
    
    Args:
        camera_ip: IP address of the SFP port (e.g., 192.168.0.2 or 192.168.0.3)
        stereo: Enable dual-sensor mode (sensor 0 + sensor 1 on same IP)
        camera_mode: Camera mode (0=4K60, 1=1080p60, etc.)
        pattern_left: Test pattern mode name for sensor 0 ('vbar' or 'hbar')
        pattern_right: Test pattern mode name for sensor 1 ('vbar' or 'hbar')
        log_level: Logging level
    
    Returns:
        Tuple of (success: bool, message: str, stats: dict)
    """
    
    # Hardcoded test parameters
    frame_limit = 100
    max_saves = 1
    timeout_seconds = 15
    save_dir = DEFAULT_SAVE_DIR
    
    # Map pattern names to IDs
    pattern_map = {"vbar": 10, "hbar": 11, "vbar4k": 10, "hbar4k": 11}
    
    # Store original pattern names for filename lookup
    pattern_name_left = pattern_left
    pattern_name_right = pattern_right
    
    # Convert to pattern IDs
    if pattern_left in pattern_map:
        pattern_left = pattern_map[pattern_left]
    if pattern_right in pattern_map:
        pattern_right = pattern_map[pattern_right] 
    
    frames_to_save = _compute_img_fac(frame_limit, max_saves)
    logging.info(f"Frames to save: {frames_to_save}")

    hololink_module.logging_level(log_level)
    
    mode_str = "DUAL-SENSOR (sensor 0 + sensor 1)" if stereo else "SINGLE-SENSOR (sensor 0 only)"
    logging.info("=" * 80)
    logging.info(f"Starting IMX274 Test Pattern Validation ({mode_str})")
    logging.info(f"SFP Port IP: {camera_ip}")
    logging.info(f"Camera Mode: {camera_mode}")
    if stereo:
        logging.info(f"Test patterns: Sensor 0 (left) = {pattern_name_left}, Sensor 1 (right) = {pattern_name_right}")
    else:
        logging.info(f"Test pattern: {pattern_name_left}")
    logging.info(f"Frame limit: {frame_limit}, Timeout: {timeout_seconds}s")
    logging.info(f"Image saving: {save_dir}")
    logging.info("=" * 80)
    
    # Create save directory
    try:
        os.makedirs(save_dir, exist_ok=True)
        logging.info(f"Created/verified save directory: {save_dir}")
    except Exception as e:
        return False, f"Failed to create save directory '{save_dir}': {str(e)}", {}
    
    hololink = None
    camera = None
    camera_left = None
    camera_right = None
    cu_context = None
    application = None
    app_thread = None
    
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
        
        camera_mode_enum = hololink_module.sensors.imx274.imx274_mode.Imx274_Mode(camera_mode)
        
        # Stereo mode bandwidth limitation: 10Gbps cannot support dual 4K cameras
        # Force 1080p60 (mode 1) for stereo, regardless of user input
        if stereo:
            camera_mode_enum = hololink_module.sensors.imx274.imx274_mode.Imx274_Mode(1)
        
        if pattern_name_left == "vbar":
            golden_filename_left = "golden_fhd_vbar_imx274.npy"
        elif pattern_name_left == "hbar":
            golden_filename_left = "golden_fhd_hbar_imx274.npy"
        elif pattern_name_left == "vbar4k":
            golden_filename_left = "golden_4k_vbar_imx274.npy"
        elif pattern_name_left == "hbar4k":
            golden_filename_left = "golden_4k_hbar_imx274.npy"

        if pattern_name_right == "vbar":
            golden_filename_right = "golden_fhd_vbar_imx274.npy"
        elif pattern_name_right == "hbar":
            golden_filename_right = "golden_fhd_hbar_imx274.npy"
        elif pattern_name_right == "vbar4k":
            golden_filename_right = "golden_4k_vbar_imx274.npy"
        elif pattern_name_right == "hbar4k":
            golden_filename_right = "golden_4k_hbar_imx274.npy"

        # Compare captured frame to golden reference
        golden_path_left = _PROJECT_ROOT / "CI_CD" / "images" / golden_filename_left
        golden_path_right = _PROJECT_ROOT / "CI_CD" / "images" / golden_filename_right
        
        # Early validation: Check if golden references exist BEFORE running capture
        # This fails fast if files are missing instead of wasting time on capture
        if stereo:
            if not golden_path_left.exists():
                return False, f"Golden reference not found for left camera: {golden_path_left}", {}
            if not golden_path_right.exists():
                return False, f"Golden reference not found for right camera: {golden_path_right}", {}
        else:
            if not golden_path_left.exists():
                return False, f"Golden reference not found: {golden_path_left}", {}

        def load_golden_reference(golden_path, save_dir_path, stats_dict, camera_name=""):
            """
            Load and compare captured image with golden reference.
            
            Args:
                golden_path: Path to golden reference .npy file
                save_dir_path: Directory containing captured .npy files
                stats_dict: Statistics dictionary to update
                camera_name: Optional camera identifier ("left", "right", or "")
            
            Returns:
                Tuple of (success, message, updated_stats)
            """
            # Load golden reference
            gold_img = np.load(golden_path)
            logging.info(f"[{camera_name}] Loaded golden reference: {golden_path}")
            logging.info(f"[{camera_name}]   Shape: {gold_img.shape}, dtype: {gold_img.dtype}")
            
            # Find captured .npy files for this camera
            from pathlib import Path as PathLib
            if camera_name:
                # For stereo: filter by camera name (left_*.npy or right_*.npy)
                pattern = f"{camera_name}_*.npy"
                npy_files = list(PathLib(save_dir_path).glob(pattern))
            else:
                # For single camera: get all .npy files
                npy_files = list(PathLib(save_dir_path).glob("*.npy"))
            
            if not npy_files:
                return False, f"No captured .npy files found in {save_dir_path} for {camera_name}", stats_dict
            
            # Get the newest file by modification time
            captured_file = max(npy_files, key=lambda x: x.stat().st_mtime)
            logging.info(f"[{camera_name}] Found {len(npy_files)} .npy files, loading newest: {captured_file.name}")
            
            captured_img = np.load(captured_file)
            logging.info(f"[{camera_name}] Loaded captured image: {captured_file.name}")
            logging.info(f"[{camera_name}]   Shape: {captured_img.shape}, dtype: {captured_img.dtype}")
            
            # Add metadata to stats
            prefix = f"{camera_name}_" if camera_name else ""
            stats_dict[f"{prefix}captured_shape"] = str(captured_img.shape)
            stats_dict[f"{prefix}captured_dtype"] = str(captured_img.dtype)
            stats_dict[f"{prefix}captured_size_bytes"] = captured_img.nbytes
            stats_dict[f"{prefix}golden_shape"] = str(gold_img.shape)
            stats_dict[f"{prefix}golden_dtype"] = str(gold_img.dtype)
            
            # Bit-by-bit comparison
            if captured_img.shape != gold_img.shape:
                stats_dict[f"{prefix}comparison_result"] = "shape_mismatch"
                return False, f"[{camera_name}] Shape mismatch: captured {captured_img.shape} vs golden {gold_img.shape}", stats_dict
            
            if captured_img.dtype != gold_img.dtype:
                stats_dict[f"{prefix}comparison_result"] = "dtype_mismatch"
                return False, f"[{camera_name}] Dtype mismatch: captured {captured_img.dtype} vs golden {gold_img.dtype}", stats_dict
            
            # Calculate total bits compared
            bits_per_element = captured_img.itemsize * 8
            total_elements = captured_img.size
            total_bits = total_elements * bits_per_element
            
            stats_dict[f"{prefix}total_elements_compared"] = total_elements
            stats_dict[f"{prefix}bits_per_element"] = bits_per_element
            stats_dict[f"{prefix}total_bits_compared"] = total_bits
            
            # Exact comparison
            is_exact_match = np.array_equal(captured_img, gold_img)
            
            if is_exact_match:
                stats_dict[f"{prefix}comparison_result"] = "exact_match"
                stats_dict[f"{prefix}identical_elements"] = total_elements
                stats_dict[f"{prefix}identical_rate_percent"] = 100.0
                logging.info(f"[{camera_name}] ✓ EXACT MATCH with golden reference")
                logging.info(f"[{camera_name}]   Total elements: {total_elements:,}, Total bits: {total_bits:,}")
                return True, f"[{camera_name}] Test pattern matches golden reference exactly", stats_dict
            else:
                diff_count = np.sum(captured_img != gold_img)
                identical_count = total_elements - diff_count
                identical_rate = 100.0 * (identical_count / total_elements)
                
                stats_dict[f"{prefix}comparison_result"] = "mismatch"
                stats_dict[f"{prefix}identical_elements"] = int(identical_count)
                stats_dict[f"{prefix}different_elements"] = int(diff_count)
                stats_dict[f"{prefix}identical_rate_percent"] = round(identical_rate, 4)
                
                logging.error(f"[{camera_name}] ✗ MISMATCH with golden reference")
                logging.error(f"[{camera_name}]   Identical: {identical_count:,}/{total_elements:,} ({identical_rate:.4f}%)")
                return False, f"[{camera_name}] Test pattern mismatch: {identical_rate:.4f}% identical (expected 100%)", stats_dict


        if stereo:
            # === STEREO MODE (Single Interface, Dual Sensors) ===
            # Access BOTH sensor 0 and sensor 1 on the SAME IP address
            # This matches test_imx274_stereo_single_interface architecture
            
            logging.info(f"Searching for Hololink device at {camera_ip}...")
            channel_metadata = hololink_module.Enumerator.find_channel(channel_ip=camera_ip)
            if not channel_metadata:
                return False, f"Failed to find Hololink device at {camera_ip}", {}
            
            logging.info("Hololink device found, configuring for dual sensors...")
            
            # Create separate channel metadata for each sensor on the SAME IP
            channel_metadata_left = hololink_module.Metadata(channel_metadata)
            hololink_module.DataChannel.use_sensor(channel_metadata_left, 0)  # Sensor 0
            
            channel_metadata_right = hololink_module.Metadata(channel_metadata)
            hololink_module.DataChannel.use_sensor(channel_metadata_right, 1)  # Sensor 1
            
            # Initialize data channels
            hololink_channel_left = hololink_module.DataChannel(channel_metadata_left)
            hololink_channel_right = hololink_module.DataChannel(channel_metadata_right)
            
            # Initialize cameras with expander configuration
            camera_left = hololink_module.sensors.imx274.dual_imx274.Imx274Cam(
                hololink_channel_left, expander_configuration=0
            )
            camera_right = hololink_module.sensors.imx274.dual_imx274.Imx274Cam(
                hololink_channel_right, expander_configuration=1
            )
            
            # Create stereo application
            application = VerificationApplicationStereo(
                cu_context,
                cu_device_ordinal,
                hololink_channel_left,
                camera_left,
                hololink_channel_right,
                camera_right,
                camera_mode_enum,
                frame_limit,
                save_dir=save_dir,
                max_saves=max_saves,
                frames_to_save=frames_to_save,
            )
            
            # Start hololink
            logging.info("Starting Hololink and cameras...")
            hololink = hololink_channel_left.hololink()
            assert hololink is hololink_channel_right.hololink(), "Both sensors must share same hololink"
            hololink.start()
            hololink.reset()
            
            application._hololink = hololink
            
            # Setup cameras (configure called AFTER application creates set_mode in compose)
            camera_left.setup_clock()  # Also sets camera_right's clock (shared)
            camera_left.configure(camera_mode_enum)
            camera_left.set_digital_gain_reg(0x4)
            
            camera_right.configure(camera_mode_enum)
            camera_right.set_digital_gain_reg(0x4)
            
            # Configure test patterns
            logging.info(f"Setting sensor 0 (left) test pattern: {pattern_left}")
            camera_left.test_pattern(pattern_left)
            
            logging.info(f"Setting sensor 1 (right) test pattern: {pattern_right}")
            camera_right.test_pattern(pattern_right)
            
            # Note: camera.start() not needed - application handles this
            
        else:
            # === SINGLE SENSOR MODE ===
            # Access only sensor 0 on the specified IP address
            
            logging.info(f"Searching for camera at {camera_ip}...")
            channel_metadata = hololink_module.Enumerator.find_channel(channel_ip=camera_ip)
            if not channel_metadata:
                return False, f"Failed to find camera at {camera_ip}", {}
            
            logging.info("Camera found")
            
            hololink_channel = hololink_module.DataChannel(channel_metadata)
            if camera_ip == "192.168.0.2":
                camera = hololink_module.sensors.imx274.dual_imx274.Imx274Cam(hololink_channel, expander_configuration=0)
            else:
                camera = hololink_module.sensors.imx274.dual_imx274.Imx274Cam(hololink_channel, expander_configuration=1)
            
            # Create single camera application
            application = VerificationApplicationSingle(
                cu_context,
                cu_device_ordinal,
                hololink_channel,
                camera,
                camera_mode_enum,
                frame_limit,
                save_dir=save_dir,
                max_saves=max_saves,
                frames_to_save=frames_to_save,
            )
            
            # Start hololink and camera
            logging.info("Starting Hololink and camera...")
            hololink = hololink_channel.hololink()
            hololink.start()
            hololink.reset()
            
            application._hololink = hololink
            
            # Configure camera (matches verify_camera_imx274.py sequence)
            camera.setup_clock()
            camera.configure(camera_mode_enum)
            camera.set_digital_gain_reg(0x4)  # Set digital gain for better brightness
            
            # Set test pattern (10=vbar, 11=hbar)
            logging.info(f"Setting test pattern: ID {pattern_left} ({pattern_name_left})")
            camera.test_pattern(pattern_left)
            
            # Note: camera.start() not needed - camera starts automatically with application
        
        # Run verification
        logging.info(f"Capturing {frame_limit} frames...")
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
            
            frames = application.get_frame_count()
            
            if frames > 0 and first_frame_time is None:
                first_frame_time = time.time()
                logging.info(f"First frame received after {time.time() - start_time:.2f}s")
            
            if frames > 0:
                last_frame_time = time.time()
            
            # Safety timeout: no new frames
            if last_frame_time is not None and (time.time() - last_frame_time) > timeout_seconds:
                logging.error(f"No new frames for {timeout_seconds}s, aborting...")
                try:
                    application.interrupt()
                except Exception as e:
                    logging.warning(f"Error interrupting app: {e}")
                break
            
            # Safety timeout: total time exceeded
            if (time.time() - start_wait) > max_wait_time:
                logging.error(f"Total wait time exceeded {max_wait_time}s, aborting...")
                try:
                    application.interrupt()
                except Exception as e:
                    logging.warning(f"Error interrupting app: {e}")
                break
        
        # Wait for thread to finish
        if app_thread.is_alive():
            logging.info("Waiting for application thread to finish...")
            app_thread.join(timeout=3.0)
            if app_thread.is_alive():
                logging.warning("Application thread still alive after 3s timeout")
        
        elapsed_time = time.time() - start_time
        saved_count = application.get_saved_count()
        
        logging.info(f"Capture complete: {saved_count} images saved in {elapsed_time:.2f}s")

        stats = {
            "camera_mode": camera_mode,
            "stereo": stereo,
            "save_dir": save_dir,
            "saved_images": saved_count,
        }
        
        # Check if frames were captured
        expected_saves = max_saves * (2 if stereo else 1)
        if saved_count < expected_saves:
            return False, f"Insufficient frames saved: {saved_count}/{expected_saves}", stats
        
        # === GOLDEN REFERENCE COMPARISON ===
        logging.info("=" * 80)
        logging.info("Starting golden reference comparison...")
        logging.info("=" * 80)
        
        if stereo:
            # Compare both left and right cameras against their respective golden references
            # Golden paths already set at lines 897-898 based on pattern names
            
            # Check if golden references exist
            if not golden_path_left.exists():
                logging.warning(f"Golden reference not found for left camera: {golden_path_left}")
                return True, f"Capture successful (golden reference not available for left camera)", stats
            
            if not golden_path_right.exists():
                logging.warning(f"Golden reference not found for right camera: {golden_path_right}")
                return True, f"Capture successful (golden reference not available for right camera)", stats
            
            # Compare left camera
            success_left, msg_left, stats = load_golden_reference(golden_path_left, save_dir, stats, camera_name="left")
            
            # Compare right camera
            success_right, msg_right, stats = load_golden_reference(golden_path_right, save_dir, stats, camera_name="right")
            
            # Both must pass
            if success_left and success_right:
                return True, "Both left and right test patterns match golden references exactly", stats
            elif not success_left and not success_right:
                return False, f"Both cameras failed: {msg_left}; {msg_right}", stats
            elif not success_left:
                return False, f"Left camera failed: {msg_left}", stats
            else:
                return False, f"Right camera failed: {msg_right}", stats
        else:
            # Single camera mode - compare against golden reference
            # Golden path already set at line 897 based on pattern name
            
            if not golden_path_left.exists():
                logging.warning(f"Golden reference not found: {golden_path_left}")
                return True, f"Capture successful (golden reference not available for comparison)", stats
            
            # Compare captured image with golden reference
            return load_golden_reference(golden_path_left, save_dir, stats, camera_name="")
        
    except Exception as e:
        logging.error(f"Verification failed with exception: {e}", exc_info=True)
        return False, f"Exception during verification: {str(e)}", {}
    
    finally:
        if hololink:
            try:
                logging.info("Stopping Hololink...")
                hololink.stop()
            except Exception as e:
                logging.error(f"Error stopping hololink: {e}", exc_info=True)
        
        if app_thread and app_thread.is_alive():
            logging.info("Waiting for application thread...")
            app_thread.join(timeout=5.0)
            if app_thread.is_alive():
                logging.error("Application thread still alive after 5s")
        
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


def main() -> Tuple[bool, str, dict]:
    parser = argparse.ArgumentParser(
        description="Verify IMX274 test pattern (single sensor or dual sensors on one SFP port)",
        epilog="""
Examples:
  # Test sensor 0 with vertical bar pattern (default)
  python verify_test_pattern_imx274.py --camera-ip 192.168.0.2 --camera-mode 1 --tp-mode1 vbar
  
  # Test both sensors (0 and 1) with different patterns
  python verify_test_pattern_imx274.py --stereo --camera-ip 192.168.0.2 --camera-mode 1 --tp-mode1 vbar --tp-mode2 hbar
  
  # Test both sensors on second SFP port  
  python verify_test_pattern_imx274.py --stereo --camera-ip 192.168.0.3 --camera-mode 1 --tp-mode1 hbar --tp-mode2 vbar
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--camera-ip", type=str, default="192.168.0.2", 
                       help="SFP port IP address (192.168.0.2 or 192.168.0.3)")
    parser.add_argument("--stereo", action="store_true",
                       help="Enable dual-sensor mode (sensor 0 + sensor 1 on same IP)")
    parser.add_argument("--camera-mode", type=int, default=0, 
                       help="Camera mode: 0=4K60fps, 1=1080p60fps, 2=1080p120fps")
    parser.add_argument("--tp-mode-left", type=str, default="vbar", choices=["vbar", "hbar", "vbar4k", "hbar4k"],
                       help="Test pattern for sensor 0: vbar=pattern 10, hbar=pattern 11, vbar4k, hbar4k")
    parser.add_argument("--tp-mode-right", type=str, default="vbar", choices=["vbar", "hbar", "vbar4k", "hbar4k"],
                       help="Test pattern for sensor 1 (stereo mode only): vbar=pattern 10, hbar=pattern 11, vbar4k, hbar4k")
    parser.add_argument("--log-level", type=int, default=logging.INFO, 
                       help="Logging level (10=DEBUG, 20=INFO, 30=WARNING)")

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=args.log_level,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    
    # Run verification
    success, message, stats = verify_camera_functional(
        camera_ip=args.camera_ip,
        stereo=args.stereo,
        camera_mode=args.camera_mode,
        pattern_left=args.tp_mode_left,
        pattern_right=args.tp_mode_right,
        log_level=args.log_level,
    )
    
    # Print summary
    print(tpf.header_footer(90, "IMX274 TEST PATTERN VALIDATION SUMMARY"))
    
    status = "✓ PASS" if success else "✗ FAIL"
    print(f"\n{status}: Test Pattern Comparison")
    print(f"  {message}")
    
    if stats:
        print("\n📊 Statistics:")
        for key, value in stats.items():
            print(f"  {key}: {value}")
    
    print("\n" + "=" * 90)
    
    return success, message, stats


if __name__ == "__main__":
    success, message, stats = main()
    if success:
        print(f"[PASS] {message}")
        sys.exit(0)
    else:
        print(f"[FAIL] {message}")
        sys.exit(1)
