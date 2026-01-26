# IMX258 Camera Verification Guide

**Last Updated:** January 2026  
**Purpose:** Complete guide to IMX258 camera setup, timing constraints, verification procedures, and troubleshooting.

---

## Table of Contents

1. [Camera Modes Quick Reference](#camera-modes-quick-reference)
2. [Timing Constraints](#timing-constraints)
3. [Register Configuration](#register-configuration)
4. [Verification Procedures](#verification-procedures)
5. [Common Issues and Fixes](#common-issues-and-fixes)
6. [Frame Gap Analysis](#frame-gap-analysis)

---

## Camera Modes Quick Reference

### Mode Definitions

| Mode ID | Name | Resolution | FPS | DIV | FRM | LINE | Status |
|---------|------|------------|-----|-----|-----|------|--------|
| 0 | 1920×1080@60fps | 1920×1080 | 60 | 5 | 1592 | 5352 | ✓ Validated |
| 1 | 1920×1080@30fps | 1920×1080 | 30 | 10 | 1592 | 5352 | ✓ Validated |
| 2 | 1920×1080@60fps_cus | 1920×1080 | 60 | 5 | 1050 | 5100 | ✗ BROKEN |
| 3 | 1920×1080@30fps_cus | 1920×1080 | 30 | 10 | 1050 | 5100 | ✗ BROKEN |
| 4 | 1920×1080@60fps_new | 1920×1080 | 60 | 5 | 1116 | 5400 | ✓ Validated |
| 5 | 4K@30fps | 3840×2160 | 30 | 5 | 2232 | 10800 | ✓ Validated |

### Recommended Test Sequence

```python
test_sequence = [4, 5, 5, 4, 5]  # Mode IDs to test in order
```

**Why This Sequence:**
- Tests resolution switching (1080p ↔ 4K)
- Verifies cleanup between runs
- Ensures frame synchronization after mode change
- Validates consistent FPS across repetitions

---

## Timing Constraints

### Critical Rule #1: FRM_LENGTH >= Y_OUT_SIZE

**Problem:** FRM_LENGTH register sets total frame lines (including blanking). If it's LESS than output height, sensor outputs incomplete frames.

**Example of Failure:**
```
Mode 2 (60fps_cus):
  FRM_LENGTH = 1050 lines
  Y_OUT_SIZE = 1080 lines
  MISSING = 30 lines
  Result: BLACK/BLANK FRAMES ✗
```

**Correct Values:**
```
Mode 4 (60fps_new):
  FRM_LENGTH = 1116 lines (minimum safe)
  Y_OUT_SIZE = 1080 lines
  BLANKING = 36 lines
  Result: VALID OUTPUT ✓
```

### Critical Rule #2: LINE_LENGTH >= X_OUT_SIZE

**Problem:** LINE_LENGTH register sets pixel clocks per line (including blanking). If too small, horizontal sync fails.

**Requirements:**
- Mode 0-4 (1920×1080): LINE_LENGTH >= 5100 (minimum)
- Mode 5 (4K): LINE_LENGTH = 10800 (fixed)

### Critical Rule #3: DIV Value Effects

**IVTPXCK_DIV (0x0301) scales pixel clock:**

```
DIV=5:  PXCK = (27MHz * 110) / 5 = 594 MHz
DIV=10: PXCK = (27MHz * 110) / 10 = 297 MHz (half speed)

FPS = PXCK / (FRM_LENGTH * LINE_LENGTH)
```

**Important:** Cannot arbitrarily scale FRM_LENGTH/LINE_LENGTH when changing DIV

- DIV cannot be changed without validated register set
- DIV=4 is incompatible with 1920×1080 (requires FRM < 1000, violates constraint)
- Must use pre-validated configurations

---

## Register Configuration

### Minimal Register Set for Camera Operation

```python
# Frame and Line Timing (CRITICAL)
("0340", "04"),  # FRM_LENGTH high byte
("0341", "5C"),  # FRM_LENGTH low byte (1116 = 0x045C)
("0342", "15"),  # LINE_LENGTH high byte
("0343", "18"),  # LINE_LENGTH low byte (5400 = 0x1518)

# Output Image Size
("034C", "07"),  # X_OUT_SIZE high (1920 = 0x0780)
("034D", "80"),  # X_OUT_SIZE low
("034E", "04"),  # Y_OUT_SIZE high (1080 = 0x0438)
("034F", "38"),  # Y_OUT_SIZE low

# PLL and Clock Configuration
("0136", "1B"),  # INCK = 27MHz
("0137", "00"),
("0305", "04"),  # PREPLLCK_VT_DIV
("030D", "04"),  # PREPLLCK_OP_DIV
("0306", "00"),  # PLL_IVT_MPY high (110 = 0x006E)
("0307", "6E"),  # PLL_IVT_MPY low
("030E", "00"),  # PLL_IOP_MPY high
("030F", "6E"),  # PLL_IOP_MPY low
("0301", "05"),  # IVTPXCK_DIV = 5 (60fps)
("0303", "02"),  # IVTSYCK_DIV
("0309", "0A"),  # IOPPXCK_DIV
("030B", "01"),  # IOPSYCK_DIV

# CSI Configuration
("0114", "03"),  # CSI_LANE_MODE = 4 lanes
("0112", "0A"),  # CSI_DT_FMT = RAW10
("0113", "0A"),
("0820", "00"),  # MIPI Bit Rate (720Mbps = 0x02D0)
("0821", "00"),
("0822", "02"),
("0823", "D0"),

# Exposure and Gain (for image brightness)
("0202", "06"),  # COARSE_EXPOSURE (typical)
("0203", "00"),
("0204", "01"),  # ANALOG_GAIN (typical = 0x0100 = 1x)
("0205", "00"),
```

### How to Calculate FRM_LENGTH for Custom FPS

```python
target_fps = 30.0
pxck = 297_000_000  # Hz (DIV=10)
x_out = 1920
y_out = 1080
margin = 36  # Safe blanking margin

line_length = 5100  # Fixed minimum
frm_length_needed = pxck / (target_fps * line_length)

if frm_length_needed < (y_out + margin):
    frm_length = y_out + margin
    actual_fps = pxck / (frm_length * line_length)
    print(f"Using FRM={frm_length}, actual FPS={actual_fps}")
else:
    frm_length = int(frm_length_needed)
    actual_fps = target_fps
    print(f"Using FRM={frm_length}, actual FPS={actual_fps}")
```

---

## Verification Procedures

### Single Mode Verification

```bash
# Run mode 4 (1920×1080@60fps) without visualization
python3 verify_camera_imx258.py --camera-mode 4 --frame-limit 300

# Run mode 5 (4K@30fps) with fullscreen visualization
python3 verify_camera_imx258.py --camera-mode 5 --holoviz --frame-limit 300
```

### Multi-Mode Verification (Recommended)

```bash
# Run sequence [4, 5, 5, 4, 5] automatically
python3 verify_multi_mode_imx258.py

# Same with visualization
python3 verify_multi_mode_imx258.py --holoviz
```

### What to Expect

**Successful Run (Mode 4):**
```
Average FPS: 59.87
Frame count: 300/300
Elapsed time: 5.02s
Max gap: 16.67ms (expected for 60fps)
Dropped frames: 0
```

**Successful Run (Mode 5):**
```
Average FPS: 29.94
Frame count: 300/300
Elapsed time: 10.03s
Max gap: 33.34ms (expected for 30fps)
Dropped frames: 0
```

**Failed Run (Broken Mode 2):**
```
Frame count: 47/300
Average FPS: 0.00 (black frames, no valid data)
Error: Insufficient frames received
```

---

## Common Issues and Fixes

### Issue 1: Black/Blank Frames

**Symptoms:**
- Frames received but all black
- ImageSaver shows min=0, max=0
- HolovizOp displays black screen

**Root Cause:**
- FRM_LENGTH < Y_OUT_SIZE (timing violation)
- Sensor outputs incomplete frame data

**Fix:**
```python
# Check which mode causes issue
for mode in [0, 1, 2, 3, 4, 5]:
    result = verify_camera_imx258(camera_mode=mode, frame_limit=10)
    if "blank" in result:
        print(f"Mode {mode} is broken")

# Use validated mode instead (4 or 5 recommended)
python3 verify_camera_imx258.py --camera-mode 4
```

### Issue 2: Frame Gaps and Dropped Frames

**Symptoms:**
- Max gap > 50ms (for 60fps) or > 100ms (for 30fps)
- Estimated dropped frames > 0
- Non-uniform frame spacing

**Root Cause:**
- Network congestion
- Camera buffer exhaustion
- Consecutive runs without proper cleanup

**Fix:**
```python
# Clear global state between runs
import hololink as hololink_module
hololink_module.Hololink.reset_framework()

# Ensure cleanup sequence is correct
hololink.stop()
hololink_module.Hololink.reset_framework()  # MUST be before CUDA destroy
cuda.cuCtxDestroy(cu_context)
```

### Issue 3: Inconsistent FPS Between Modes

**Symptoms:**
- Mode 4: 59.87 fps ✓
- Mode 5: 29.94 fps ✓
- Mode 4 again: 95.30 fps ✗ (too high!)

**Root Cause:**
- Hololink device registry cached from previous run
- Kernel socket buffers contain old packets from Mode 5

**Fix:**
```python
# Mandatory cleanup between multi-mode runs
verify_camera_functional(mode=4)

# BEFORE next run:
hololink_module.Hololink.reset_framework()

verify_camera_functional(mode=5)
```

### Issue 4: HolovizOp Black Screen

**Symptoms:**
- Fullscreen window opens
- Screen completely black
- No visualization appears

**Root Cause:**
- `generate_alpha=False` (outputs RGB not RGBA)
- Missing `alpha_value` parameter
- Pool size mismatch

**Fix:**
```python
# Ensure RGBA output in fullscreen mode
bayer_to_rgba = BayerDemosaicOp(
    self,
    name="bayer_to_rgba",
    pool=rgba_pool,
    generate_alpha=True,          # MUST be True
    alpha_value=65535,            # MUST be set
    bayer_grid_pos=bayer_format.value,
    interpolation_mode=0,
)

# Verify pool size matches
block_size = width * height * 4 * 2  # RGBA uint16
```

---

## Frame Gap Analysis

### Understanding Frame Gaps

**Frame Gap:** Time between consecutive frames

```
Expected for 60fps:  1000ms / 60 = 16.67ms
Expected for 30fps:  1000ms / 30 = 33.34ms

Large gap (> 1.5x expected):
  - Indicates dropped frame(s)
  - Example: 50ms gap at 60fps = ~3 dropped frames
```

### Analyzing Gaps in Verification Results

```python
# Frame gap statistics returned in stats dict:
{
    "frame_count": 300,
    "avg_fps": 59.87,
    "max_gap_ms": 16.67,           # Maximum gap observed
    "avg_gap_ms": 16.67,           # Average gap
    "num_large_gaps": 0,           # Gaps > 1.5x expected
    "dropped_frames_estimate": 0,  # Estimated dropped frames
}
```

### Acceptable vs Concerning Values

| Metric | 60fps Target | 30fps Target | Verdict |
|--------|--------------|--------------|---------|
| Max Gap | < 25ms | < 50ms | Acceptable |
| Max Gap | 25-50ms | 50-100ms | Warning |
| Max Gap | > 50ms | > 100ms | FAIL |
| Dropped Frames | = 0 | = 0 | Expected |
| Dropped Frames | > 0 | > 0 | Investigate |

---

## Brightness/Exposure Control

### Setting Camera Exposure

```python
import hololink as hololink_module

channel = hololink_module.Enumerator.find_channel(channel_ip="192.168.0.2")
camera = hololink_module.sensors.imx258.Imx258(channel, camera_id=0)

# Configure mode first
camera.configure(mode)

# Set focus distance
camera.set_focus(-140)  # -140 = near, 0 = far

# Set exposure (integration time)
# Values: 0x0438 (default) to 0x0800 (longer)
camera.set_exposure(0x0600)  # ~1536 lines

# Set analog gain
# Values: 0x0100 (1x, default) to 0x0300 (3x)
camera.set_analog_gain(0x0180)  # 1.5x gain

camera.start()
```

### Brightness Adjustment Guide

| Appearance | Action | Register | Value |
|------------|--------|----------|-------|
| Too Dark | Increase Exposure | 0x0200-0x0203 | +0x0200 |
| Too Dark | Increase Gain | 0x0204-0x0205 | +0x0080 |
| Too Bright | Decrease Exposure | 0x0200-0x0203 | -0x0100 |
| Too Bright | Decrease Gain | 0x0204-0x0205 | -0x0080 |

**Preference:** Adjust exposure first (better image quality), then gain (adds noise).

---

## Quick Troubleshooting Checklist

- [ ] Verify mode ID is valid (0-5)
- [ ] Check camera reachable: `Enumerator::find_channel()`
- [ ] Verify network connection: `ping 192.168.0.2`
- [ ] Test mode 4 first (most stable)
- [ ] Run cleanup between modes: `Hololink::reset_framework()`
- [ ] Check frame count > 90% of limit
- [ ] Check FPS within ±10% of target
- [ ] Verify max gap < 1.5x expected interval
- [ ] Ensure image brightness acceptable
- [ ] Confirm no dropped frames (large gaps)

---

## Performance Benchmarks

**Expected Performance (Validated Modes):**

| Mode | FPS | Resolution | Frame Time | Data Rate |
|------|-----|------------|------------|-----------|
| 0-1 | 60/30 | 1920×1080 | 16.67/33.34ms | 124/62 MB/s |
| 4 | 60 | 1920×1080 | 16.67ms | 124 MB/s |
| 5 | 30 | 3840×2160 | 33.34ms | 248 MB/s |

**Network Throughput:**
- 1Gbps Ethernet: ~125 MB/s max (accounting for headers)
- Mode 5 @ 30fps: 248 MB/s raw (EXCEEDS 1Gbps!)
- Solution: Mode 5 uses data compression or lower frame rate

---

## Related Documentation

- [Hololink Core API Reference](HOLOLINK_CORE_API_REFERENCE.md)
- [Implementation Details](readme%20guides/IMPLEMENTATION_SUMMARY.md)
- [Frame Analysis and Diagnostics](readme%20guides/HOLOLINK_PACKET_ANALYSIS.md)

