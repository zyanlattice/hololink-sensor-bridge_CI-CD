# Hololink Implementation Best Practices Guide

**Last Updated:** January 2026  
**Purpose:** Consolidated best practices for reliable Hololink camera system implementation, cleanup procedures, and common patterns.

---

## Table of Contents

1. [Device Lifecycle Management](#device-lifecycle-management)
2. [Memory and Resource Management](#memory-and-resource-management)
3. [Frame Handling Patterns](#frame-handling-patterns)
4. [Multi-Mode Operation](#multi-mode-operation)
5. [Performance Optimization](#performance-optimization)
6. [Error Recovery](#error-recovery)
7. [Debugging Techniques](#debugging-techniques)

---

## Device Lifecycle Management

### Critical Cleanup Sequence

**Problem:** Improper cleanup causes frame contamination in subsequent runs. The order matters!

```python
def shutdown_gracefully(hololink_device, app_thread, cuda_context):
    """
    Proper cleanup sequence to prevent frame leakage to next run
    
    MUST be called in this exact order:
    1. Stop device (closes socket, unblocks receiver)
    2. Wait for application to finish
    3. Reset Hololink framework (clears global state)
    4. Destroy CUDA context
    """
    
    try:
        # Step 1: Stop the device
        # This closes the control socket and allows receiver to exit
        hololink_device.stop()
        print("✓ Device stopped")
        
        # Step 2: Wait for GXF application to finish
        # Timeout ensures we don't hang forever if something crashes
        success = app_thread.join(timeout=5.0)
        if success is None:
            print("⚠ Application thread did not exit within timeout")
        else:
            print("✓ Application thread finished")
        
        # Step 3: CRITICAL - Reset Hololink framework
        # This clears the global device registry that caches network packets
        # Without this, buffered frames from previous run contaminate next run
        from hololink import Hololink
        Hololink.reset_framework()
        print("✓ Hololink framework reset")
        
        # Step 4: Destroy CUDA context (if using GPU)
        # Only after framework reset, since reset might access CUDA
        import pycuda.driver as cuda
        cuda.cuCtxDestroy(cuda_context)
        print("✓ CUDA context destroyed")
        
    except Exception as e:
        print(f"⚠ Cleanup error (non-fatal): {e}")


def safe_camera_operation(mode, frame_limit=300):
    """Example of complete safe camera operation"""
    
    import pycuda.driver as cuda
    from hololink import Enumerator, sensors
    
    cuda_context = None
    app_thread = None
    hololink = None
    
    try:
        # Initialize CUDA
        cuda.cuInit(0)
        device = cuda.Device(0)
        cuda_context = device.make_context()
        
        # Find device
        hololink = Enumerator.find_channel(
            channel_ip="192.168.0.2",
            timeout_s=5.0
        )
        print(f"✓ Connected to {hololink.device_ip}")
        
        # Configure camera
        camera = sensors.imx258.Imx258(hololink, camera_id=0)
        camera.configure(mode=mode)
        camera.start()
        print(f"✓ Camera mode {mode} started")
        
        # Create and run application in thread
        from threading import Thread
        app = create_holoscan_app(mode, frame_limit)
        app_thread = Thread(target=app.run, daemon=False)
        app_thread.start()
        print("✓ Application started")
        
        # Wait for completion
        app_thread.join(timeout=60.0)
        
        return True
        
    except Exception as e:
        print(f"✗ Error during operation: {e}")
        return False
        
    finally:
        # Cleanup in correct order
        if hololink:
            shutdown_gracefully(hololink, app_thread, cuda_context)


if __name__ == "__main__":
    success = safe_camera_operation(mode=4, frame_limit=300)
    sys.exit(0 if success else 1)
```

### Why Order Matters

```
CORRECT ORDER:
┌─────────────────────────────────────────────────┐
│ 1. hololink.stop()                              │
│    └─ Closes socket, receiver thread unblocks  │
│                                                 │
│ 2. app_thread.join()                            │
│    └─ Waits for GXF graph to clean up          │
│                                                 │
│ 3. Hololink.reset_framework()  ← CRITICAL!     │
│    └─ Clears device registry                   │
│    └─ Flushes cached packets                   │
│                                                 │
│ 4. cuda.cuCtxDestroy()                          │
│    └─ Releases GPU memory                      │
└─────────────────────────────────────────────────┘

WRONG ORDER (causes problems):
┌─────────────────────────────────────────────────┐
│ ✗ cuda.cuCtxDestroy() first                    │
│   → GPU resources still in use, crash           │
│                                                 │
│ ✗ Hololink.reset_framework() first              │
│   → Application still trying to receive frames  │
│   → Frames contaminate next run                │
│                                                 │
│ ✗ app_thread.join() last                        │
│   → Device already stopped, thread hangs       │
└─────────────────────────────────────────────────┘
```

---

## Memory and Resource Management

### Block Memory Pool Configuration

**Problem:** Incorrect pool size causes HolovizOp black screen or crashes.

```python
from holoscan.operators import BayerDemosaicOp
from holoscan.core import BlockMemoryPool
from cupy.core.dlpack import numpy_to_dlpack

# For RGB output (image saving)
width, height = 1920, 1080
rgb_bytes_per_pixel = 3 * 2  # 3 channels × 2 bytes (uint16)

rgb_pool = BlockMemoryPool(
    block_size=width * height * rgb_bytes_per_pixel,  # = 12,441,600 bytes
    num_blocks=10  # Allocate 10 frames worth
)

# For RGBA output (visualization)
rgba_bytes_per_pixel = 4 * 2  # 4 channels × 2 bytes (uint16)

rgba_pool = BlockMemoryPool(
    block_size=width * height * rgba_bytes_per_pixel,  # = 16,588,800 bytes
    num_blocks=5  # Allocate 5 frames worth
)

# Use pools when creating operators
demosaic_rgb = BayerDemosaicOp(
    self,
    name="bayer_to_rgb",
    pool=rgb_pool,
    generate_alpha=False,  # RGB mode
    bayer_grid_pos=0  # RGGB format
)

demosaic_rgba = BayerDemosaicOp(
    self,
    name="bayer_to_rgba",
    pool=rgba_pool,
    generate_alpha=True,   # RGBA mode
    alpha_value=65535,     # Full opacity
    bayer_grid_pos=0
)
```

### GPU Memory Layout

```
Mode 4 (1920×1080@60fps):
┌─────────────────────────────────────────┐
│ GPU Memory Layout (BlockMemoryPool)     │
├─────────────────────────────────────────┤
│ Block 1: [1920×1080 RGBA uint16]        │
│          = 1920 × 1080 × 4 × 2 bytes    │
│          = 16,588,800 bytes (~16 MB)    │
│                                         │
│ Block 2: [1920×1080 RGBA uint16]        │
│          (10 blocks × 16 MB = 160 MB)   │
│                                         │
│ ...                                     │
│                                         │
│ Block N: [1920×1080 RGBA uint16]        │
└─────────────────────────────────────────┘

Mode 5 (3840×2160@30fps):
┌─────────────────────────────────────────┐
│ GPU Memory Layout (BlockMemoryPool)     │
├─────────────────────────────────────────┤
│ Block 1: [3840×2160 RGBA uint16]        │
│          = 3840 × 2160 × 4 × 2 bytes    │
│          = 66,355,200 bytes (~63 MB)    │
│                                         │
│ Block 2: [3840×2160 RGBA uint16]        │
│          (5 blocks × 63 MB = 315 MB)    │
│                                         │
│ ...                                     │
└─────────────────────────────────────────┘
```

### Memory Leak Prevention

```python
class VerificationApplication(Application):
    def compose(self):
        # GOOD: Operators stored as instance variables for cleanup
        self._receiver = LinuxReceiverOperator(...)
        self._demosaic = BayerDemosaicOp(...)
        self._saver = ImageSaverOp(...)
        self._visualizer = HolovizOp(...)
        
        # AVOID: Operators stored in local variables
        # Local variables go out of scope and can cause cleanup issues
        # receiver = LinuxReceiverOperator(...)  # ✗ WRONG
        
    def __del__(self):
        """Explicit cleanup if needed"""
        # Holoscan handles most cleanup automatically
        # Only needed for custom resources
        pass
```

---

## Frame Handling Patterns

### Pattern 1: Pass-Through Frame Counting

**Use Case:** Track frames without modifying data

```python
class FrameCounterOp(Operator):
    """Pass-through operator that counts frames and collects statistics"""
    
    def __init__(self, *args, **kwargs):
        self._frame_count = 0
        self._timestamps = []
        super().__init__(*args, **kwargs)
    
    def setup(self, spec):
        spec.input("input_frame")
        spec.output("output_frame")  # Pass through
    
    def compute(self, op_input, op_output, context):
        frame = op_input.receive("input_frame")
        
        self._frame_count += 1
        self._timestamps.append(frame.timestamp)
        
        # CRITICAL: Must emit frame downstream for visualization/saving
        op_output.emit(frame, "output_frame")
    
    def get_statistics(self):
        """Return collected statistics"""
        if len(self._timestamps) < 2:
            return {}
        
        elapsed = (self._timestamps[-1] - self._timestamps[0]) / 1e6  # Convert to seconds
        fps = self._frame_count / elapsed if elapsed > 0 else 0
        
        return {
            "frame_count": self._frame_count,
            "elapsed_s": elapsed,
            "avg_fps": fps
        }
```

### Pattern 2: Selective Frame Saving

**Use Case:** Save only specific frames (e.g., every Nth frame)

```python
class SelectiveFrameSaverOp(Operator):
    """Save every Nth frame to avoid disk I/O bottleneck"""
    
    def __init__(self, save_interval=30, *args, **kwargs):
        self._save_interval = save_interval
        self._frame_count = 0
        self._saved_count = 0
        super().__init__(*args, **kwargs)
    
    def setup(self, spec):
        spec.input("input_frame")
    
    def compute(self, op_input, op_output, context):
        frame = op_input.receive("input_frame")
        
        # Save every Nth frame
        if self._frame_count % self._save_interval == 0:
            self._save_frame(frame)
            self._saved_count += 1
        
        self._frame_count += 1
    
    def _save_frame(self, frame):
        """Actual frame saving logic"""
        import numpy as np
        from pathlib import Path
        
        # Convert to numpy array
        frame_data = np.asarray(frame)
        
        # Save as .npy (raw data)
        output_dir = Path("frames")
        output_dir.mkdir(exist_ok=True)
        
        npy_file = output_dir / f"frame_{self._saved_count:06d}.npy"
        np.save(str(npy_file), frame_data)
```

### Pattern 3: Conditional Frame Flow

**Use Case:** Visualize OR save based on command-line option

```python
class VerificationApplication(Application):
    def __init__(self, *args, save_images=False, fullscreen=False, **kwargs):
        self._save_images = save_images
        self._fullscreen = fullscreen
        super().__init__(*args, **kwargs)
    
    def compose(self):
        # Common operators
        receiver = LinuxReceiverOperator(...)
        demosaic = BayerDemosaicOp(...)
        frame_counter = FrameCounterOp(...)
        
        # Branch 1: Save images (RGB format)
        if self._save_images and not self._fullscreen:
            saver = ImageSaverOp(...)
            add_flow(demosaic, saver, {("transmitter", "input")})
            add_flow(frame_counter, saver, {("transmitter", "input")})
            self._saver = saver
        
        # Branch 2: Fullscreen visualization (RGBA format)
        elif self._fullscreen:
            visualizer = HolovizOp(fullscreen=True, ...)
            add_flow(demosaic, visualizer, {("transmitter", "receivers")})
            add_flow(frame_counter, visualizer, {("transmitter", "receivers")})
            
            if self._save_images:
                screenshot = ScreenShotOp(...)
                # Screenshot captures rendered output
                self._screenshot = screenshot
        
        # Branch 3: No output (headless)
        else:
            # Frame counter is terminal operator
            pass
```

---

## Multi-Mode Operation

### Safe Mode Switching

**Problem:** Running mode 4, then mode 5 back-to-back causes dropped frames or frozen output.

```python
def run_multiple_modes(mode_sequence, frame_limit=300, delay_between_modes=5):
    """Execute camera verification for multiple modes"""
    
    results = {}
    
    for mode_id in mode_sequence:
        print(f"\n{'='*60}")
        print(f"Testing Mode {mode_id}")
        print(f"{'='*60}")
        
        try:
            # Run verification
            stats = safe_camera_operation(
                mode=mode_id,
                frame_limit=frame_limit
            )
            
            results[mode_id] = {
                "success": True,
                "stats": stats
            }
            
            print(f"✓ Mode {mode_id} completed: {stats['avg_fps']:.1f} FPS")
            
        except Exception as e:
            results[mode_id] = {
                "success": False,
                "error": str(e)
            }
            print(f"✗ Mode {mode_id} failed: {e}")
        
        # Critical: Wait before next mode
        # Allows kernel socket buffers to drain and hardware to reset
        if mode_id != mode_sequence[-1]:  # Don't wait after last mode
            print(f"Waiting {delay_between_modes}s before next mode...")
            time.sleep(delay_between_modes)
    
    return results


# Use it
results = run_multiple_modes(
    mode_sequence=[4, 5, 5, 4, 5],
    frame_limit=300,
    delay_between_modes=5
)

# Report results
pass_count = sum(1 for r in results.values() if r["success"])
total_count = len(results)
print(f"\nResults: {pass_count}/{total_count} modes passed")
```

### Mode-Specific Configurations

```python
MODE_CONFIG = {
    4: {  # 1920×1080@60fps
        "name": "1920×1080@60fps",
        "resolution": (1920, 1080),
        "fps": 60,
        "div": 5,
        "frame_length": 1116,
        "line_length": 5400,
        "min_fps_threshold": 54,  # 60 - 10%
        "max_fps_threshold": 66,  # 60 + 10%
        "expected_frame_gap_ms": 16.67,
    },
    5: {  # 3840×2160@30fps
        "name": "4K@30fps",
        "resolution": (3840, 2160),
        "fps": 30,
        "div": 5,
        "frame_length": 2232,
        "line_length": 10800,
        "min_fps_threshold": 27,   # 30 - 10%
        "max_fps_threshold": 33,   # 30 + 10%
        "expected_frame_gap_ms": 33.34,
    },
}

def validate_mode_performance(mode_id, actual_fps, frame_count, total_frames):
    """Check if mode performance meets expectations"""
    
    config = MODE_CONFIG.get(mode_id)
    if not config:
        return False, f"Unknown mode {mode_id}"
    
    # Check FPS
    if not (config["min_fps_threshold"] <= actual_fps <= config["max_fps_threshold"]):
        return False, (
            f"FPS out of range: {actual_fps:.1f} "
            f"(expected {config['fps']}±10%)"
        )
    
    # Check frame count
    min_frames_needed = int(total_frames * 0.9)  # Need 90% of frames
    if frame_count < min_frames_needed:
        return False, (
            f"Insufficient frames: {frame_count}/{total_frames} "
            f"(need {min_frames_needed})"
        )
    
    return True, "PASS"
```

---

## Performance Optimization

### Network Optimization

```python
import socket

def setup_optimized_socket(host="192.168.0.2", port=12321):
    """Configure socket for optimal Hololink communication"""
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    # Increase buffers for high frame rate
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2097152)  # 2MB
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 2097152)  # 2MB
    
    # Enable timestamping for frame timestamp accuracy
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_TIMESTAMP, 1)
    
    # Set timeout to prevent indefinite blocking
    sock.settimeout(5.0)
    
    # Connect to device
    sock.connect((host, port))
    
    return sock
```

### Frame Processing Pipeline Optimization

```python
# INEFFICIENT: Process each frame individually
for frame in receiver.get_frame_iterator():
    # Process one frame
    demosaiced = demosaic(frame)
    saved = save(demosaiced)
    # Result: Can't parallelize, slow

# EFFICIENT: Batch processing (use operators)
class BatchProcessorOp(Operator):
    """Process multiple frames at once"""
    
    def __init__(self, batch_size=10, *args, **kwargs):
        self._batch_size = batch_size
        self._batch = []
        super().__init__(*args, **kwargs)
    
    def compute(self, op_input, op_output, context):
        frame = op_input.receive("input_frame")
        self._batch.append(frame)
        
        if len(self._batch) >= self._batch_size:
            # Process batch
            results = self._process_batch(self._batch)
            for result in results:
                op_output.emit(result, "output_frame")
            self._batch = []
    
    def _process_batch(self, frames):
        """CUDA can process entire batch at once"""
        return frames  # Simplified
```

---

## Error Recovery

### Handling Network Timeouts

```python
def connect_with_retry(
    host="192.168.0.2",
    port=12321,
    max_retries=5,
    retry_delay=2
):
    """Connect with exponential backoff"""
    
    import socket
    import time
    
    for attempt in range(max_retries):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(5.0)
            sock.connect((host, port))
            print(f"✓ Connected on attempt {attempt + 1}")
            return sock
            
        except (socket.timeout, ConnectionError) as e:
            wait_time = retry_delay * (2 ** attempt)  # Exponential backoff
            print(f"✗ Connection failed (attempt {attempt + 1}): {e}")
            
            if attempt < max_retries - 1:
                print(f"  Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"✗ Failed after {max_retries} attempts")
                raise
```

### Recovering from Dropped Frames

```python
def handle_frame_drops(
    actual_frame_count,
    expected_frame_count,
    fps,
    max_tolerance=0.1
):
    """Determine if frame drops are acceptable"""
    
    drop_percentage = 1 - (actual_frame_count / expected_frame_count)
    
    if drop_percentage <= max_tolerance:
        # Acceptable
        return True, f"Frame drop: {drop_percentage*100:.1f}% (acceptable)"
    
    elif drop_percentage <= 0.25:
        # Warning
        return True, f"Frame drop: {drop_percentage*100:.1f}% (warning)"
    
    else:
        # Failure
        return False, f"Frame drop: {drop_percentage*100:.1f}% (too high)"
```

---

## Debugging Techniques

### Adding Instrumentation

```python
class InstrumentedFrameCounterOp(Operator):
    """Frame counter with detailed logging"""
    
    def __init__(self, verbose=False, *args, **kwargs):
        self._verbose = verbose
        self._last_log_count = 0
        self._log_interval = 100
        super().__init__(*args, **kwargs)
    
    def compute(self, op_input, op_output, context):
        frame = op_input.receive("input_frame")
        self._frame_count += 1
        self._timestamps.append(frame.timestamp)
        
        if self._verbose and (self._frame_count - self._last_log_count) >= self._log_interval:
            elapsed = (frame.timestamp - self._timestamps[0]) / 1e6
            fps = self._frame_count / elapsed
            print(f"[{self._frame_count:6d}] FPS={fps:6.2f}, "
                  f"TS={frame.timestamp:12d}, "
                  f"Size={frame.size:8d}")
            self._last_log_count = self._frame_count
        
        op_output.emit(frame, "output_frame")
```

### Capturing Diagnostic Data

```python
def save_diagnostic_data(
    frame_counter_op,
    demosaic_op,
    visualizer_op,
    output_dir="diagnostics"
):
    """Save operator state for analysis"""
    
    import json
    from pathlib import Path
    
    Path(output_dir).mkdir(exist_ok=True)
    
    diagnostics = {
        "frame_counter": {
            "frame_count": frame_counter_op.get_frame_count(),
            "fps": frame_counter_op.get_fps(),
            "timestamps": frame_counter_op.get_timestamps()[-100:],  # Last 100
        },
        "demosaic": {
            # Add relevant state
        },
        "visualizer": {
            # Add relevant state
        },
    }
    
    with open(f"{output_dir}/diagnostics.json", "w") as f:
        json.dump(diagnostics, f, indent=2)
    
    print(f"✓ Diagnostics saved to {output_dir}/")
```

---

## Related Documentation

- [IMX258 Camera Verification Guide](IMX258_CAMERA_VERIFICATION_GUIDE.md)
- [Hololink Communication Protocol](HOLOLINK_COMMUNICATION_PROTOCOL_GUIDE.md)
- [Hololink Core API Reference](HOLOLINK_CORE_API_REFERENCE.md)

