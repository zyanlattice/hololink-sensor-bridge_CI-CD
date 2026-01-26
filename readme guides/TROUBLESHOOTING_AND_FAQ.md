# Hololink Troubleshooting and FAQ Guide

**Last Updated:** January 2026  
**Purpose:** Quick reference for common issues, solutions, and frequently asked questions about Hololink camera systems.

---

## Table of Contents

1. [Quick Diagnostic Flowchart](#quick-diagnostic-flowchart)
2. [Common Issues and Solutions](#common-issues-and-solutions)
3. [Frequently Asked Questions](#frequently-asked-questions)
4. [Performance Troubleshooting](#performance-troubleshooting)
5. [Network and Connectivity](#network-and-connectivity)
6. [Image Quality Issues](#image-quality-issues)
7. [Debugging Checklist](#debugging-checklist)

---

## Quick Diagnostic Flowchart

```
START: Camera not working
    ↓
    ├─ Can ping 192.168.0.2?
    │  ├─ NO → [Network Issue] → Go to Network & Connectivity section
    │  └─ YES ↓
    │
    ├─ Can detect device with Enumerator.find_channel()?
    │  ├─ NO → [Discovery Issue] → Check firewall, network setup
    │  └─ YES ↓
    │
    ├─ Camera.configure(mode) succeeds?
    │  ├─ NO → [Configuration Issue] → Check register access
    │  └─ YES ↓
    │
    ├─ Camera.start() succeeds?
    │  ├─ NO → [Start Issue] → Check device state
    │  └─ YES ↓
    │
    ├─ Receiving frames from get_frame_iterator()?
    │  ├─ NO → [Frame RX Issue] → Check socket configuration
    │  └─ YES ↓
    │
    ├─ HolovizOp displays image?
    │  ├─ NO (Black screen) → [Viz Issue] → Check RGBA format
    │  └─ YES (Displaying) → ✓ SUCCESS
    │
    └─ Image quality acceptable?
       ├─ NO (Too dark/bright) → [Quality Issue] → Adjust exposure
       └─ YES → ✓ FULLY OPERATIONAL
```

---

## Common Issues and Solutions

### Issue 1: Cannot Detect Device

**Symptoms:**
```
TimeoutError: Device discovery timeout
Enumerator.find_channel() returns None
```

**Diagnostics:**
```bash
# Check network connectivity
ping -c 5 192.168.0.2

# Check if port is reachable
nc -uz 192.168.0.2 12321

# Monitor for incoming packets
tcpdump -i eth0 'host 192.168.0.2' -v
```

**Solutions (in order):**

| # | Solution | How to Test |
|---|----------|------------|
| 1 | Check power to device | LED indicators on device |
| 2 | Verify network cable | Replace cable with known-good |
| 3 | Configure host IP | `ip addr add 192.168.0.1/24 dev eth0` |
| 4 | Check firewall | `sudo ufw allow 12321/udp` |
| 5 | Reset device | Power cycle (off 5s, on) |
| 6 | Update Hololink library | `pip install --upgrade hololink` |
| 7 | Use different physical port | Try alternate ethernet port on host |

**Root Cause Breakdown:**

```python
# Example of proper device discovery with diagnostics
def diagnose_device_discovery():
    import socket
    from hololink import Enumerator
    
    # Step 1: Check network connectivity
    print("Step 1: Checking network connectivity...")
    try:
        result = socket.create_connection(("192.168.0.2", 12321), timeout=2)
        result.close()
        print("  ✓ Can connect to device IP:port")
    except Exception as e:
        print(f"  ✗ Cannot connect: {e}")
        print("    → Check: power, network cable, firewall, IP address")
        return False
    
    # Step 2: Try device discovery
    print("Step 2: Attempting device discovery...")
    try:
        channel = Enumerator.find_channel(
            channel_ip="192.168.0.2",
            timeout_s=10.0
        )
        print(f"  ✓ Discovered: {channel.device_ip}")
        return True
    except Exception as e:
        print(f"  ✗ Discovery failed: {e}")
        return False
```

---

### Issue 2: Black Screen in Fullscreen Visualization

**Symptoms:**
```
HolovizOp window opens
Screen shows pure black
No image visible
No errors in console
```

**Root Causes:** (in order of likelihood)

| # | Cause | Indicator | Fix |
|---|-------|-----------|-----|
| 1 | RGB instead of RGBA | Black screen immediately | `generate_alpha=True` |
| 2 | Wrong pool size | Works briefly then hangs | Recalculate: `width*height*4*2` |
| 3 | Missing alpha_value | Transparent/black | Set `alpha_value=65535` |
| 4 | Demosaic not connected | Black screen | Add flow: `add_flow(demosaic, viz)` |
| 5 | FrameCounterOp blocking | Black after 30 frames | Remove blocking gate |
| 6 | GPU memory exhausted | Sporadic black | Reduce pool num_blocks |
| 7 | CUDA context issue | Black on Mode 5 | Check reset_framework() |

**Quick Fix:**

```python
# WRONG (causes black screen)
demosaic = BayerDemosaicOp(
    ...,
    generate_alpha=False,  # ✗ WRONG
    # Missing alpha_value
    pool=BlockMemoryPool(block_size=1920*1080*3*2)  # ✗ WRONG (RGB)
)

# CORRECT
demosaic = BayerDemosaicOp(
    ...,
    generate_alpha=True,   # ✓ CORRECT
    alpha_value=65535,     # ✓ Full opacity
    pool=BlockMemoryPool(block_size=1920*1080*4*2)  # ✓ RGBA bytes
)
```

---

### Issue 3: Dropped Frames / FPS Lower Than Expected

**Symptoms:**
```
Expected FPS: 60.0
Actual FPS: 42.3
Frame gaps > 50ms
Estimated dropped frames: 3-5 per 100
```

**Investigation Steps:**

```python
def analyze_frame_drops():
    """Diagnose frame drop causes"""
    
    import subprocess
    import time
    
    print("Checking for frame drops...")
    
    # 1. Check network load
    print("\n1. Network utilization:")
    result = subprocess.run(
        ["iftop", "-i", "eth0", "-n", "-t", "-s", "1"],
        capture_output=True, timeout=2
    )
    print(result.stdout.decode())
    
    # 2. Check system load
    print("2. System CPU load:")
    result = subprocess.run(["top", "-bn", "1"], capture_output=True)
    lines = result.stdout.decode().split('\n')[0:5]
    for line in lines:
        print(f"  {line}")
    
    # 3. Check network stats
    print("3. Network errors:")
    result = subprocess.run(
        ["ethtool", "-S", "eth0"],
        capture_output=True
    )
    for line in result.stdout.decode().split('\n'):
        if "error" in line.lower() or "drop" in line.lower():
            print(f"  {line}")
    
    # 4. Check socket buffers
    print("4. Socket buffer usage:")
    result = subprocess.run(
        ["cat", "/proc/net/udp"],
        capture_output=True
    )
    print("  (Check RX queue column for backlog)")
```

**Solutions by Root Cause:**

| Root Cause | Indicator | Solution |
|-----------|-----------|----------|
| Network congestion | ethtool shows RX errors | Reduce other network traffic, use dedicated ethernet port |
| CPU overload | top shows >80% CPU | Reduce frame rate, simplify processing |
| Buffer overflow | Socket RX queue > 90% | Increase SO_RCVBUF, reduce frame size |
| Hardware timeout | Periodic 1-2s gaps | Increase timeout values, check voltage |
| Cleanup issue | Frames drop after 100 | Add `Hololink.reset_framework()` |
| Memory fragmentation | Gradually increasing gaps | Restart application |

**Fix Example:**

```python
# Before: drops ~5 frames per 100
def run_camera_mode_4():
    channel = Enumerator.find_channel("192.168.0.2")
    camera = sensors.imx258.Imx258(channel)
    camera.configure(mode=4)
    camera.start()
    
    frame_count = 0
    for frame in channel.get_frame_iterator():
        frame_count += 1
        if frame_count >= 300:
            break

# After: zero drops
def run_camera_mode_4_fixed():
    # 1. Increase socket buffer
    channel = Enumerator.find_channel("192.168.0.2")
    channel.socket.setsockopt(
        socket.SOL_SOCKET, 
        socket.SO_RCVBUF, 
        8388608  # 8MB instead of default 2MB
    )
    
    # 2. Configure with proper timeouts
    camera = sensors.imx258.Imx258(channel)
    camera.configure(mode=4)
    camera.start()
    
    # 3. Process with error handling
    frame_count = 0
    for frame in channel.get_frame_iterator():
        if frame is None:  # Timeout
            print(f"Frame {frame_count} timeout, checking device...")
            continue
        
        frame_count += 1
        if frame_count >= 300:
            break
    
    # 4. Proper cleanup
    camera.stop()
    channel.close()
    Hololink.reset_framework()
```

---

### Issue 4: Inconsistent Performance Between Runs

**Symptoms:**
```
First run: 59.87 FPS ✓
Second run: 47.32 FPS ✗
Third run: 95.23 FPS ✗
```

**Root Cause:** Hololink device registry caches packets from previous run

**Solution:**

```python
# Add this between runs!
from hololink import Hololink

# After first run cleanup
camera.stop()
channel.close()

# BEFORE second run starts
Hololink.reset_framework()  # ← CRITICAL!

# Now second run starts fresh
```

**Detailed Explanation:**

```
WITHOUT reset_framework():
┌────────────────────────────────────────────┐
│ Run 1: Mode 4 (1920×1080@60fps)           │
│ Sends frames at 60fps for 5 seconds       │
│ 300 frames captured                        │
│ device.close() → socket closed but...      │
│ → Buffered frames still in kernel queues  │
└────────────────────────────────────────────┘
         ↓ (no cleanup of global state)
┌────────────────────────────────────────────┐
│ Run 2: Mode 5 (4K@30fps)                   │
│ Expected: 30fps                            │
│ Actual: 60fps (old Mode 4 packets!)        │
│ Image glitches or frozen                   │
└────────────────────────────────────────────┘

WITH reset_framework():
┌────────────────────────────────────────────┐
│ Run 1: Mode 4 complete                     │
│ device.close()                              │
│ Hololink.reset_framework() ← Clears cache │
│ Flushes kernel packet queues               │
└────────────────────────────────────────────┘
         ↓ (clean state)
┌────────────────────────────────────────────┐
│ Run 2: Mode 5 starts fresh                 │
│ Expected: 30fps                            │
│ Actual: 30fps ✓                            │
│ No contamination from previous run         │
└────────────────────────────────────────────┘
```

---

### Issue 5: Device Hangs / Unresponsive

**Symptoms:**
```
Application freezes
No timeout, no error message
Process must be killed with -9
```

**Causes:**

| Cause | Indicator | Fix |
|-------|-----------|-----|
| Socket timeout disabled | Code never calls timeout | Add `socket.settimeout(5.0)` |
| Deadlock in cleanup | Hangs on app_thread.join() | Add timeout: `join(timeout=5)` |
| CUDA kernel stuck | Hangs on GPU operation | Reset CUDA device |
| Circular dependency | Frame loop never exits | Use CountCondition |
| Socket not created | Hangs on socket.bind() | Check socket configuration |

**Recovery:**

```bash
# Find the hanging process
ps aux | grep python

# Kill it forcefully
kill -9 <PID>

# Clear socket resources
sudo fuser -k 12321/udp
sudo fuser -k 50000/udp

# Reset network
sudo ifconfig eth0 down
sudo ifconfig eth0 up

# Restart application
python3 verify_camera_imx258.py --camera-mode 4
```

**Prevention:**

```python
# Add timeout to all blocking operations
def safe_frame_reception(channel, timeout_s=5.0):
    """Receive frames with timeout protection"""
    
    import signal
    
    def timeout_handler(signum, frame):
        raise TimeoutError("Frame reception timeout")
    
    # Set alarm
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(int(timeout_s))
    
    try:
        for frame in channel.get_frame_iterator():
            signal.alarm(0)  # Reset alarm
            yield frame
            signal.alarm(int(timeout_s))  # Restart for next frame
    finally:
        signal.alarm(0)  # Cancel alarm
```

---

## Frequently Asked Questions

### Q1: What's the difference between modes 2/3 and 4?

**A:** Modes 2-3 are broken (FRM_LENGTH < Y_OUT_SIZE), modes 4-5 are validated.

- **Mode 0-1:** Validated but older, same resolution as 4
- **Mode 2-3:** Never use (black frames)
- **Mode 4:** Recommended for 1080p (best for testing)
- **Mode 5:** Use for 4K resolution testing

### Q2: Why does fullscreen visualization show different brightness than saved images?

**A:** HolovizOp applies sRGB gamma correction (framebuffer_srgb=True).

```
HolovizOp display:     [sRGB gamma applied] → appears brighter
ImageSaverOp output:   [linear PNG] → appears darker

This is expected behavior, not a bug.

If you need matching brightness:
- Save normalized PNG with gamma: PIL.Image.apply(gamma_lut)
- Or disable sRGB in HolovizOp (slightly worse visual quality)
```

### Q3: How many frames should I expect to drop in a 300-frame capture?

**A:** Zero frames for validated modes.

```
Expected drops by mode:
├─ Mode 4 (1920×1080@60fps): 0 frames
├─ Mode 5 (4K@30fps):        0 frames
├─ Mode 0-1:                 0 frames (if configured correctly)
└─ Mode 2-3:                 All frames (broken)

If dropping > 1%: investigate network, cpu load, or cleanup issues
```

### Q4: Can I change exposure while streaming?

**A:** Yes, through register writes (experimental).

```python
# Configure mode first
camera.configure(mode=4)
camera.start()

# Then adjust exposure while running
camera.set_exposure(0x0800)  # Increase exposure

# New exposure applies to subsequent frames
```

**Note:** This is a camera register change, not a guarantee of smooth transition.

### Q5: What's the recommended test sequence?

**A:** [4, 5, 5, 4, 5]

```
Why this sequence?
├─ Starts with 1080p (simpler, less bandwidth)
├─ Tests 4K (requires more GPU/network resources)
├─ Repeats 4K to ensure stability
├─ Returns to 1080p to verify cleanup
└─ Final 4K test confirms recovery

This catches:
├─ Basic functionality (first 4)
├─ Resolution switching (4 → 5)
├─ Memory cleanup issues (5 → 4)
├─ GPU context preservation (4 → 5)
└─ System stability (final 5)
```

### Q6: How do I capture frames without visualization?

**A:** Use headless mode (no HolovizOp).

```python
# CLI
python3 verify_camera_imx258.py --camera-mode 4 --frame-limit 300
# (no --holoviz flag)

# Python
stats = verify_camera_imx258(
    camera_mode=4,
    frame_limit=300,
    save_images=False,
    fullscreen=False
)
# Frames counted but not displayed or saved
```

### Q7: How do I save screenshots of the visualization?

**A:** Use the ScreenShotOp operator (automatic in fullscreen+save mode).

```bash
# Enable full output
python3 verify_camera_imx258.py --camera-mode 4 --holoviz --save-images
# Saves both:
#  - frames/*.npy (raw frame data)
#  - frames/*.png (demosaiced images)
#  - screenshots/*.png (HolovizOp rendered output, with sRGB gamma)
```

### Q8: What does "max_gap_ms" in statistics mean?

**A:** Maximum time between consecutive frames.

```
Mode 4 (60fps):
  Expected gap: 1000ms / 60 = 16.67ms
  Normal range: 15-18ms
  Large gap (30ms): indicates 1 dropped frame
  
Mode 5 (30fps):
  Expected gap: 1000ms / 30 = 33.34ms
  Normal range: 32-35ms
  Large gap (50+ms): indicates 1+ dropped frames

Check these:
├─ max_gap_ms < 1.5x expected ✓ normal
├─ max_gap_ms > 1.5x expected ✗ investigate
└─ Estimated dropped frames > 0 ✗ investigate
```

---

## Performance Troubleshooting

### Baseline Performance

```
Test Conditions:
├─ Network: Direct ethernet connection
├─ CPU: Idle, no background processes
├─ GPU: Dedicated, no other tasks
├─ Temperature: Room temp (< 25°C)
└─ Image format: Bayer RAW10

Expected Results:
├─ Mode 4: 59.87 ± 0.5 FPS (within 99.16% of target)
├─ Mode 5: 29.94 ± 0.3 FPS (within 99.8% of target)
├─ Zero dropped frames: 300/300 frames minimum
├─ Max gap ≤ 20ms: (Mode 4) / 40ms (Mode 5)
└─ Network load ≤ 50%: confirmed with iftop
```

### Performance Degradation Checklist

```python
def diagnose_performance():
    """Check each factor affecting FPS"""
    
    checks = {
        "Network": check_network_load,
        "CPU": check_cpu_usage,
        "GPU": check_gpu_memory,
        "Temperature": check_device_temp,
        "Timeouts": check_socket_timeouts,
        "Cleanup": check_framework_state,
    }
    
    for name, check_func in checks.items():
        status = check_func()
        indicator = "✓" if status else "✗"
        print(f"{indicator} {name}")
```

---

## Network and Connectivity

### Network Setup Verification

```bash
# 1. Configure host interface
sudo ip addr add 192.168.0.1/24 dev eth0
sudo ip link set eth0 up

# 2. Verify connectivity
ping -c 5 192.168.0.2
# Expected: 5/5 received, <1ms latency

# 3. Check for packet loss
ping -c 100 192.168.0.2 | grep packet
# Expected: 0% packet loss

# 4. Verify ports
nc -uz 192.168.0.2 12321 && echo "Control port OK"
nc -uz 192.168.0.2 50000 && echo "Data port OK"

# 5. Check firewall
sudo ufw status | grep 12321
sudo ufw status | grep 50000
# Expected: ALLOW IN (or Status: inactive)
```

### Ethernet Optimization

```bash
# Increase buffer sizes (optional but recommended)
sudo sysctl -w net.core.rmem_max=134217728
sudo sysctl -w net.core.wmem_max=134217728

# Enable jumbo frames if supported (1500 MTU standard is fine)
ip link show eth0 | grep mtu

# Disable TCP offloading (can interfere with UDP timing)
sudo ethtool -K eth0 gro off gso off
```

---

## Image Quality Issues

### Dark Images (Too Low Brightness)

```
Causes (in order of likelihood):
├─ Exposure set too low
├─ Gain too low
├─ Lens obstruction
├─ Insufficient lighting
└─ Focus distance wrong

Fix:
camera.set_exposure(0x0800)  # Increase from 0x0600
camera.set_analog_gain(0x0180)  # Increase from 0x0100
camera.set_focus(-140)  # -140 = near focus
```

### Bright Images (Too High Brightness)

```
Causes:
├─ Exposure set too high
├─ Gain too high
├─ Excessive lighting
└─ Reflections

Fix:
camera.set_exposure(0x0400)  # Decrease from 0x0600
camera.set_analog_gain(0x0100)  # Decrease from 0x0180
```

### Blurry Images

```
Causes:
├─ Out of focus (focus distance wrong)
├─ Camera motion during capture
├─ Exposure too long

Fix:
camera.set_focus(-140)  # Adjust focus distance
camera.set_exposure(0x0400)  # Reduce exposure
# Or check for vibration/motion
```

### Noisy Images

```
Causes:
├─ Gain too high
├─ ISO too high (if available)
├─ Underexposed (forced to increase gain)

Fix:
camera.set_analog_gain(0x0100)  # Reduce gain to 1x
camera.set_exposure(0x0800)  # Increase exposure instead
```

---

## Debugging Checklist

**Before reporting an issue, verify:**

```
Network:
  [ ] Can ping 192.168.0.2
  [ ] No packet loss detected
  [ ] Both ports 12321 and 50000 accessible
  [ ] Firewall allows UDP traffic
  [ ] No other applications using ports

Device:
  [ ] Device power LED is on
  [ ] Network cable connected and lit
  [ ] Using supported ethernet adapter
  [ ] Device appears in Enumerator.find_channel()

Configuration:
  [ ] Using validated mode (4 or 5)
  [ ] Frame limit >= 100
  [ ] Timeout >= 5 seconds
  [ ] Min FPS threshold set correctly

Application:
  [ ] No other python instances running
  [ ] Sufficient disk space for frames
  [ ] GPU memory available (nvidia-smi)
  [ ] System CPU < 80% idle load

Cleanup:
  [ ] Previous run cleaned up properly
  [ ] No orphaned socket processes
  [ ] Hololink.reset_framework() called
  [ ] CUDA context destroyed
```

**If still failing:**

1. Collect logs: `python3 verify_camera_imx258.py --camera-mode 4 > debug.log 2>&1`
2. Run diagnostics: `python3 diagnose_device_discovery()`
3. Check hardware: Power cycle device, try different network port
4. Isolate issue: Test with simple socket read/write first
5. Report with: Mode ID, error message, network topology, log excerpt

---

## Related Documentation

- [IMX258 Camera Verification Guide](IMX258_CAMERA_VERIFICATION_GUIDE.md)
- [Hololink Communication Protocol](HOLOLINK_COMMUNICATION_PROTOCOL_GUIDE.md)
- [Implementation Best Practices](IMPLEMENTATION_BEST_PRACTICES.md)
- [Hololink Core API Reference](HOLOLINK_CORE_API_REFERENCE.md)

