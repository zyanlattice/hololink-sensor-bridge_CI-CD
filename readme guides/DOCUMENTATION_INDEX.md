# Hololink Documentation Index

**Last Updated:** January 2026  
**Purpose:** Central reference for all consolidated Hololink and camera verification documentation.

---

## Quick Navigation

### 🚀 Getting Started (Read These First)
1. [IMX258 Camera Verification Guide](IMX258_CAMERA_VERIFICATION_GUIDE.md) - Start here for camera operations
2. [Hololink Core API Reference](HOLOLINK_CORE_API_REFERENCE.md) - Complete API documentation
3. [Quick Troubleshooting](#quick-troubleshooting-by-situation) - Immediate solutions

### 📚 Complete Reference Guides
| Guide | Purpose | Best For |
|-------|---------|----------|
| [IMX258 Camera Verification Guide](IMX258_CAMERA_VERIFICATION_GUIDE.md) | Camera modes, timing, verification procedures | Configuring camera, understanding modes 0-5 |
| [Hololink Communication Protocol Guide](HOLOLINK_COMMUNICATION_PROTOCOL_GUIDE.md) | Protocol details, packet structures, register access | Low-level communication, debugging |
| [Implementation Best Practices Guide](IMPLEMENTATION_BEST_PRACTICES.md) | Design patterns, cleanup procedures, optimization | Building reliable systems, multi-mode operation |
| [Troubleshooting and FAQ Guide](TROUBLESHOOTING_AND_FAQ.md) | Common issues, solutions, performance tuning | Solving problems, understanding behavior |
| [Hololink Core API Reference](HOLOLINK_CORE_API_REFERENCE.md) | Complete API with examples | Using Hololink library |

---

## Documentation Structure

```
Hololink Documentation
├─ Quick Start
│  ├─ Camera Verification (modes, timing constraints)
│  └─ API Reference (classes, methods, usage)
│
├─ Technical Depth
│  ├─ Communication Protocol (packet formats, register operations)
│  └─ Implementation Patterns (cleanup, memory, frame handling)
│
└─ Practical Help
   ├─ Troubleshooting (10+ common issues with solutions)
   └─ FAQ (answers to frequent questions)
```

---

## Quick Troubleshooting by Situation

### Situation 1: "Camera not detected"
**Go to:** [Troubleshooting and FAQ → Issue 1](TROUBLESHOOTING_AND_FAQ.md#issue-1-cannot-detect-device)
- Check network connectivity
- Verify IP configuration
- Check firewall settings

### Situation 2: "HolovizOp shows black screen"
**Go to:** [Troubleshooting and FAQ → Issue 2](TROUBLESHOOTING_AND_FAQ.md#issue-2-black-screen-in-fullscreen-visualization)
- Verify RGBA format (not RGB)
- Check pool size calculation
- Ensure alpha_value is set

### Situation 3: "Dropping frames / low FPS"
**Go to:** [Troubleshooting and FAQ → Issue 3](TROUBLESHOOTING_AND_FAQ.md#issue-3-dropped-frames--fps-lower-than-expected)
- Check network load
- Verify cleanup sequence
- Increase socket buffers

### Situation 4: "Inconsistent FPS between runs"
**Go to:** [Troubleshooting and FAQ → Issue 4](TROUBLESHOOTING_AND_FAQ.md#issue-4-inconsistent-performance-between-runs)
- Add `Hololink.reset_framework()` between runs
- Verify cleanup in correct order

### Situation 5: "Mode switching causes hangs"
**Go to:** [Implementation Best Practices → Multi-Mode Operation](IMPLEMENTATION_BEST_PRACTICES.md#multi-mode-operation)
- Wait 5+ seconds between mode changes
- Call reset_framework() between runs

### Situation 6: "Image too dark or bright"
**Go to:** [IMX258 Camera Verification → Brightness Control](IMX258_CAMERA_VERIFICATION_GUIDE.md#brightnessexposure-control)
- Adjust exposure and gain values
- Check focus distance

### Situation 7: "Can't understand register operations"
**Go to:** [Hololink Communication Protocol → Register Operations](HOLOLINK_COMMUNICATION_PROTOCOL_GUIDE.md#register-readwrite-operations)
- See examples of read/write operations
- Understand block read/write format

### Situation 8: "Device hangs or freezes"
**Go to:** [Troubleshooting and FAQ → Issue 5](TROUBLESHOOTING_AND_FAQ.md#issue-5-device-hangs--unresponsive)
- Check for timeout configuration
- Verify cleanup sequence
- Kill and restart application

---

## By Task

### I want to...

#### Configure and start camera
1. Read: [IMX258 Camera Verification Guide → Camera Modes](IMX258_CAMERA_VERIFICATION_GUIDE.md#camera-modes-quick-reference)
2. Reference: [Hololink Core API → Camera Configuration](HOLOLINK_CORE_API_REFERENCE.md#camera-configuration-example)
3. Check: [Implementation Best Practices → Device Lifecycle](IMPLEMENTATION_BEST_PRACTICES.md#device-lifecycle-management)

#### Verify camera is working
1. Run: `python3 verify_camera_imx258.py --camera-mode 4 --frame-limit 300`
2. Interpret results: [IMX258 Guide → Verification Procedures](IMX258_CAMERA_VERIFICATION_GUIDE.md#verification-procedures)
3. Check FPS: [Troubleshooting → Performance Benchmarks](TROUBLESHOOTING_AND_FAQ.md#baseline-performance)

#### Visualize camera output fullscreen
1. Read: [IMX258 Guide → Verification Procedures](IMX258_CAMERA_VERIFICATION_GUIDE.md#verification-procedures)
2. Run: `python3 verify_camera_imx258.py --camera-mode 4 --holoviz`
3. Debug if black: [Troubleshooting → Issue 2](TROUBLESHOOTING_AND_FAQ.md#issue-2-black-screen-in-fullscreen-visualization)

#### Access registers (I2C/SPI)
1. Reference: [Communication Protocol → Register Operations](HOLOLINK_COMMUNICATION_PROTOCOL_GUIDE.md#register-readwrite-operations)
2. Example: [Communication Protocol → Examples](HOLOLINK_COMMUNICATION_PROTOCOL_GUIDE.md#communication-examples)
3. API details: [Core API Reference → I2C Interface](HOLOLINK_CORE_API_REFERENCE.md#i2c-interface)

#### Test multiple camera modes
1. Read: [Implementation Best Practices → Multi-Mode Operation](IMPLEMENTATION_BEST_PRACTICES.md#multi-mode-operation)
2. Run: `python3 verify_multi_mode_imx258.py`
3. Understand mode differences: [IMX258 Guide → Mode Table](IMX258_CAMERA_VERIFICATION_GUIDE.md#mode-definitions)

#### Optimize for performance
1. Read: [Implementation Best Practices → Performance](IMPLEMENTATION_BEST_PRACTICES.md#performance-optimization)
2. Configure: [Troubleshooting → Network Optimization](TROUBLESHOOTING_AND_FAQ.md#network-optimization)
3. Monitor: [Troubleshooting → Performance Troubleshooting](TROUBLESHOOTING_AND_FAQ.md#performance-troubleshooting)

#### Debug a specific problem
1. Use: [Troubleshooting → Quick Diagnostic Flowchart](TROUBLESHOOTING_AND_FAQ.md#quick-diagnostic-flowchart)
2. Find your issue: [Troubleshooting → Common Issues](TROUBLESHOOTING_AND_FAQ.md#common-issues-and-solutions)
3. Apply solution from table

---

## Key Concepts Reference

### Camera Modes
| Mode | Resolution | FPS | Status | When to Use |
|------|-----------|-----|--------|------------|
| 0-1 | 1920×1080 | 60/30 | Validated | Testing, comfortable baseline |
| 2-3 | 1920×1080 | 60/30 | ✗ BROKEN | Never use (black frames) |
| 4 | 1920×1080 | 60 | Validated | Default for testing |
| 5 | 3840×2160 | 30 | Validated | High resolution testing |

**Recommended test sequence:** [4, 5, 5, 4, 5]

### Critical Procedures
| Procedure | Why | How |
|-----------|-----|-----|
| Device cleanup | Prevent frame contamination | Follow [cleanup sequence](IMPLEMENTATION_BEST_PRACTICES.md#critical-cleanup-sequence) |
| reset_framework() | Clear global device registry | Call between consecutive runs |
| RGBA format | Required for HolovizOp | `generate_alpha=True, alpha_value=65535` |
| Pool sizing | Prevent black screen | `width * height * 4 * 2` bytes |
| Timeout config | Prevent hangs | `socket.settimeout(5.0)` |

### Performance Expectations
| Metric | Mode 4 | Mode 5 | Limit |
|--------|--------|--------|-------|
| FPS | 59.87 | 29.94 | ±10% acceptable |
| Frames (300s limit) | 300/300 | 300/300 | ≥90% required |
| Max gap | <20ms | <40ms | >50ms investigate |
| Dropped frames | 0 | 0 | >1% investigate |

---

## File Organization

### New Consolidated Guides (Created)
```
root/
├─ IMX258_CAMERA_VERIFICATION_GUIDE.md          [Modes, timing, verification]
├─ HOLOLINK_COMMUNICATION_PROTOCOL_GUIDE.md     [Protocol, packets, registers]
├─ IMPLEMENTATION_BEST_PRACTICES.md             [Patterns, cleanup, optimization]
├─ TROUBLESHOOTING_AND_FAQ.md                   [Common issues, solutions]
├─ HOLOLINK_CORE_API_REFERENCE.md               [Complete API documentation]
└─ DOCUMENTATION_INDEX.md                       [This file]
```

### Legacy Guides (Original, still present)
```
readme guides/
├─ IMPLEMENTATION_SUMMARY.md                    (superseded by Implementation Best Practices)
├─ IMX258_*.md                                  (superseded by IMX258 Camera Guide)
├─ HOLOLINK_*.md                                (superseded by Communication Protocol & Core API)
├─ PROCESS_ISOLATION_SOLUTION.md                (reference material)
└─ TESTING_ASSESSMENT_SUMMARY.md                (reference material)
```

**Note:** Original guides are retained for reference but consolidated guides are the primary source of truth.

---

## Implementation Examples

### Complete Camera Initialization
See: [Core API Reference → Device Initialization Example](HOLOLINK_CORE_API_REFERENCE.md#complete-device-initialization-example)

```python
from hololink import Enumerator, sensors

channel = Enumerator.find_channel("192.168.0.2")
camera = sensors.imx258.Imx258(channel, camera_id=0)
camera.configure(mode=4)
camera.start()

for frame_num, frame in enumerate(channel.get_frame_iterator()):
    if frame_num >= 300:
        break
    process_frame(frame)

camera.stop()
channel.close()
Hololink.reset_framework()
```

### Multi-Mode Testing
See: [Implementation Best Practices → Multi-Mode Operation](IMPLEMENTATION_BEST_PRACTICES.md#multi-mode-operation)

```bash
python3 verify_multi_mode_imx258.py --holoviz
```

### Register Read/Write
See: [Communication Protocol → Register Operations](HOLOLINK_COMMUNICATION_PROTOCOL_GUIDE.md#register-readwrite-operations)

```python
# Single register
value = channel.read_register(0x0307)
channel.write_register(address=0x0307, value=0x6E)

# Block operations
values = channel.read_block(0x0300, length=4)
channel.write_block(0x0300, [0x6E, 0x05, 0xFF])
```

---

## Common Parameter Reference

### Camera Configuration
```python
camera.configure(mode)                  # 0-5 (0-1, 4-5 valid)
camera.set_exposure(0x0600)            # Integration time (0x0400-0x0800)
camera.set_analog_gain(0x0100)         # Gain multiplier (0x0100-0x0300)
camera.set_focus(-140)                 # Focus distance (-140 near, 0 far)
```

### Frame Verification
```python
frame_limit=300                        # Total frames to capture
timeout=15                             # Seconds to wait for all frames
min_fps=25.0                          # Minimum acceptable FPS
--camera-mode 4                       # Which mode to test
```

### Performance Tuning
```python
SO_RCVBUF=2097152                    # 2MB socket buffer
block_size=width*height*4*2          # Pool block size (RGBA)
num_blocks=5                         # Number of frames to allocate
'''

---

## Debugging Resources

### Network Diagnostics
```bash
ping 192.168.0.2                       # Basic connectivity
iftop -i eth0                          # Monitor bandwidth
tcpdump -i eth0 'host 192.168.0.2'    # Capture traffic
ethtool -S eth0 | grep -i error        # Check for errors
```

### Device Diagnostics
```bash
nvidia-smi                             # GPU memory usage
top -b                                 # CPU usage
ps aux | grep python                   # Running processes
dmesg | tail -20                       # Kernel messages
```

### Application Diagnostics
```python
# See: Troubleshooting → Debugging Techniques
from hololink import Hololink
Hololink.reset_framework()  # Clear state
```

---

## Checklists

### Pre-Deployment Checklist
- [ ] Tested mode 4 (1920×1080@60fps) - min 300 frames
- [ ] Tested mode 5 (4K@30fps) - min 300 frames
- [ ] Multi-mode sequence [4,5,5,4,5] all pass
- [ ] Frame drops < 1% across all modes
- [ ] FPS within ±10% of target
- [ ] Fullscreen visualization working (if needed)
- [ ] Screenshot capture working (if needed)
- [ ] Image brightness acceptable
- [ ] Cleanup sequence verified
- [ ] Network stable (<50% utilization)

### Troubleshooting Checklist
See: [Troubleshooting → Debugging Checklist](TROUBLESHOOTING_AND_FAQ.md#debugging-checklist)

---

## Related Code Files

### Verification Scripts
- `verify_camera_imx258.py` - Single-mode verification (784 lines)
- `verify_multi_mode_imx258.py` - Multi-mode sequence testing

### Key Classes
- `VerificationApplication` - Main GXF application
- `FrameCounterOp` - Frame tracking + statistics
- `ImageSaverOp` - Frame saving (PNG + NPY)
- `ScreenShotOp` - Visualizer screenshot capture

### Implementation Details
See: [Implementation Best Practices → Frame Handling Patterns](IMPLEMENTATION_BEST_PRACTICES.md#frame-handling-patterns)

---

## Version History

| Date | Changes |
|------|---------|
| Jan 2026 | Initial consolidated documentation created (5 guides) |
| - | Merged 15+ scattered readme files |
| - | Created unified API reference |
| - | Added complete troubleshooting guide |

---

## Contributing / Updating Docs

When updating documentation:

1. **Small fixes:** Update the specific guide directly
2. **New content:** Add to appropriate guide or create new section
3. **API changes:** Update [Core API Reference](HOLOLINK_CORE_API_REFERENCE.md) first
4. **New issues:** Add to [Troubleshooting FAQ](TROUBLESHOOTING_AND_FAQ.md)
5. **Update this index:** If structure changes significantly

---

## License and Attribution

Original source materials from:
- Hololink library documentation
- IMX258 sensor specifications
- Holoscan SDK examples
- Development experience and testing

Consolidated and organized for clarity and accessibility.

---

**Last generated:** January 2026  
**Maintained by:** Lattice Semiconductor  
**Questions?** Check the appropriate guide above or troubleshooting section

