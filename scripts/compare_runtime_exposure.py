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

# See README.md for detailed information.

import argparse
import ctypes
import logging

import holoscan
import cuda.bindings.driver as cuda

import hololink as hololink_module
import time

# PTP timestamp helper
def get_timestamp(metadata: dict, name: str) -> float:
    """Extract PTP timestamp from metadata (seconds + nanoseconds)."""
    s = metadata.get(f"{name}_s", 0)
    f = metadata.get(f"{name}_ns", 0)
    f *= 1.0 / 1000000000.0  # nanoseconds to seconds
    return s + f

class FrameCounterOp(holoscan.core.Operator):
    """Operator to count received frames and track timestamps.
    
    Includes warmup period - first 20 frames are discarded for stabilization.
    """
    
    def __init__(self, *args, frame_limit=50, pass_through=False, warmup_frames=20, **kwargs):
        self.pass_through = pass_through
        self.frame_limit = frame_limit  # User-requested frame count
        self.warmup_frames = warmup_frames  # Frames to discard at start
        self.frames_received = 0  # Total frames received (including warmup)
        self.frame_count = 0  # Counted frames (after warmup)
        self.start_time = None
        self.timestamps = []
        self.fps = 0.0
        
        # PTP timestamp storage
        self.ptp_acquisition_times = []  # Frame acquisition time (frame_end - frame_start)
        
        super().__init__(*args, **kwargs)
        
    def setup(self, spec):
        spec.input("input")
        if self.pass_through:
            spec.output("output")
        
    def compute(self, op_input, op_output, context):
        in_message = op_input.receive("input")
        self.frames_received += 1
        
        # Warmup period - discard first N frames silently
        if self.frames_received <= self.warmup_frames:
            if self.pass_through:
                op_output.emit(in_message, "output")
            return
        
        # Check if we've reached the user-requested frame limit (after warmup)
        if self.frame_count >= self.frame_limit:
            if self.pass_through:
                op_output.emit(in_message, "output")
            return
        
        # First real frame after warmup - start timing
        if self.start_time is None:
            self.start_time = time.time()
            logging.info(f"Warmup complete ({self.warmup_frames} frames discarded), starting measurement...")
        
        self.frame_count += 1
        self.timestamps.append(time.time())
        
        # Extract PTP timestamps for frame acquisition time measurement
        try:
            frame_start_s = get_timestamp(self.metadata, "timestamp")  # FPGA: first data byte
            frame_end_s = get_timestamp(self.metadata, "metadata")     # FPGA: last data byte + metadata
            
            # Debug: Log first frame metadata
            if self.frame_count == 1:
                logging.info(f"DEBUG: metadata keys = {list(self.metadata.keys()) if hasattr(self, 'metadata') else 'NO METADATA'}")
                logging.info(f"DEBUG: frame_start_s = {frame_start_s}, frame_end_s = {frame_end_s}")
            
            # Validate: frame_end > frame_start and difference is reasonable (< 100ms)
            # Accept both Unix epoch and PTP boot time domains - only the difference matters
            if frame_start_s > 0 and frame_end_s > frame_start_s:
                acquisition_time_ms = (frame_end_s - frame_start_s) * 1000  # Convert to ms
                
                # Sanity check: frame acquisition should be 3-100ms (catches corruption)
                if 3 < acquisition_time_ms < 100:
                    self.ptp_acquisition_times.append(acquisition_time_ms)
                    if self.frame_count == 1:
                        logging.info(f"[!] PTP acquisition time: {acquisition_time_ms:.3f}ms")
                elif self.frame_count == 1:
                    logging.warning(f"[!] Frame acquisition time out of range: {acquisition_time_ms:.3f}ms (expected 3-100ms)")
            elif self.frame_count == 1:
                logging.warning(f"[!] Invalid PTP ordering: start={frame_start_s}, end={frame_end_s}")
        except Exception as e:
            if self.frame_count == 1:
                logging.error(f"[X] Failed to read PTP timestamps: {e}")
        
        # Pass through if needed
        if self.pass_through:
            op_output.emit(in_message, "output")
                
        elapsed = time.time() - self.start_time
        fps = self.frame_count / elapsed if elapsed > 0 else 0

        if self.frame_count % 10 == 0:
            logging.info(f"Frames counted: {self.frame_count}/{self.frame_limit}, FPS: {fps:.2f}")

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
    
    def get_fps_stats(self):
        """Calculate max, average, and min instantaneous FPS from timestamps.
        
        Returns:
            dict with max_fps, avg_fps, min_fps
        """
        if len(self.timestamps) < 2:
            return {"max_fps": 0, "avg_fps": 0, "min_fps": 0}
        
        # Calculate instantaneous FPS between consecutive frames
        intervals = [self.timestamps[i+1] - self.timestamps[i] 
                    for i in range(len(self.timestamps) - 1)]
        
        # Convert intervals to FPS (1/interval)
        fps_values = [1.0 / interval for interval in intervals if interval > 0]
        
        if not fps_values:
            return {"max_fps": 0, "avg_fps": 0, "min_fps": 0}
        
        return {
            "max_fps": round(max(fps_values), 2),
            "avg_fps": round(sum(fps_values) / len(fps_values), 2),
            "min_fps": round(min(fps_values), 2)
        }
    
    def get_ptp_stats(self):
        """Calculate min, average, and max PTP frame acquisition times.
        
        Returns:
            dict with max_acq_ms, avg_acq_ms, min_acq_ms
        """
        if not self.ptp_acquisition_times:
            return {"max_acq_ms": 0, "avg_acq_ms": 0, "min_acq_ms": 0}
        
        return {
            "max_acq_ms": round(max(self.ptp_acquisition_times), 3),
            "avg_acq_ms": round(sum(self.ptp_acquisition_times) / len(self.ptp_acquisition_times), 3),
            "min_acq_ms": round(min(self.ptp_acquisition_times), 3)
        }

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
        self._frame_counter = None  # Will be created in compose()
        
        # Enable metadata access from C++ receiver (required for PTP timestamps)
        self.enable_metadata(True)


    def compose(self):
        logging.info("compose")
        
        # Add warmup frames to the actual count condition
        warmup_frames = 20
        actual_frame_count = self._frame_limit + warmup_frames if self._frame_limit else None
        
        if actual_frame_count:
            self._count = holoscan.conditions.CountCondition(
                self,
                name="count",
                count=actual_frame_count,  # User limit + warmup
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

        # Frame counter as terminal operator (monitoring only, no output)
        self._frame_counter = FrameCounterOp(
            self, 
            name="frame_counter",
            frame_limit=self._frame_limit if self._frame_limit else 999999,
            warmup_frames=warmup_frames,  # Discard first 20 frames
            pass_through=False  # Terminal operator - no downstream connection needed
        )

        visualizer = holoscan.operators.HolovizOp(
            self,
            name="holoviz",
            fullscreen=self._fullscreen,
            headless=self._headless,
            framebuffer_srgb=True,
        )

        
        self.add_flow(receiver_operator, self._frame_counter, {("output", "input")})
        self.add_flow(receiver_operator, csi_to_bayer_operator, {("output", "input")})
        self.add_flow(csi_to_bayer_operator, image_processor_operator, {("output", "input")})
        self.add_flow(image_processor_operator, demosaic, {("output", "receiver")})
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
    
    def get_frame_count(self):
        """Get current frame count from frame counter.
        
        Thread-safe: Can be called from main thread while application runs.
        
        Returns:
            int: Current frame count (after warmup), or 0 if not started
        """
        if self._frame_counter:
            return self._frame_counter.frame_count
        return 0


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
        default=600,
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
    )

    # Run it
    hololink = hololink_channel.hololink()
    
    # Storage for test results
    test_results = {}

    # =========================================================================== Normal Test ===========================================================================
    hololink.start()
    hololink.reset()
    camera_0.configure_mipi_lane(4, hololink_module.sensors.imx258.FULL_HD_LANE_RATE_MBPS)
    camera_0.configure(camera_mode)
    camera_0.set_focus(-300)
    camera_0.start()
    logging.info("Running normal test...")
    application.run()
    
    # Collect FPS stats from normal test
    if application._frame_counter:
        test_results['normal'] = {
            'fps': application._frame_counter.get_fps_stats(),
            'ptp': application._frame_counter.get_ptp_stats()
        }
        logging.info(f"Normal test stats: {test_results['normal']}")
    
    hololink.stop()

    # ============================================================================= Sleep ===============================================================================

    logging.info("Normal test complete, waiting 5 seconds before restarting for variable exposure test...")
    time.sleep(5)  # Short pause between tests

    # ====================================================================== Variable Exposure Test =====================================================================
    hololink.start()
    hololink.reset()
    camera_0.configure_mipi_lane(4, hololink_module.sensors.imx258.FULL_HD_LANE_RATE_MBPS)
    camera_0.configure(camera_mode)
    camera_0.set_focus(-300)
    camera_0.start()
    logging.info("Running variable exposure test...")
    # Run application in separate thread to allow runtime exposure changes
    # daemon=True allows clean exit when window is closed
    import threading
    app_thread = threading.Thread(target=application.run, daemon=True)
    app_thread.start()
    
    # Wait for app to initialize
    time.sleep(2)
    
    # Change exposure at specific frame numbers
    exposure_changes = [
        (100, 0x00FF),   # At frame 100, change to ultra low exposure
        (200, 0x0220),   # At frame 200, change to medium exposure
        (300, 0x0400),   # At frame 300, change to medium exposure
        (400, 0x05F0),   # At frame 400, change to high exposure
        (500, 0x0F00),   # At frame 500, change to ultra high exposure
    ]
    
    applied_changes = set()  # Track which changes have been applied
    
    while app_thread.is_alive():
        current_frame = application.get_frame_count()
        
        # Check if we should apply any exposure changes
        for frame_num, exposure_val in exposure_changes:
            if current_frame >= frame_num and frame_num not in applied_changes:
                logging.info(f"Frame {current_frame}: Changing exposure to {exposure_val:#06x}...")
                application.set_exposure(exposure_val)
                applied_changes.add(frame_num)
        
        # Small sleep to avoid busy-waiting
        time.sleep(0.1)
        
        # Break if all changes applied and near frame limit
        if len(applied_changes) == len(exposure_changes) and current_frame >= args.frame_limit - 10:
            break
    
    # Wait for thread to complete or timeout after window close
    try:
        app_thread.join(timeout=300)  # 5 minute timeout
        if app_thread.is_alive():
            logging.warning("Application still running after timeout, forcing exit...")
    except KeyboardInterrupt:
        logging.info("Interrupted by user (Ctrl+C)")
    
    # Collect FPS stats from variable exposure test
    if application._frame_counter:
        test_results['variable_exposure'] = {
            'fps': application._frame_counter.get_fps_stats(),
            'ptp': application._frame_counter.get_ptp_stats()
        }
        logging.info(f"Variable exposure stats: {test_results['variable_exposure']}")
    
    hololink.stop()

    # ========================================================================== Print Comparison Table ==========================================================================
    print("\n" + "="*80)
    print(f"PERFORMANCE COMPARISON TABLE FOR {args.frame_limit} FRAMES")
    print("="*80)
    print(f"{'Metric':<25} {'Normal':<20} {'Variable Exposure':<20} {'Percent Diff':<15}")
    print("-"*80)
    
    normal_stats = test_results.get('normal', {'fps': {'max_fps': 0, 'avg_fps': 0, 'min_fps': 0}, 'ptp': {'max_acq_ms': 0, 'avg_acq_ms': 0, 'min_acq_ms': 0}})
    var_stats = test_results.get('variable_exposure', {'fps': {'max_fps': 0, 'avg_fps': 0, 'min_fps': 0}, 'ptp': {'max_acq_ms': 0, 'avg_acq_ms': 0, 'min_acq_ms': 0}})
    
    normal_fps = normal_stats['fps']
    var_fps = var_stats['fps']
    normal_ptp = normal_stats['ptp']
    var_ptp = var_stats['ptp']
    
    def percent_diff(new, old):
        if old == 0:
            return 0.0
        return (new - old) / old * 100
    
    # FPS Metrics
    print("\nFPS Metrics:")
    print(f"{'  Max FPS':<25} {normal_fps['max_fps']:<20.2f} {var_fps['max_fps']:<20.2f} ({percent_diff(var_fps['max_fps'], normal_fps['max_fps']):+.2f}%)")
    print(f"{'  Avg FPS':<25} {normal_fps['avg_fps']:<20.2f} {var_fps['avg_fps']:<20.2f} ({percent_diff(var_fps['avg_fps'], normal_fps['avg_fps']):+.2f}%)")
    print(f"{'  Min FPS':<25} {normal_fps['min_fps']:<20.2f} {var_fps['min_fps']:<20.2f} ({percent_diff(var_fps['min_fps'], normal_fps['min_fps']):+.2f}%)")
    
    # PTP Acquisition Time Metrics
    print("\nPTP Frame Acquisition Time (ms):")
    print(f"{'  Max Acq Time':<25} {normal_ptp['max_acq_ms']:<20.3f} {var_ptp['max_acq_ms']:<20.3f} ({percent_diff(var_ptp['max_acq_ms'], normal_ptp['max_acq_ms']):+.2f}%)")
    print(f"{'  Avg Acq Time':<25} {normal_ptp['avg_acq_ms']:<20.3f} {var_ptp['avg_acq_ms']:<20.3f} ({percent_diff(var_ptp['avg_acq_ms'], normal_ptp['avg_acq_ms']):+.2f}%)")
    print(f"{'  Min Acq Time':<25} {normal_ptp['min_acq_ms']:<20.3f} {var_ptp['min_acq_ms']:<20.3f} ({percent_diff(var_ptp['min_acq_ms'], normal_ptp['min_acq_ms']):+.2f}%)")
    print("="*80)

    print("\nExposure test parameters:")
    for frame_num, exposure_val in exposure_changes:
        print(f"  Frame {frame_num}: Exposure set to {exposure_val:#06x}")
    print("="*80)


if __name__ == "__main__":
    main()
