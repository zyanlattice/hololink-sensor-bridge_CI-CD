# SPDX-FileCopyrightText: Copyright (c) 2024 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
IMX258 Camera Player with Automatic Exposure Control

This script provides real-time automatic exposure adjustment for IMX258 camera.

FEATURES:
    - Hierarchical auto-exposure algorithm with 3 priority levels:
      1. Prevent clipping (urgent) - React if >2% pixels saturated
      2. Optimize high percentiles - Target p99 in [180, 240] range
      3. Fine-tune median - Target p50 in [100, 140] range
    
    - Moving average smoothing to prevent jitter
    - Downsampling for performance (analyze every 4th pixel by default)
    - Shadow detail protection (p01 monitoring)
    - Configurable parameters via command-line

USAGE:
    Basic usage (auto-exposure enabled by default):
        python linux_AE_player_imx258.py
    
    Disable auto-exposure:
        python linux_AE_player_imx258.py --no-auto-exposure
    
    Custom auto-exposure tuning:
        python linux_AE_player_imx258.py \\
            --ae-target-p99-low 160 \\
            --ae-target-p99-high 220 \\
            --ae-target-median-low 90 \\
            --ae-target-median-high 130 \\
            --ae-saturation-threshold 0.01
    
    Faster adjustments (more aggressive):
        python linux_AE_player_imx258.py \\
            --ae-adjustment-interval 3 \\
            --ae-smoothing-window 3
    
    Fullscreen with auto-exposure:
        python linux_AE_player_imx258.py --fullscreen

ALGORITHM DETAILS:
    The auto-exposure operator analyzes each frame's luminance distribution
    and makes hierarchical decisions:
    
    Priority 1 (Clipping Prevention):
        if saturation_ratio > 2%:
            Decrease exposure by 30% (aggressive)
        elif saturation_ratio > 1%:
            Decrease exposure by 10% (gentle warning)
    
    Priority 2 (High Percentile Optimization):
        if p99 < 180:
            Increase exposure by 10%
        elif p99 > 240:
            Decrease exposure by 10%
    
    Priority 3 (Median Fine-tuning):
        if p50 < 100:
            Increase exposure by 5%
        elif p50 > 140:
            Decrease exposure by 5%
    
    Bonus (Shadow Detail):
        if p01 < 10 and p50 < 120:
            Increase exposure by 8% (lift shadows)
    
    Moving average smoothing prevents oscillation and frame-to-frame jitter.
    
    EXPOSURE RANGE:
    - Default initial: 0x0438 (1080 decimal) - IMX258 camera default
    - Meaningful range: 0x00FF to 0x0F00 (255 to 3840 decimal)
    - Outside this range, images become too dark or too bright
    - Algorithm will clamp to limits and warn if exceeded

PERFORMANCE:
    - Downsampling (4x) reduces analysis time by ~16x
    - Frame skipping (every 5 frames) minimizes pipeline blocking
    - Pass-through architecture ensures visualizer runs at full FPS
    - GPU→CPU transfer only for small downsampled region (~60KB vs 4MB)

MONITORING:
    Auto-exposure stats are printed every 10 seconds:
        [AE Stats] p99=215.3, p50=118.7, p01=8.2, sat=0.45%, adjustments=12
    
    Final summary printed on exit with optimization status.
