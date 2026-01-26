# Hololink Quick Reference Card

**Print or bookmark this page** - Essential info at a glance

---

## Critical Commands

```bash
# Test camera mode 4 (1920×1080@60fps)
python3 verify_camera_imx258.py --camera-mode 4 --frame-limit 300

# Test with visualization
python3 verify_camera_imx258.py --camera-mode 4 --holoviz --frame-limit 300

# Test multiple modes sequentially
python3 verify_multi_mode_imx258.py

# With visualization
python3 verify_multi_mode_imx258.py --holoviz
```

---

## Camera Modes at a Glance

| Mode | Resolution | FPS | Status | Use |
|------|-----------|-----|--------|-----|
| **4** | 1920×1080 | 60 | ✓ VALID | Default test |
| **5** | 3840×2160 | 30 | ✓ VALID | High-res test |
| 0-1 | 1920×1080 | 60/30 | ✓ Valid | Alternative |
| 2-3 | 1920×1080 | 60/30 | ✗ BROKEN | Never use |

---

## Expected Performance

| Metric | Mode 4 | Mode 5 | Check |
|--------|--------|--------|-------|
| FPS | 59.87 | 29.94 | ±10% OK |
| Frames | 300/300 | 300/300 | ≥90% OK |
| Max Gap | <20ms | <40ms | >50ms = bad |
| Drops | 0 | 0 | >1% = bad |

---

## Troubleshooting in 30 Seconds

```
Can't detect device?
  → ping 192.168.0.2
  → Check firewall

Black screen?
  → Check generate_alpha=True
  → Verify pool size: width*height*4*2

Low FPS?
  → Check network load (iftop)
  → Increase socket buffer
  → Check Hololink.reset_framework()

Hangs?
  → Add timeout to sockets
  → Kill with kill -9
  → Reset with: sudo fuser -k 12321/udp
```

---

## Critical Cleanup Sequence

**MUST be in this order:**

```python
# Step 1: Stop device
hololink.stop()

# Step 2: Wait for app
app_thread.join(timeout=5.0)

# Step 3: CRITICAL - Reset framework (clears cached state!)
from hololink import Hololink
Hololink.reset_framework()

# Step 4: Destroy CUDA
import pycuda.driver as cuda
cuda.cuCtxDestroy(cuda_context)
```

⚠️ **Wrong order = frame contamination to next run**

---

## Fullscreen Visualization Setup

```python
# MUST have:
demosaic = BayerDemosaicOp(
    ...,
    generate_alpha=True,           # ← REQUIRED
    alpha_value=65535,             # ← REQUIRED
    pool=BlockMemoryPool(
        block_size=width*height*4*2  # ← RGBA (4 channels)
    )
)

visualizer = HolovizOp(
    fullscreen=True,
    framebuffer_srgb=True  # Makes display brighter than saved images
)

# Connect directly (no blocking frame counter!)
add_flow(demosaic, visualizer, {("transmitter", "receivers")})
```

---

## Register Read/Write

```python
# Single value
value = channel.read_register(0x0307)
channel.write_register(address=0x0307, value=0x6E)

# Multiple values
values = channel.read_block(address=0x0300, length=4)
channel.write_block(base_addr=0x0300, data=[0x6E, 0x05, 0xFF])

# Camera configuration
camera.set_exposure(0x0600)      # Integration time
camera.set_analog_gain(0x0180)   # Gain (1x = 0x0100)
camera.set_focus(-140)           # Focus (-140=near, 0=far)
```

---

## Common Fixes

| Problem | Fix |
|---------|-----|
| Black screen | `generate_alpha=True, alpha_value=65535` |
| Frames not reaching viz | Remove blocking FrameCounterOp gate |
| Frame drops after 100 | Add `Hololink.reset_framework()` |
| Inconsistent FPS | Call `reset_framework()` between runs |
| Device hangs | Add `socket.settimeout(5.0)` |
| Can't detect device | `ping 192.168.0.2`, check firewall |
| Image too dark | `camera.set_exposure(0x0800)` |
| Image too bright | `camera.set_exposure(0x0400)` |

---

## Device Configuration

```python
from hololink import Enumerator, sensors

# Connect
channel = Enumerator.find_channel(
    channel_ip="192.168.0.2",
    timeout_s=5.0
)

# Create camera
camera = sensors.imx258.Imx258(channel, camera_id=0)

# Configure
camera.configure(mode=4)  # Or 5 for 4K

# Adjust
camera.set_exposure(0x0600)
camera.set_analog_gain(0x0100)
camera.set_focus(-140)

# Start
camera.start()

# Use
for frame in channel.get_frame_iterator():
    process_frame(frame)
    
# Stop
camera.stop()
channel.close()
Hololink.reset_framework()
```

