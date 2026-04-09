#!/usr/bin/env python3
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
IMX258 Camera Player with Hardware ISP (Argus ISP)

This script demonstrates using the hardware-accelerated Argus ISP operator
instead of the software CUDA-based image processing pipeline.

HARDWARE ISP vs SOFTWARE ISP:
    Software (normal):  Receiver → CsiToBayer → ImageProcessor → BayerDemosaic → Holoviz
    Hardware (Argus):   Receiver → CsiToBayer → ArgusIsp → Holoviz
    
    Hardware ISP advantages:
    - Single operator (simplified pipeline)
    - Hardware-accelerated processing
    - Native ISP parameters (exposure_time_ms, analog_gain, pixel_bit_depth)
    - 3 RGB components (vs 4 RGBA in software)
    
USAGE:
    Basic usage (Mode 0, 60fps):
        python linux_hwisp_imx258_player.py
    
    Different camera mode:
        python linux_hwisp_imx258_player.py --camera-mode 1  # 30fps mode
    
    Fullscreen display:
        python linux_hwisp_imx258_player.py --fullscreen
    
    Custom camera IP:
        python linux_hwisp_imx258_player.py --hololink 192.168.0.10
    
    Multiple camera IDs:
        python linux_hwisp_imx258_player.py --camera-id 1
    
    Frame limit (for testing):
        python linux_hwisp_imx258_player.py --frame-limit 100

CAMERA MODES (IMX258):
    Mode 0: 1920x1080 @ 60fps
    Mode 1: 1920x1080 @ 30fps
    Mode 2: 1920x1080 @ 60fps (custom)
    Mode 3: 1920x1080 @ 30fps (custom)
    Mode 4: 1920x1080 @ 60fps (new)
    Mode 5: 4K @ 30fps

ARGUS ISP PARAMETERS:
    - exposure_time_ms: Frame time in milliseconds (default: 16.67ms for 60fps)
    - analog_gain: ISP analog gain multiplier (default: 10.0)
    - pixel_bit_depth: Pixel bit depth (default: 10 for RAW10)
    - bayer_format: Bayer pattern format (auto-detected from camera)

PERFORMANCE:
    Hardware ISP typically provides faster processing with lower CPU/GPU usage
    compared to software CUDA-based demosaicing.