"""

# See README.md for detailed information.

import argparse
import ctypes
import logging
import numpy as np

import holoscan
import cuda.bindings.driver as cuda

import hololink as hololink_module
import time


class AutoExposureOp(holoscan.core.Operator):
    """
    Automatic exposure control operator with hierarchical decision-making.
    
    Algorithm:
      1. Prevent clipping (priority) - React if >2% pixels saturated
      2. Optimize high percentiles - Target p99 in [180, 240] range
      3. Fine-tune median brightness - Target p50 in [100, 140] range
    
    Uses moving average smoothing and downsampling for performance.
    """
    
    def __init__(self, *args, 
                 camera=None, 
                 initial_exposure=0x0438,  # IMX258 default exposure value
                 target_p99_low=180,
                 target_p99_high=240,
                 target_median_low=100,
                 target_median_high=140,
                 saturation_threshold=0.02,  # 2% clipping threshold
                 smoothing_window=5,  # Moving average window
                 min_adjustment_interval=5,  # Frames between adjustments
                 enable_auto=True,  # Enable/disable auto exposure
                 min_exposure=0x00FF,  # Minimum meaningful exposure (tested)
                 max_exposure=0x0F00,  # Maximum meaningful exposure (tested)
                 downsample_factor=4,  # Analyze every Nth pixel for speed
                 **kwargs):
        super().__init__(*args, **kwargs)
        self.camera = camera
        self.target_p99_low = target_p99_low
        self.target_p99_high = target_p99_high
        self.target_median_low = target_median_low
        self.target_median_high = target_median_high
        self.saturation_threshold = saturation_threshold
        self.smoothing_window = smoothing_window
        self.min_adjustment_interval = min_adjustment_interval
        self.enable_auto = enable_auto
        self.min_exposure = min_exposure
        self.max_exposure = max_exposure
        self.downsample_factor = downsample_factor
        
        # State tracking - initialized with ACTUAL camera exposure value
        self.current_exposure = initial_exposure
        self.brightness_history = []  # For moving average
        self.frame_count = 0
        self.last_adjustment_frame = -min_adjustment_interval  # Allow first adjustment on frame 1
        
        logging.info(f"[AE] Initialized with exposure {self.current_exposure:#06x}")
        
        # Statistics (for monitoring)
        self.stats = {
            'last_p99': 0,
            'last_p50': 0,
            'last_p01': 0,
            'last_saturation_ratio': 0,
            'total_adjustments': 0,
        }
        
    def setup(self, spec):
        spec.input("input")
        spec.output("output")  # Pass-through to visualizer
        
    def compute(self, op_input, op_output, context):
        in_message = op_input.receive("input")
        self.frame_count += 1
        
        # CRITICAL: Pass through immediately to avoid blocking pipeline
        op_output.emit(in_message, "output")
        
        # Skip auto-exposure if disabled or adjusting too frequently
        if not self.enable_auto:
            return
            
        frames_since_last_adj = self.frame_count - self.last_adjustment_frame
        if frames_since_last_adj < self.min_adjustment_interval:
            return
        
        try:
            import cupy as cp
            
            # Get frame data from GPU
            tensor = in_message.get("")
            cuda_array = cp.asarray(tensor)
            
            # Debug: Log first frame analysis
            if self.frame_count == 1:
                logging.info(f"[AE] First frame analysis starting (current exposure: {self.current_exposure:#06x})")
            
            # OPTIMIZATION: Downsample for faster analysis (e.g., every 4th pixel = 16x faster)
            sampled = cuda_array[::self.downsample_factor, ::self.downsample_factor].copy()
            host_array = cp.asnumpy(sampled)
            
            # Calculate luminance from RGB/RGBA data
            # Input is RGBA uint16 from BayerDemosaicOp
            luminance = self._rgb_to_luminance(host_array)
            
            # Normalize to 0-255 range for consistent thresholds
            if luminance.max() > 255:
                luminance = (luminance / 65535.0 * 255).astype(np.uint8)
            else:
                luminance = luminance.astype(np.uint8)
            
            # Calculate brightness metrics
            metrics = self._analyze_brightness(luminance)
            
            # Update stats for monitoring
            self.stats.update({
                'last_p99': metrics['p99'],
                'last_p50': metrics['p50'],
                'last_p01': metrics['p01'],
                'last_saturation_ratio': metrics['saturation_ratio'],
            })
            
            # Debug: Log first few frames
            if self.frame_count <= 3:
                logging.info(f"[AE] Frame {self.frame_count} metrics: p99={metrics['p99']:.1f}, "
                            f"p50={metrics['p50']:.1f}, p01={metrics['p01']:.1f}, "
                            f"sat={metrics['saturation_ratio']*100:.2f}%")
            
            # Add to history for smoothing
            self.brightness_history.append(metrics)
            if len(self.brightness_history) > self.smoothing_window:
                self.brightness_history.pop(0)
            
            # Calculate smoothed metrics (moving average)
            smoothed = self._smooth_metrics(self.brightness_history)
            
            # Decide on exposure adjustment
            new_exposure = self._calculate_exposure(smoothed)
            
            # Apply if changed significantly (>1 unit difference = 0x0010)
            exposure_diff = abs(new_exposure - self.current_exposure)
            if exposure_diff >= 0x0010:
                self._apply_exposure(new_exposure)
                self.last_adjustment_frame = self.frame_count
                self.stats['total_adjustments'] += 1
                
        except Exception as e:
            # Don't crash pipeline on analysis errors
            logging.warning(f"AutoExposure analysis failed (frame {self.frame_count}): {e}")
    
    def _rgb_to_luminance(self, rgb_array):
        """Convert RGB/RGBA to luminance using ITU-R BT.601 weights.
        
        Args:
            rgb_array: Shape (H, W, C) where C is 3 or 4
        
        Returns:
            Grayscale array (H, W)
        """
        if rgb_array.ndim == 2:
            # Already grayscale
            return rgb_array
        
        # Extract RGB channels (ignore alpha if present)
        r = rgb_array[:, :, 0].astype(np.float32)
        g = rgb_array[:, :, 1].astype(np.float32)
        b = rgb_array[:, :, 2].astype(np.float32)
        
        # ITU-R BT.601 luma: Y = 0.299*R + 0.587*G + 0.114*B
        luminance = 0.299 * r + 0.587 * g + 0.114 * b
        
        return luminance
    
    def _analyze_brightness(self, luminance):
        """Analyze frame brightness metrics.
        
        Args:
            luminance: 2D array of brightness values (0-255)
        
        Returns:
            dict with p99, p50, p01, mean, saturation_ratio
        """
        return {
            'p99': np.percentile(luminance, 99),    # Bright regions
            'p50': np.percentile(luminance, 50),    # Median (robust to outliers)
            'p01': np.percentile(luminance, 1),     # Dark regions
            'mean': luminance.mean(),
            'saturation_ratio': (luminance >= 250).sum() / luminance.size,  # >250 = clipping
        }
    
    def _smooth_metrics(self, history):
        """Apply moving average smoothing to prevent jitter.
        
        Args:
            history: List of metric dictionaries
        
        Returns:
            Smoothed metrics dictionary
        """
        if not history:
            return {
                'p99': 128, 'p50': 128, 'p01': 0,
                'mean': 128, 'saturation_ratio': 0
            }
        
        # Average each metric across history window
        smoothed = {}
        for key in ['p99', 'p50', 'p01', 'mean', 'saturation_ratio']:
            values = [m[key] for m in history]
            smoothed[key] = sum(values) / len(values)
        
        return smoothed
    
    def _calculate_exposure(self, metrics):
        """Hierarchical exposure decision with three priority levels.
        
        Args:
            metrics: Smoothed brightness metrics
        
        Returns:
            New exposure value
        """
        current = self.current_exposure
        
        # ═══════════════════════════════════════════════════════════
        # PRIORITY 1: Prevent clipping (URGENT - aggressive response)
        # ═══════════════════════════════════════════════════════════
        if metrics['saturation_ratio'] > self.saturation_threshold:
            # Aggressive decrease to prevent further clipping
            new = int(current * 0.7)
            logging.info(f"[AE] CLIPPING DETECTED ({metrics['saturation_ratio']*100:.2f}%) → "
                        f"Exposure {current:#06x} → {new:#06x} (-30%)")
            return new
        
        elif metrics['saturation_ratio'] > self.saturation_threshold * 0.5:
            # Warning zone (1% saturation) - gentle decrease
            new = int(current * 0.9)
            logging.info(f"[AE] Near clipping ({metrics['saturation_ratio']*100:.2f}%) → "
                        f"Exposure {current:#06x} → {new:#06x} (-10%)")
            return new
        
        # ═══════════════════════════════════════════════════════════
        # PRIORITY 2: Optimize high percentiles (coarse adjustment)
        # ═══════════════════════════════════════════════════════════
        if metrics['p99'] < self.target_p99_low:
            # Bright regions too dark
            new = int(current * 1.1)
            logging.info(f"[AE] p99={metrics['p99']:.1f} < {self.target_p99_low} (too dark) → "
                        f"Exposure {current:#06x} → {new:#06x} (+10%)")
            return new
        
        elif metrics['p99'] > self.target_p99_high:
            # Bright regions too bright
            new = int(current * 0.9)
            logging.info(f"[AE] p99={metrics['p99']:.1f} > {self.target_p99_high} (too bright) → "
                        f"Exposure {current:#06x} → {new:#06x} (-10%)")
            return new
        
        # ═══════════════════════════════════════════════════════════
        # PRIORITY 3: Fine-tune median brightness (subtle adjustment)
        # ═══════════════════════════════════════════════════════════
        if metrics['p50'] < self.target_median_low:
            # Overall scene too dark
            new = int(current * 1.05)
            logging.info(f"[AE] p50={metrics['p50']:.1f} < {self.target_median_low} (median dark) → "
                        f"Exposure {current:#06x} → {new:#06x} (+5%)")
            return new
        
        elif metrics['p50'] > self.target_median_high:
            # Overall scene too bright
            new = int(current * 0.95)
            logging.info(f"[AE] p50={metrics['p50']:.1f} > {self.target_median_high} (median bright) → "
                        f"Exposure {current:#06x} → {new:#06x} (-5%)")
            return new
        
        # ═══════════════════════════════════════════════════════════
        # BONUS: Check shadow detail (p01)
        # ═══════════════════════════════════════════════════════════
        if metrics['p01'] < 10 and metrics['p50'] < 120:
            # Shadows crushed and overall not bright - lift exposure
            new = int(current * 1.08)
            logging.info(f"[AE] p01={metrics['p01']:.1f} (shadows crushed) → "
                        f"Exposure {current:#06x} → {new:#06x} (+8%)")
            return new
        
        # ═══════════════════════════════════════════════════════════
        # CHECK: Stuck at limits?
        # ═══════════════════════════════════════════════════════════
        # Warn if we're at exposure limits but scene is still suboptimal
        if current <= self.min_exposure and (metrics['p99'] < self.target_p99_low or metrics['p50'] < self.target_median_low):
            # At minimum exposure but scene is still too dark
            if self.frame_count % 30 == 0:  # Only warn every 30 frames to avoid spam
                logging.warning(f"[AE] At minimum exposure {current:#06x} but scene is dark "
                               f"(p99={metrics['p99']:.1f}, p50={metrics['p50']:.1f}). "
                               f"Consider increasing gain or improving lighting.")
        
        elif current >= self.max_exposure and (metrics['p99'] > self.target_p99_high or metrics['p50'] > self.target_median_high):
            # At maximum exposure but scene is still too bright
            if self.frame_count % 30 == 0:
                logging.warning(f"[AE] At maximum exposure {current:#06x} but scene is bright "
                               f"(p99={metrics['p99']:.1f}, p50={metrics['p50']:.1f}). "
                               f"Consider decreasing gain or reducing lighting.")
        
        # No change needed - exposure is optimal
        return current
    
    def _apply_exposure(self, new_exposure):
        """Apply exposure change to camera with safety clamping.
        
        Args:
            new_exposure: Requested exposure value
        """
        # Clamp to valid range
        clamped = max(self.min_exposure, min(self.max_exposure, new_exposure))
        
        # Warn if hitting limits
        if clamped != new_exposure:
            if clamped == self.min_exposure:
                logging.warning(f"[AE] Exposure clamped to minimum {clamped:#06x} (requested {new_exposure:#06x})")
            else:
                logging.warning(f"[AE] Exposure clamped to maximum {clamped:#06x} (requested {new_exposure:#06x})")
        
        # Don't apply if change is too small (< 0x0010 = 16 units)
        if abs(clamped - self.current_exposure) < 0x0010:
            return
        
        if self.camera:
            try:
                self.camera.set_exposure(clamped)
                self.current_exposure = clamped
            except Exception as e:
                logging.error(f"[AE] Failed to apply exposure {clamped:#06x}: {e}")
        else:
            logging.warning("[AE] Camera reference not set")
    
    def get_stats(self):
        """Get current auto-exposure statistics.
        
        Returns:
            dict with current metrics and adjustment count
        """
        return self.stats.copy()


class MicroApplication(holoscan.core.Application):
    def __init__(
        self,
        headless,
        fullscreen,
        cuda_context,
        cuda_device_ordinal,
        hololink_channel,
        camera,
        camera_mode,
        frame_limit,
        enable_auto_exposure=True,
        ae_params=None,
        initial_exposure=0x0438,  # ← NEW: Initial exposure value set on camera
    ):
        logging.info("__init__")
        super().__init__()
        self._headless = headless
        self._fullscreen = fullscreen
        self._cuda_context = cuda_context
        self._cuda_device_ordinal = cuda_device_ordinal
        self._hololink_channel = hololink_channel
        self._camera = camera
        self._camera_mode = camera_mode
        self._frame_limit = frame_limit
        self._enable_auto_exposure = enable_auto_exposure
        self._ae_params = ae_params or {}
        self._initial_exposure = initial_exposure  # Store for operator initialization
        self._auto_exposure_op = None  # Will be created in compose()

    def compose(self):
        logging.info("compose")
        if self._frame_limit:
            self._count = holoscan.conditions.CountCondition(
                self,
                name="count",
                count=self._frame_limit,
            )
            condition = self._count
        else:
            self._ok = holoscan.conditions.BooleanCondition(
                self, name="ok", enable_tick=True
            )
            condition = self._ok

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
        logging.info(f"{frame_size=}")
        frame_context = self._cuda_context
        receiver_operator = hololink_module.operators.LinuxReceiverOperator(
            self,
            condition,
            name="receiver",
            frame_size=frame_size,
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
        )

        # Auto-exposure operator (if enabled)
        if self._enable_auto_exposure:
            # Pass the initial exposure value that was set on camera
            self._auto_exposure_op = AutoExposureOp(
                self,
                name="auto_exposure",
                camera=self._camera,
                initial_exposure=self._initial_exposure,  # ← Use actual camera value
                enable_auto=True,
                **self._ae_params  # Pass user-defined parameters
            )
            logging.info(f"Auto-exposure ENABLED with params: {self._ae_params}")
        
        # Build pipeline flow
        self.add_flow(receiver_operator, csi_to_bayer_operator, {("output", "input")})
        self.add_flow(csi_to_bayer_operator, image_processor_operator, {("output", "input")})
        self.add_flow(image_processor_operator, demosaic, {("output", "receiver")})
        
        if self._enable_auto_exposure:
            # Insert auto-exposure between demosaic and visualizer
            self.add_flow(demosaic, self._auto_exposure_op, {("transmitter", "input")})
            self.add_flow(self._auto_exposure_op, visualizer, {("output", "receivers")})
        else:
            # Direct connection (no auto-exposure)
            self.add_flow(demosaic, visualizer, {("transmitter", "receivers")})


    def set_exposure(self, exposure):
        """Set exposure value directly on camera (immediate, no operator overhead).
        
        Thread-safe: Can be called from main thread while application runs.
        
        Args:
            exposure: Exposure register value (e.g., 0x0600)
        """
        if self._camera:
            try:
                self._camera.set_exposure(exposure)
                logging.info(f"Applied exposure: {exposure:#06x}")
            except Exception as e:
                logging.error(f"Failed to set exposure: {e}")
        else:
            logging.warning("Camera not initialized yet")
    
    def get_ae_stats(self):
        """Get current auto-exposure statistics.
        
        Returns:
            dict with metrics, or None if auto-exposure disabled
        """
        if self._auto_exposure_op:
            return self._auto_exposure_op.get_stats()
        return None


def main():
    parser = argparse.ArgumentParser()
    modes = hololink_module.sensors.imx258.Imx258_Mode
    mode_choices = [mode.value for mode in modes]
    mode_help = " ".join([f"{mode.value}:{mode.name}" for mode in modes])
    parser.add_argument(
        "--camera-mode",
        type=int,
        choices=mode_choices,
        default=mode_choices[0],
        help=mode_help,
    )
    parser.add_argument("--headless", action="store_true", help="Run in headless mode")
    parser.add_argument(
        "--fullscreen", action="store_true", help="Run in fullscreen mode"
    )
    parser.add_argument(
        "--frame-limit",
        type=int,
        default=None,
        help="Exit after receiving this many frames",
    )
    parser.add_argument(
        "--hololink",
        default="192.168.0.2",
        help="IP address of Hololink board",
    )
    parser.add_argument(
        "--log-level",
        type=int,
        default=20,
        help="Logging level to display",
    )
    
    # Auto-exposure parameters
    parser.add_argument(
        "--no-auto-exposure",
        action="store_true",
        help="Disable automatic exposure control"
    )
    parser.add_argument(
        "--ae-target-p99-low",
        type=int,
        default=180,
        help="Auto-exposure target p99 low threshold (0-255, default: 180)"
    )
    parser.add_argument(
        "--ae-target-p99-high",
        type=int,
        default=240,
        help="Auto-exposure target p99 high threshold (0-255, default: 240)"
    )
    parser.add_argument(
        "--ae-target-median-low",
        type=int,
        default=100,
        help="Auto-exposure target median low threshold (0-255, default: 100)"
    )
    parser.add_argument(
        "--ae-target-median-high",
        type=int,
        default=140,
        help="Auto-exposure target median high threshold (0-255, default: 140)"
    )
    parser.add_argument(
        "--ae-saturation-threshold",
        type=float,
        default=0.02,
        help="Auto-exposure saturation threshold (0-1, default: 0.02 = 2%%)"
    )
    parser.add_argument(
        "--ae-smoothing-window",
        type=int,
        default=5,
        help="Auto-exposure moving average window size (frames, default: 5)"
    )
    parser.add_argument(
        "--ae-adjustment-interval",
        type=int,
        default=5,
        help="Minimum frames between auto-exposure adjustments (default: 5)"
    )
    parser.add_argument(
        "--ae-min-exposure",
        type=lambda x: int(x, 0),  # Support hex (0x00FF) or decimal
        default=0x00FF,
        help="Auto-exposure minimum exposure value (hex or decimal, default: 0x00FF = 255)"
    )
    parser.add_argument(
        "--ae-max-exposure",
        type=lambda x: int(x, 0),
        default=0x0F00,
        help="Auto-exposure maximum exposure value (hex or decimal, default: 0x0F00 = 3840)"
    )
    parser.add_argument(
        "--ae-downsample",
        type=int,
        default=4,
        help="Auto-exposure downsample factor (analyze every Nth pixel, default: 4)"
    )
    parser.add_argument(
        "--initial-exposure",
        type=lambda x: int(x, 0),  # Support hex (0x0438) or decimal
        default=0x0438,
        help="Initial camera exposure value (hex or decimal, default: 0x0438 = IMX258 default)"
    )

    args = parser.parse_args()
    hololink_module.logging_level(args.log_level)
    logging.info("Initializing.")

    # Get a handle to the GPU
    (cu_result,) = cuda.cuInit(0)
    assert cu_result == cuda.CUresult.CUDA_SUCCESS
    cu_device_ordinal = 0
    cu_result, cu_device = cuda.cuDeviceGet(cu_device_ordinal)
    assert cu_result == cuda.CUresult.CUDA_SUCCESS
    cu_result, cu_context = cuda.cuDevicePrimaryCtxRetain(cu_device)
    assert cu_result == cuda.CUresult.CUDA_SUCCESS

    # Get a handle to the Hololink device
    channel_metadata = hololink_module.Enumerator.find_channel(channel_ip=args.hololink)
    hololink_channel = hololink_module.DataChannel(channel_metadata)

    # Get a handle to the camera
    camera_index = 0
    camera_0 = hololink_module.sensors.imx258.Imx258(hololink_channel, camera_index)
    camera_mode = hololink_module.sensors.imx258.Imx258_Mode(args.camera_mode)

    # Prepare auto-exposure parameters
    ae_params = {
        'target_p99_low': args.ae_target_p99_low,
        'target_p99_high': args.ae_target_p99_high,
        'target_median_low': args.ae_target_median_low,
        'target_median_high': args.ae_target_median_high,
        'saturation_threshold': args.ae_saturation_threshold,
        'smoothing_window': args.ae_smoothing_window,
        'min_adjustment_interval': args.ae_adjustment_interval,
        'min_exposure': args.ae_min_exposure,
        'max_exposure': args.ae_max_exposure,
        'downsample_factor': args.ae_downsample,
    }

    # Set up the application
    application = MicroApplication(
        args.headless,
        args.fullscreen,
        cu_context,
        cu_device_ordinal,
        hololink_channel,
        camera_0,
        camera_mode,
        args.frame_limit,
        enable_auto_exposure=not args.no_auto_exposure,
        ae_params=ae_params,
        initial_exposure=args.initial_exposure,  # Use user-specified initial exposure
    )

    # Run it
    hololink = hololink_channel.hololink()
    hololink.start()
    hololink.reset()

    camera_0.configure_mipi_lane(4, hololink_module.sensors.imx258.FULL_HD_LANE_RATE_MBPS)
    camera_0.configure(camera_mode)
    camera_0.set_focus(-140)
    version = camera_0.get_version()
    
    # Set initial exposure BEFORE starting camera (critical for auto-exposure)
    initial_exposure = args.initial_exposure
    camera_0.set_exposure(initial_exposure)
    logging.info(f"Set initial camera exposure to {initial_exposure:#06x}")
    
    # Also set reasonable gain and focus for better starting image
    camera_0.set_focus(-300)
    camera_0.set_analog_gain(0x0180)  # 1.5x gain for better brightness
    logging.info("Set focus=-300, analog_gain=0x0180")
    
    camera_0.start()
    
    # Log initial settings
    if not args.no_auto_exposure:
        logging.info("=" * 80)
        logging.info("AUTO-EXPOSURE ENABLED")
        logging.info("=" * 80)
        logging.info(f"  Initial exposure:  {args.initial_exposure:#06x}")
        logging.info(f"  Target p99 range:  [{ae_params['target_p99_low']}, {ae_params['target_p99_high']}]")
        logging.info(f"  Target median:     [{ae_params['target_median_low']}, {ae_params['target_median_high']}]")
        logging.info(f"  Saturation thresh: {ae_params['saturation_threshold']*100:.1f}%")
        logging.info(f"  Smoothing window:  {ae_params['smoothing_window']} frames")
        logging.info(f"  Adjustment rate:   Every {ae_params['min_adjustment_interval']} frames")
        logging.info(f"  Exposure range:    [{ae_params['min_exposure']:#06x}, {ae_params['max_exposure']:#06x}]")
        logging.info(f"  Downsample factor: {ae_params['downsample_factor']}x")
        logging.info("=" * 80)
    else:
        logging.info("Auto-exposure DISABLED - Manual control only")
    
    import threading
    app_thread = threading.Thread(target=application.run, daemon=True)
    app_thread.start()
    
    # Monitor auto-exposure stats (if enabled)
    if not args.no_auto_exposure:
        logging.info("Starting auto-exposure monitoring (prints every 10 seconds)...")
        last_stats_time = time.time()
        stats_interval = 10  # Print stats every 10 seconds
        
        while app_thread.is_alive():
            time.sleep(1)
            
            # Print stats periodically
            if time.time() - last_stats_time >= stats_interval:
                stats = application.get_ae_stats()
                if stats:
                    logging.info("─" * 80)
                    logging.info(f"[AE Stats] p99={stats['last_p99']:.1f}, "
                                f"p50={stats['last_p50']:.1f}, "
                                f"p01={stats['last_p01']:.1f}, "
                                f"sat={stats['last_saturation_ratio']*100:.2f}%, "
                                f"adjustments={stats['total_adjustments']}")
                    logging.info("─" * 80)
                last_stats_time = time.time()
    
    # Wait for thread to complete or timeout after window close
    try:
        app_thread.join(timeout=300)  # 5 minute timeout
        if app_thread.is_alive():
            logging.warning("Application still running after timeout, forcing exit...")
    except KeyboardInterrupt:
        logging.info("Interrupted by user (Ctrl+C)")
    
    # Print final auto-exposure summary
    if not args.no_auto_exposure:
        stats = application.get_ae_stats()
        if stats:
            logging.info("\n" + "=" * 80)
            logging.info("AUTO-EXPOSURE FINAL SUMMARY")
            logging.info("=" * 80)
            logging.info(f"  Total adjustments made: {stats['total_adjustments']}")
            logging.info(f"  Final brightness metrics:")
            logging.info(f"    p99 (bright regions):    {stats['last_p99']:.1f}")
            logging.info(f"    p50 (median):            {stats['last_p50']:.1f}")
            logging.info(f"    p01 (dark regions):      {stats['last_p01']:.1f}")
            logging.info(f"    Saturation ratio:        {stats['last_saturation_ratio']*100:.2f}%")
            
            # Check if final exposure is in target range
            in_target = (ae_params['target_p99_low'] <= stats['last_p99'] <= ae_params['target_p99_high'] and
                        ae_params['target_median_low'] <= stats['last_p50'] <= ae_params['target_median_high'])
            status = "✓ OPTIMAL" if in_target else "⚠ SUBOPTIMAL"
            logging.info(f"  Exposure status: {status}")
            logging.info("=" * 80)

    hololink.stop()


if __name__ == "__main__":
    main()