---

## Network Setup

```bash
# Configure host IP
sudo ip addr add 192.168.0.1/24 dev eth0
sudo ip link set eth0 up

# Verify
ping -c 5 192.168.0.2

# Allow firewall
sudo ufw allow 12321/udp
sudo ufw allow 50000:50010/udp

# Monitor
iftop -i eth0      # Network load
nvidia-smi         # GPU memory
top                # CPU usage
```

---

## Quick Diagnostic

```bash
# Can reach device?
ping 192.168.0.2

# Socket reachable?
nc -uz 192.168.0.2 12321

# Network errors?
ethtool -S eth0 | grep -i error

# GPU memory?
nvidia-smi

# System load?
top -b -n 1 | head -5
```

---

## Multi-Mode Test Sequence

```
Recommended: [4, 5, 5, 4, 5]

Why?
├─ Test 1080p first (simpler)
├─ Switch to 4K (tests resolution switching)
├─ Repeat 4K (memory stability)
├─ Back to 1080p (cleanup verification)
└─ Final 4K (overall stability)
```

---

## Documentation Map

| Need | Document |
|------|----------|
| **Start here** | [DOCUMENTATION_INDEX.md](DOCUMENTATION_INDEX.md) |
| Camera setup | [IMX258_CAMERA_VERIFICATION_GUIDE.md](IMX258_CAMERA_VERIFICATION_GUIDE.md) |
| API reference | [HOLOLINK_CORE_API_REFERENCE.md](HOLOLINK_CORE_API_REFERENCE.md) |
| Something broken | [TROUBLESHOOTING_AND_FAQ.md](TROUBLESHOOTING_AND_FAQ.md) |
| Protocol details | [HOLOLINK_COMMUNICATION_PROTOCOL_GUIDE.md](HOLOLINK_COMMUNICATION_PROTOCOL_GUIDE.md) |
| Best practices | [IMPLEMENTATION_BEST_PRACTICES.md](IMPLEMENTATION_BEST_PRACTICES.md) |

---

## Pre-Flight Checklist

- [ ] Can ping 192.168.0.2
- [ ] Firewall allows 12321/udp
- [ ] Mode 4 runs, get 300 frames
- [ ] Mode 5 runs, get 300 frames
- [ ] FPS within ±10% of target
- [ ] No dropped frames (>1%)
- [ ] Fullscreen viz working (if needed)
- [ ] Image brightness acceptable
- [ ] Cleanup sequence working

---

## Emergency Commands

```bash
# Kill frozen process
pkill -9 -f verify_camera_imx258

# Clear UDP ports
sudo fuser -k 12321/udp
sudo fuser -k 50000:50010/udp

# Reset network
sudo systemctl restart networking

# Check GPU
nvidia-smi --query-gpu=memory.free --format=csv,nounits

# Full system diagnostic
lspci | grep -i nvidia
ifconfig eth0
ethtool eth0
```

---

## Common Parameters

```python
frame_limit=300           # Frames to capture
timeout=15               # Seconds to wait
min_fps=25.0            # Minimum acceptable FPS
camera_mode=4           # Which mode (0-5)
--holoviz              # Enable fullscreen viz
--save-images          # Save frames to disk
```

---

## Performance Baseline

```
Network: Dedicated ethernet (1Gbps)
CPU: Idle
GPU: Dedicated
Storage: Fast SSD for frame saving
Temperature: < 25°C

Expected (Validated):
├─ Mode 4: 59.87 FPS (within 99.16%)
├─ Mode 5: 29.94 FPS (within 99.8%)
├─ Zero drops: 300/300 frames
└─ Max gap: <20ms (Mode 4) / <40ms (Mode 5)
```

---

## Key Concepts

**Bayer demosaicing:** Raw sensor data → RGB image  
**RGBA format:** RGB + alpha channel for visualization  
**FRM_LENGTH:** Total lines (must be ≥ output height)  
**CountCondition:** Stop GXF graph after N frames  
**reset_framework():** Clear device registry between runs  
**sRGB gamma:** Display correction (makes image brighter)  

---

**Last Updated:** January 2026  
**Version:** 1.0  
**Status:** Ready for Production

