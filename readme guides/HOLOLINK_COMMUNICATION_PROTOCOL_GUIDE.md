# Hololink Communication Protocol Guide

**Last Updated:** January 2026  
**Purpose:** Complete reference for Hololink communication protocol, packet structures, command types, and message formats.

---

## Table of Contents

1. [Protocol Overview](#protocol-overview)
2. [Control Plane Messages](#control-plane-messages)
3. [Data Plane Overview](#data-plane-overview)
4. [Register Read/Write Operations](#register-readwrite-operations)
5. [Communication Examples](#communication-examples)
6. [Error Handling and Response Codes](#error-handling-and-response-codes)
7. [Network Configuration](#network-configuration)

---

## Protocol Overview

### Architecture

```
┌─────────────────────────────────────────────────┐
│             Hololink Device (192.168.0.2)       │
├─────────────────────────────────────────────────┤
│                                                 │
│  ┌──────────────┐      ┌──────────────┐        │
│  │ Control Plane│      │  Data Plane  │        │
│  │  (Port 12321)│      │ (Port 50000) │        │
│  └──────────────┘      └──────────────┘        │
│       ↑↓ Commands           ↑↓ Streams          │
│       ↑↓ (RD/WR Regs)       ↑↓ (Raw CSI)        │
│                                                 │
│  ┌──────────────┐      ┌──────────────┐        │
│  │ I2C Slave    │      │  GPIO Exp    │        │
│  │ (Registers)  │      │  (Focus/etc) │        │
│  └──────────────┘      └──────────────┘        │
│                                                 │
└─────────────────────────────────────────────────┘
         ↓
    Network (Ethernet 1Gbps)
         ↓
┌─────────────────────────────────────────────────┐
│    Host Machine (Python Application)            │
├─────────────────────────────────────────────────┤
│                                                 │
│  ┌──────────────┐      ┌──────────────┐        │
│  │   Control    │      │   Receiver   │        │
│  │   Socket     │      │   Socket     │        │
│  │  (TCP/UDP)   │      │  (UDP stream)│        │
│  └──────────────┘      └──────────────┘        │
│                                                 │
└─────────────────────────────────────────────────┘
```

### Transport Layers

| Plane | Purpose | Protocol | Port | Direction |
|-------|---------|----------|------|-----------|
| Control | Register R/W, Device Config | UDP/TCP | 12321 | Bidirectional |
| Data | Raw Camera Frame Streams | UDP | 50000+ | Device → Host |

---

## Control Plane Messages

### Message Structure

```
┌──────────────────────────────────────────────────────┐
│ Control Packet Format                                │
├──────────────────────────────────────────────────────┤
│ Byte 0-3:   Magic Header (0xDEADBEEF)               │
│ Byte 4-5:   Command Type (1 byte cmd + 1 byte data) │
│ Byte 6-7:   Sequence Number (for matching req/resp) │
│ Byte 8-11:  Address (register address)              │
│ Byte 12-15: Data (register value or length)         │
│ Byte 16-19: Checksum (CRC32)                        │
└──────────────────────────────────────────────────────┘
Total: 20 bytes minimum
```

### Command Types

#### 1. Register Write (WR_DWORD)

**Purpose:** Write 32-bit value to register

**Format:**
```
Byte 0-3:   0xDEADBEEF  (magic)
Byte 4:     0x01        (WR_DWORD command)
Byte 5:     0x00        (reserved)
Byte 6-7:   Sequence ID (e.g., 0x0001)
Byte 8-11:  Register address (big-endian)
Byte 12-15: Value to write (big-endian)
Byte 16-19: CRC32
```

**Example:** Write 0x6E to register 0x0307
```python
addr = 0x0307
value = 0x0000006E

packet = bytearray()
packet += bytes([0xDE, 0xAD, 0xBE, 0xEF])  # Magic
packet += bytes([0x01, 0x00])              # WR_DWORD
packet += bytes([0x00, 0x01])              # Seq ID
packet += addr.to_bytes(4, 'big')          # Address
packet += value.to_bytes(4, 'big')         # Value
packet += crc32(packet).to_bytes(4, 'big') # Checksum
```

**Response:**
```
Byte 0-3:   0xDEADBEEF
Byte 4:     0x01        (echo command)
Byte 5:     0x00        (status: 0=success)
Byte 6-7:   Sequence ID (matches request)
Byte 8-11:  0x00000000  (echo addr)
Byte 12-15: 0x00000000  (echo value)
Byte 16-19: CRC32
```

#### 2. Register Read (RD_DWORD)

**Purpose:** Read 32-bit value from register

**Format:**
```
Byte 0-3:   0xDEADBEEF
Byte 4:     0x02        (RD_DWORD command)
Byte 5:     0x00
Byte 6-7:   Sequence ID
Byte 8-11:  Register address
Byte 12-15: 0x00000000  (unused for reads)
Byte 16-19: CRC32
```

**Response:** Contains read value
```
Byte 0-3:   0xDEADBEEF
Byte 4:     0x02        (echo command)
Byte 5:     0x00        (status)
Byte 6-7:   Sequence ID
Byte 8-11:  Register address
Byte 12-15: [VALUE READ FROM REGISTER]
Byte 16-19: CRC32
```

#### 3. Block Write (WR_BLOCK)

**Purpose:** Write multiple registers in sequence

**Format:**
```
Byte 0-3:   0xDEADBEEF
Byte 4:     0x03        (WR_BLOCK command)
Byte 5:     0x00
Byte 6-7:   Sequence ID
Byte 8-11:  Base address
Byte 12-15: Block length (number of 32-bit words)
Byte 16+:   Data block (length × 4 bytes)
Byte -4-0:  CRC32
```

**Example:** Write 3 registers sequentially
```python
base_addr = 0x0300
values = [0x0000006E, 0x00000005, 0x000000FF]

packet = bytearray()
packet += bytes([0xDE, 0xAD, 0xBE, 0xEF])
packet += bytes([0x03, 0x00])              # WR_BLOCK
packet += bytes([0x00, 0x01])              # Seq ID
packet += base_addr.to_bytes(4, 'big')
packet += len(values).to_bytes(4, 'big')   # Block length
for val in values:
    packet += val.to_bytes(4, 'big')
packet += crc32(packet).to_bytes(4, 'big')
```

#### 4. Block Read (RD_BLOCK)

**Purpose:** Read multiple consecutive registers

**Format:**
```
Byte 0-3:   0xDEADBEEF
Byte 4:     0x04        (RD_BLOCK command)
Byte 5:     0x00
Byte 6-7:   Sequence ID
Byte 8-11:  Base address
Byte 12-15: Block length (number of words to read)
Byte 16-19: CRC32
```

**Response:**
```
Byte 0-3:   0xDEADBEEF
Byte 4:     0x04        (echo)
Byte 5:     0x00        (status)
Byte 6-7:   Sequence ID
Byte 8-11:  Base address
Byte 12-15: Block length
Byte 16+:   [DATA BLOCK - length × 4 bytes]
Byte -4-0:  CRC32
```

---

## Data Plane Overview

### Stream Configuration

```python
# Data streams established AFTER control channel ready
channel = Enumerator.find_channel(channel_ip="192.168.0.2")

# Data channel inherits from control channel
# Listens on dynamic UDP port (typically 50000+)
# Receives raw CSI data frames

for frame in channel.get_frame_iterator():
    # frame is raw CSI packet
    timestamp = frame.timestamp
    data = frame.payload    # Bayer or YUV data
    seq_num = frame.sequence
```

### Frame Packet Structure

```
┌─────────────────────────────────────┐
│ Frame Packet (UDP payload)          │
├─────────────────────────────────────┤
│ Byte 0-3:   Magic (0x12345678)      │
│ Byte 4-7:   Timestamp (microsec)    │
│ Byte 8-11:  Frame ID / Sequence     │
│ Byte 12-13: Width                   │
│ Byte 14-15: Height                  │
│ Byte 16-17: Format (RAW10, RAW12)   │
│ Byte 18+:   Image Data (variable)   │
│ Byte -4-0:  CRC32                   │
└─────────────────────────────────────┘
```

### Supported Frame Formats

| Format ID | Name | Bits/Pixel | Channels | Example Resolution |
|-----------|------|-----------|----------|-------------------|
| 0x0A | RAW10 Bayer | 10 | 1 | 1920×1080 |
| 0x0C | RAW12 Bayer | 12 | 1 | 3840×2160 |
| 0x18 | YUV422 | 16 | 3 (Y,U,V) | 1920×1080 |

---

## Register Read/Write Operations

### Sequential Camera Configuration

```python
from hololink import Enumerator, sensors

# 1. Find device
channel = Enumerator.find_channel(channel_ip="192.168.0.2")

# 2. Create camera sensor object
camera = sensors.imx258.Imx258(channel, camera_id=0)

# 3. Configure mode (sets FRM_LENGTH, LINE_LENGTH, etc.)
camera.configure(mode=4)  # 1920×1080@60fps

# 4. Set individual properties
camera.set_exposure(0x0600)      # Coarse integration time
camera.set_analog_gain(0x0180)   # Gain multiplier
camera.set_focus(-140)           # Focus distance

# 5. Start streaming
camera.start()

# 6. Read frames
for frame_num, frame in enumerate(channel.get_frame_iterator()):
    if frame_num >= 300:
        break
    process_frame(frame.payload)

# 7. Stop and cleanup
camera.stop()
channel.close()
```

### Direct Register Operations

```python
# Low-level register access
channel = Enumerator.find_channel("192.168.0.2")

# Write single register
channel.write_register(address=0x0307, value=0x0000006E)

# Read single register
value = channel.read_register(address=0x0307)
print(f"Read register 0x0307: {value:#010x}")

# Write block of registers
base_addr = 0x0300
block_values = [0x6E, 0x05, 0xFF, 0x10]
channel.write_block(base_addr, block_values)

# Read block
values = channel.read_block(address=0x0300, length=4)
for i, val in enumerate(values):
    print(f"Reg 0x{0x0300 + i*4:04X}: {val:#010x}")
```

---

## Communication Examples

### Example 1: Complete Device Initialization

```python
#!/usr/bin/env python3
import sys
from hololink import Enumerator, sensors

def initialize_camera():
    """Initialize camera and verify operation"""
    
    try:
        # Discover device
        channel = Enumerator.find_channel(
            channel_ip="192.168.0.2",
            timeout_s=5.0
        )
        print(f"✓ Connected to {channel.device_ip}")
        
        # Create camera controller
        camera = sensors.imx258.Imx258(channel, camera_id=0)
        print(f"✓ Camera controller created")
        
        # Configure for 4K mode
        camera.configure(mode=5)
        print(f"✓ Configured mode 5 (4K@30fps)")
        
        # Set exposure
        camera.set_exposure(0x0600)
        print(f"✓ Exposure set to 0x0600")
        
        # Start streaming
        camera.start()
        print(f"✓ Camera streaming started")
        
        # Read 10 frames to verify
        frame_count = 0
        for frame in channel.get_frame_iterator():
            frame_count += 1
            if frame_count >= 10:
                break
            print(f"  Frame {frame_count}: "
                  f"Timestamp={frame.timestamp}, "
                  f"Size={len(frame.payload)} bytes")
        
        print(f"✓ Received {frame_count} frames successfully")
        
        # Cleanup
        camera.stop()
        channel.close()
        print(f"✓ Camera stopped and cleaned up")
        
        return True
        
    except Exception as e:
        print(f"✗ Error: {e}")
        return False

if __name__ == "__main__":
    success = initialize_camera()
    sys.exit(0 if success else 1)
```

### Example 2: Frame Capture with Statistics

```python
#!/usr/bin/env python3
import time
from hololink import Enumerator, sensors

def capture_frames_with_stats(
    camera_mode=4,
    num_frames=300,
    output_dir="frames/"
):
    """Capture frames and track statistics"""
    
    import os
    os.makedirs(output_dir, exist_ok=True)
    
    channel = Enumerator.find_channel("192.168.0.2")
    camera = sensors.imx258.Imx258(channel, camera_id=0)
    camera.configure(mode=camera_mode)
    camera.start()
    
    # Statistics tracking
    timestamps = []
    frame_sizes = []
    start_time = time.time()
    
    try:
        for frame_num, frame in enumerate(channel.get_frame_iterator()):
            if frame_num >= num_frames:
                break
            
            timestamps.append(frame.timestamp)
            frame_sizes.append(len(frame.payload))
            
            # Save frame (optional)
            if frame_num % 30 == 0:
                filename = os.path.join(output_dir, f"frame_{frame_num:06d}.raw")
                with open(filename, 'wb') as f:
                    f.write(frame.payload)
            
            if (frame_num + 1) % 100 == 0:
                elapsed = time.time() - start_time
                fps = (frame_num + 1) / elapsed
                print(f"Frame {frame_num + 1}: FPS={fps:.2f}")
    
    finally:
        camera.stop()
        channel.close()
    
    # Analyze
    elapsed = time.time() - start_time
    actual_fps = frame_num / elapsed
    avg_frame_size = sum(frame_sizes) / len(frame_sizes)
    
    print(f"\nCapture Statistics:")
    print(f"  Frames: {frame_num + 1}")
    print(f"  Elapsed: {elapsed:.2f}s")
    print(f"  FPS: {actual_fps:.2f}")
    print(f"  Avg frame size: {avg_frame_size:.0f} bytes")
    print(f"  Data rate: {actual_fps * avg_frame_size / 1e6:.1f} MB/s")

if __name__ == "__main__":
    capture_frames_with_stats(camera_mode=4, num_frames=300)
```

---

## Error Handling and Response Codes

### Status Codes (Byte 5 in responses)

| Code | Meaning | Recovery |
|------|---------|----------|
| 0x00 | Success | Continue |
| 0x01 | Invalid command | Check command type |
| 0x02 | Invalid address | Verify register address |
| 0x03 | Write failure | Retry or reset device |
| 0x04 | Read timeout | Increase timeout, check network |
| 0x05 | CRC error | Re-send packet |
| 0x06 | Device not ready | Wait and retry |
| 0xFF | Unknown error | Reset and reconnect |

### Handling Errors in Python

```python
from hololink import Enumerator, ConnectionError, TimeoutError

try:
    # Attempt to find device
    channel = Enumerator.find_channel(
        channel_ip="192.168.0.2",
        timeout_s=10.0
    )
except TimeoutError:
    print("ERROR: Device not responding (timeout)")
    sys.exit(1)
except ConnectionError as e:
    print(f"ERROR: Network connection failed: {e}")
    sys.exit(1)

try:
    # Attempt to read register
    value = channel.read_register(0x0300)
except Exception as e:
    print(f"ERROR: Register read failed: {e}")
    if "CRC" in str(e):
        print("  → Likely network interference, retry")
    elif "timeout" in str(e).lower():
        print("  → Device not responding, check power/network")
    else:
        print("  → Unknown error, reset device")
    sys.exit(1)
```

### Network-Level Debugging

```bash
# Monitor control packets (requires tcpdump/Wireshark)
tcpdump -i eth0 'udp port 12321' -v

# Check device connectivity
ping -c 5 192.168.0.2

# Monitor frame stream
tcpdump -i eth0 'udp port 50000' -v | head -20

# Check network load
iftop -i eth0
```

---

## Network Configuration

### Prerequisites

```bash
# Host network configuration
# Configure host interface (e.g., eth0)
sudo ip addr add 192.168.0.1/24 dev eth0
sudo ip link set eth0 up

# Verify connectivity
ping 192.168.0.2

# Check UDP ports are not blocked
sudo ufw allow 12321/udp
sudo ufw allow 50000:50010/udp
```

### Python Socket Configuration

```python
import socket

# Control channel socket (typically auto-handled by Hololink)
control_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
control_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
control_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
control_socket.settimeout(5.0)
control_socket.connect(("192.168.0.2", 12321))

# Data channel socket (recv-only)
data_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
data_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2097152)  # 2MB buffer
data_socket.settimeout(1.0)
data_socket.bind(("0.0.0.0", 50000))
```

### Timeout Recommendations

| Operation | Timeout | Notes |
|-----------|---------|-------|
| Device discovery | 5-10s | First time, may be slow |
| Register read/write | 1-2s | Should be fast |
| Frame reception | 5-10s | Depends on FPS and frame size |
| Configuration | 3-5s | Multiple register writes |
| Cleanup/close | 2-3s | Allow graceful shutdown |

---

## Related Documentation

- [IMX258 Camera Verification Guide](IMX258_CAMERA_VERIFICATION_GUIDE.md)
- [Hololink Core API Reference](HOLOLINK_CORE_API_REFERENCE.md)
- [Implementation Best Practices](readme%20guides/IMPLEMENTATION_SUMMARY.md)