"""

import argparse
import ctypes
import logging

import holoscan
import cuda.bindings.driver as cuda
from holoscan.resources import UnboundedAllocator

import hololink as hololink_module


class HardwareIspApplication(holoscan.core.Application):
    """
    IMX258 camera player using hardware-accelerated Argus ISP.
    
    Pipeline: Receiver → CsiToBayer → ArgusIsp → Holoviz
    """
    
    def __init__(
        self,
        headless,
        fullscreen,
        cuda_context,
        cuda_device_ordinal,
        hololink_channel,
        camera,
        camera_mode,
        frame_limit=None,
    ):
        super().__init__()
        self._cuda_context = cuda_context
        self._headless = headless
        self._fullscreen = fullscreen
        self._cuda_device_ordinal = cuda_device_ordinal
        self._hololink_channel = hololink_channel
        self._camera = camera
        self._camera_mode = camera_mode
        self._frame_limit = frame_limit

    def compose(self):
        # Use CountCondition if frame limit specified, otherwise run continuously
        if self._frame_limit:
            count = holoscan.conditions.CountCondition(
                self,
                name="count",
                count=self._frame_limit,
            )
        else:
            count = holoscan.conditions.BooleanCondition(
                self, name="ok", enable_tick=True
            )

        # CSI to Bayer conversion (same as software pipeline)
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
        
        
        # Receiver operator (receives frames from camera)
        receiver_operator = hololink_module.operators.LinuxReceiverOperator(
            self,
            count,
            name="receiver",
            frame_size=frame_size,
            frame_context=self._cuda_context,
            hololink_channel=self._hololink_channel,
            device=self._camera
        )
        
        # Hardware ISP (Argus ISP) - replaces ImageProcessor + BayerDemosaic
        pixel_format = self._camera.pixel_format()
        bayer_format = self._camera.bayer_format()
        
        # Pool for ISP output (3 RGB components, no alpha)
        rgb_components_per_pixel = 3  # Hardware ISP outputs RGB (no alpha)
        isp_pool = holoscan.resources.BlockMemoryPool(
            self,
            name="isp_pool",
            storage_type=1,
            block_size=self._camera._width 
            * self._camera._height 
            * rgb_components_per_pixel
            * ctypes.sizeof(ctypes.c_uint16),
            num_blocks=2,
        )
        
        # ArgusIspOp - hardware-accelerated ISP
        # Parameters tuned for IMX258 camera
        argus_isp = hololink_module.operators.ArgusIspOp(
            self,
            name="argus_isp",
            bayer_format=bayer_format.value,
            exposure_time_ms=27.77,      # 36fps frame time (1/36 = 0.02777s)
            analog_gain=10.0,             # Analog gain multiplier
            pixel_bit_depth=10,           # RAW10 format (10-bit per pixel)
            pool=isp_pool,
        )
        
        # Visualizer (display output)
        visualizer = holoscan.operators.HolovizOp(
            self,
            name="holoviz",
            fullscreen=self._fullscreen,
            headless=self._headless,
            framebuffer_srgb=True,
        )
        
        # Connect pipeline: Receiver → CsiToBayer → ArgusIsp → Holoviz
        self.add_flow(receiver_operator, csi_to_bayer_operator, {("output", "input")})
        self.add_flow(csi_to_bayer_operator, argus_isp, {("output", "input")})
        self.add_flow(argus_isp, visualizer, {("output", "receivers")})


def main():
    parser = argparse.ArgumentParser(
        description="IMX258 Camera Player with Hardware ISP (Argus ISP)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    # Camera configuration
    parser.add_argument(
        "--hololink",
        type=str,
        default="192.168.0.2",
        help="IP address of the Hololink device (default: 192.168.0.2)",
    )
    parser.add_argument(
        "--camera-id",
        type=int,
        default=0,
        choices=[0, 1],
        help="Camera ID (0 or 1, default: 0)",
    )
    parser.add_argument(
        "--camera-mode",
        type=int,
        default=0,
        help="Camera mode (0=60fps, 1=30fps, etc., default: 0)",
    )
    
    # Display options
    parser.add_argument(
        "--fullscreen",
        action="store_true",
        default=False,
        help="Run in fullscreen mode",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=False,
        help="Run in headless mode (no display, for testing)",
    )
    
    # Frame limit (for testing)
    parser.add_argument(
        "--frame-limit",
        type=int,
        default=None,
        help="Number of frames to capture before exiting (default: continuous)",
    )
    
    # MIPI configuration
    parser.add_argument(
        "--lane-num",
        type=int,
        default=4,
        help="Number of MIPI lanes (default: 4)",
    )
    parser.add_argument(
        "--lane-rate",
        type=int,
        default=371,
        help="MIPI lane rate in Mbps (default: 371)",
    )
    
    # Debugging
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--list-modes",
        action="store_true",
        help="List available camera modes and exit",
    )
    
    args = parser.parse_args()
    
    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    hololink_module.logging_level(log_level)
    
    # List modes if requested
    if args.list_modes:
        print("Available IMX258 Camera Modes:")
        for mode in hololink_module.sensors.imx258.Imx258_Mode:
            print(f"  {mode.value}: {mode.name}")
        return
    
    logging.info("=" * 80)
    logging.info("IMX258 Hardware ISP Player (Argus ISP)")
    logging.info(f"Camera IP: {args.hololink}")
    logging.info(f"Camera ID: {args.camera_id}")
    logging.info(f"Camera Mode: {args.camera_mode}")
    logging.info(f"MIPI Lanes: {args.lane_num}, Lane Rate: {args.lane_rate} Mbps")
    if args.frame_limit:
        logging.info(f"Frame Limit: {args.frame_limit}")
    logging.info("=" * 80)
    
    # Initialize CUDA
    logging.info("Initializing CUDA...")
    (cu_result,) = cuda.cuInit(0)
    if cu_result != cuda.CUresult.CUDA_SUCCESS:
        logging.error(f"CUDA initialization failed: {cu_result}")
        return
    
    cu_device_ordinal = 0
    cu_result, cu_device = cuda.cuDeviceGet(cu_device_ordinal)
    if cu_result != cuda.CUresult.CUDA_SUCCESS:
        logging.error(f"Failed to get CUDA device: {cu_result}")
        return
    
    cu_result, cu_context = cuda.cuDevicePrimaryCtxRetain(cu_device)
    if cu_result != cuda.CUresult.CUDA_SUCCESS:
        logging.error(f"Failed to create CUDA context: {cu_result}")
        return
    
    logging.info("CUDA initialized successfully")
    
    # Find Hololink device
    logging.info(f"Searching for Hololink device at {args.hololink}...")
    
    # Retry logic to handle "Interrupted system call" errors
    max_retries = 3
    retry_delay = 0.5
    channel_metadata = None
    
    for attempt in range(max_retries):
        try:
            channel_metadata = hololink_module.Enumerator.find_channel(channel_ip=args.hololink)
            if channel_metadata:
                break
            logging.warning(f"Device not found at {args.hololink}, attempt {attempt + 1}/{max_retries}")
        except RuntimeError as e:
            if "Interrupted system call" in str(e) and attempt < max_retries - 1:
                logging.warning(f"Interrupted system call on attempt {attempt + 1}/{max_retries}, retrying after {retry_delay}s delay...")
                import time
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                raise
    
    if not channel_metadata:
        logging.error(f"Failed to find Hololink device at {args.hololink} after {max_retries} attempts")
        return
    
    logging.info("Hololink device found")
    
    # Initialize IMX258 camera
    logging.info("Initializing IMX258 camera...")
    hololink_channel = hololink_module.DataChannel(channel_metadata)
    camera = hololink_module.sensors.imx258.Imx258(hololink_channel, args.camera_id)
    camera_mode = hololink_module.sensors.imx258.Imx258_Mode(args.camera_mode)
    
    # Create application
    logging.info("Creating hardware ISP application...")
    app = HardwareIspApplication(
        headless=args.headless,
        fullscreen=args.fullscreen,
        cuda_context=cu_context,
        cuda_device_ordinal=cu_device_ordinal,
        hololink_channel=hololink_channel,
        camera=camera,
        camera_mode=camera_mode,
        frame_limit=args.frame_limit,
    )
    
    # Start Hololink (must be done BEFORE camera configuration)
    logging.info("Starting Hololink...")
    hololink = hololink_channel.hololink()
    hololink.start()
    hololink.reset()
    
    # Configure MIPI lanes (IMX258-specific)
    logging.info(f"Configuring MIPI: {args.lane_num} lanes @ {args.lane_rate} Mbps")
    camera.configure_mipi_lane(args.lane_num, args.lane_rate)
    
    # Configure camera mode
    logging.info(f"Configuring camera mode: {camera_mode.name}")
    camera.configure(camera_mode)
    
    camera.set_register(0x600, 0x0)  # Normal operation
    camera.set_register(0x601, 0x0)  # Disable test pattern

    # Get camera version
    version = camera.get_version()
    logging.info(f"Camera version: {version}")
    
    # Set focus (optional, adjust as needed)
    camera.set_focus(-250)
    logging.info("Focus set to -250")
    
    # Set exposure and gain for better brightness
    # Exposure: 0x0150 (336 lines)
    # Analog gain: 0x0050 (80 = 0.5x gain = -6dB)
    camera.set_exposure(0x0150)
    camera.set_analog_gain(0x0050)
    logging.info("Exposure set to 0x0150, Analog gain set to 0x0050")
    
    # Start camera (IMX258-specific, required before capturing frames)
    logging.info("Starting camera...")
    camera.start()
    
    try:
        logging.info("Starting pipeline...")
        app.run()
        logging.info("Pipeline completed successfully")
    except KeyboardInterrupt:
        logging.info("Interrupted by user")
    except Exception as e:
        logging.error(f"Application error: {e}", exc_info=True)
    finally:
        # Cleanup
        logging.info("Cleaning up...")
        try:
            hololink.stop()
        except Exception as e:
            logging.warning(f"Error stopping hololink: {e}")
        
        try:
            hololink_module.Hololink.reset_framework()
        except Exception as e:
            logging.warning(f"Error resetting framework: {e}")
        
        try:
            cuda.cuCtxDestroy(cu_context)
        except Exception as e:
            logging.warning(f"Error destroying CUDA context: {e}")
        
        logging.info("Cleanup complete")


if __name__ == "__main__":
    main()
