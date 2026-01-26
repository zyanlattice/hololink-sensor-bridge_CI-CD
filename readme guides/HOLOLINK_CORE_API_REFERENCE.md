# Hololink Core API Reference

**Last Updated:** January 2026  
**Purpose:** Complete API documentation for Hololink core module - functions, classes, methods, arguments, and usage patterns.

---

## Table of Contents

1. [Core Classes](#core-classes)
2. [Device Management](#device-management)
3. [Communication Interfaces](#communication-interfaces)
4. [Reset and Cleanup](#reset-and-cleanup)
5. [Data Types and Enums](#data-types-and-enums)
6. [Usage Examples](#usage-examples)

---

## Core Classes

### 1. Hololink (Master Device Controller)

**File:** `hololink/core/hololink.hpp` / `hololink/core/hololink.cpp`

**Purpose:** Primary interface for all device control, register I/O, I2C, SPI, GPIO operations.

#### Constructor
```cpp
Hololink::Hololink(const std::string& ip_address, uint16_t port = 5000);
```

**Parameters:**
- `ip_address` (string): Device IP address (e.g., "192.168.0.2")
- `port` (uint16_t, optional): Control plane port (default: 5000)

**Example:**
```python
import hololink as hololink_module
channel = hololink_module.Enumerator.find_channel(channel_ip="192.168.0.2")
device = channel.hololink()
device.start()  # Begin communication
```

#### Key Methods

##### `start()`
```cpp
void Hololink::start();
```
- Opens network socket and initializes communication
- Must be called before any register/I2C/SPI operations
- Blocks until connection established
- **Raises:** Exception if device unreachable

##### `stop()`
```cpp
void Hololink::stop();
```
- Closes network socket and stops communication
- Gracefully shuts down all pending operations
- Safe to call multiple times
- Part of cleanup sequence

##### `reset()`
```cpp
void Hololink::reset();
```
- Performs FPGA/device reset via SPI
- Triggers registered ResetController callbacks
- Blocks until reset complete
- Device must be restarted with `start()` after reset

##### Register I/O Methods

###### `read_dword(address)`
```cpp
uint32_t Hololink::read_dword(uint32_t address);
```

**Parameters:**
- `address` (uint32_t): 32-bit register address

**Returns:** 32-bit value from register

**Example:**
```python
device = channel.hololink()
device.start()
value = device.read_dword(0x0340)  # Read FRM_LENGTH
device.stop()
```

###### `write_dword(address, value)`
```cpp
void Hololink::write_dword(uint32_t address, uint32_t value);
```

**Parameters:**
- `address` (uint32_t): 32-bit register address
- `value` (uint32_t): 32-bit value to write

**Example:**
```python
device.write_dword(0x0600, 0x1536)  # Write exposure register
```

###### `read_block(address, length)`
```cpp
std::vector<uint8_t> Hololink::read_block(uint32_t address, size_t length);
```

**Parameters:**
- `address` (uint32_t): Starting register address
- `length` (size_t): Number of bytes to read

**Returns:** Vector of bytes read from device

##### I2C Interface

###### `get_i2c(bus, address)`
```cpp
std::shared_ptr<I2C> Hololink::get_i2c(uint8_t bus, uint8_t address);
```

**Parameters:**
- `bus` (uint8_t): I2C bus number
- `address` (uint8_t): I2C slave address

**Returns:** Shared pointer to I2C interface

**Example:**
```python
i2c = device.get_i2c(bus=0, address=0x34)
i2c.write_byte(reg_addr, data)
value = i2c.read_byte(reg_addr)
```

##### SPI Interface

###### `get_spi(bus, chip_select, prescaler, cpol, cpha, width)`
```cpp
std::shared_ptr<Spi> Hololink::get_spi(
    uint8_t bus,
    uint8_t chip_select,
    uint8_t prescaler = 15,
    uint8_t cpol = 0,
    uint8_t cpha = 1,
    uint8_t width = 1
);
```

**Parameters:**
- `bus` (uint8_t): SPI bus number
- `chip_select` (uint8_t): Chip select line
- `prescaler` (uint8_t, optional): Clock prescaler (default: 15)
- `cpol` (uint8_t, optional): Clock polarity 0 or 1 (default: 0)
- `cpha` (uint8_t, optional): Clock phase 0 or 1 (default: 1)
- `width` (uint8_t, optional): Data width (default: 1)

**Returns:** Shared pointer to SPI interface

**Example:**
```python
spi = device.get_spi(bus=0, chip_select=0, prescaler=15)
spi.transfer(data_out, data_in)
```

---

### 2. DataChannel (Data Plane Configuration)

**File:** `hololink/core/data_channel.hpp` / `hololink/core/data_channel.cpp`

**Purpose:** Configures data plane connection (RoCe, COE, or emulation).

#### Constructor
```cpp
DataChannel::DataChannel(const ChannelMetadata& metadata);
```

**Parameters:**
- `metadata` (ChannelMetadata): Channel configuration from Enumerator

#### Key Methods

##### `hololink()`
```cpp
std::shared_ptr<Hololink> DataChannel::hololink();
```

**Returns:** Hololink instance for this data channel

**Example:**
```python
channel_metadata = hololink_module.Enumerator.find_channel(channel_ip="192.168.0.2")
data_channel = hololink_module.DataChannel(channel_metadata)
hololink = data_channel.hololink()
```

---

### 3. Enumerator (Device Discovery)

**File:** `hololink/core/enumerator.hpp` / `hololink/core/enumerator.cpp`

**Purpose:** Discovers and enumerates available Hololink devices on network.

#### Static Methods

##### `find_channel(channel_ip)`
```cpp
static std::shared_ptr<ChannelMetadata> Enumerator::find_channel(
    const std::string& channel_ip
);
```

**Parameters:**
- `channel_ip` (string): IP address of Hololink device (e.g., "192.168.0.2")

**Returns:** ChannelMetadata if found, nullptr otherwise

**Example:**
```python
channel_metadata = hololink_module.Enumerator.find_channel(channel_ip="192.168.0.2")
if channel_metadata:
    print("Device found!")
else:
    print("Device not found")
```

---

## Device Management

### Static Methods for Framework Control

#### `Hololink::reset_framework()`
```cpp
static void Hololink::reset_framework();
```

**Purpose:** Clears global registry of all Hololink device instances

**When to Use:**
- Between consecutive verification runs
- After `stop()` to prevent cached state contamination
- Before destroying CUDA context in cleanup sequence

**Important:** Must be called BEFORE CUDA context destruction

**Example:**
```python
# Run verification
verify_camera_functional(...)

# Cleanup sequence
hololink_module.Hololink.reset_framework()
cuda.cuCtxDestroy(cu_context)
```

---

## Communication Interfaces

### I2C Interface

**Methods:**
- `read_byte(address)` - Read single byte
- `write_byte(address, data)` - Write single byte
- `read_block(address, length)` - Read multiple bytes
- `write_block(address, data)` - Write multiple bytes

**Example: Camera I2C Control**
```python
i2c = device.get_i2c(bus=0, address=0x34)

# Read camera version
version_high = i2c.read_byte(0x0002)
version_low = i2c.read_byte(0x0003)
version = (version_high << 8) | version_low

# Write exposure setting
i2c.write_byte(0x0202, 0x15)  # Exposure time register
i2c.write_byte(0x0203, 0x36)
```

### SPI Interface

**Methods:**
- `transfer(out, in)` - Full-duplex SPI transfer
- `write(data)` - Write only
- `read(length)` - Read only

**Example: Device Reset via SPI**
```python
spi = device.get_spi(bus=0, chip_select=0, prescaler=15)
reset_command = [0x01, 0x00, 0x00, 0x00]
spi.write(reset_command)
```

---

## Reset and Cleanup

### Proper Cleanup Sequence

This is CRITICAL for consecutive verification runs:

```python
# 1. Stop frame reception
hololink.stop()

# 2. Wait for GXF graph to complete
app_thread.join(timeout=5.0)

# 3. CLEAR GLOBAL DEVICE REGISTRY (prevents frame contamination)
hololink_module.Hololink.reset_framework()

# 4. Destroy CUDA context
cuda.cuCtxDestroy(cu_context)
```

**Why This Order:**
- `hololink.stop()` closes socket, allowing receiver to unblock
- `reset_framework()` clears global device state before destroying CUDA
- Must happen BEFORE any new verification run

### Receiver Close Methods

Different receivers have specific close methods:

#### LinuxReceiverOperator
```cpp
void close();  // Sets flag for run() to return
```

#### RoceReceiverOperator
```cpp
void close();  // Terminates RoCE receiver
```

#### LinuxCoeReceiverOperator
```cpp
void close();  // Terminates CoE receiver
```

---

## Data Types and Enums

### ChannelMetadata

Returned by `Enumerator::find_channel()`, contains:
- IP address
- Port information
- Protocol type (RoCe, COE, Emulation)
- Device serial number

### Common Addresses (Register Map)

**Camera Timing Registers (IMX258):**
```
0x0340-0x0341 = FRM_LENGTH_LINES (frame length)
0x0342-0x0343 = LINE_LENGTH_PCK (line length)
0x034C-0x034D = X_OUT_SIZE (output width)
0x034E-0x034F = Y_OUT_SIZE (output height)
```

**Camera Exposure Registers:**
```
0x0202-0x0203 = COARSE_EXPOSURE_TIME
0x0204-0x0205 = ANALOG_GAIN
```

---

## Usage Examples

### Complete Device Initialization

```python
import hololink as hololink_module
from cuda import cuda

# 1. Discover device
channel_metadata = hololink_module.Enumerator.find_channel(
    channel_ip="192.168.0.2"
)
if not channel_metadata:
    print("Device not found!")
    exit(1)

# 2. Create data channel
data_channel = hololink_module.DataChannel(channel_metadata)

# 3. Initialize Hololink
hololink = data_channel.hololink()

# 4. Start communication
hololink.start()

# 5. Perform operations
i2c = hololink.get_i2c(bus=0, address=0x34)
version = i2c.read_byte(0x0002)
print(f"Camera version: {version}")

# 6. Cleanup (IMPORTANT!)
hololink.stop()
hololink_module.Hololink.reset_framework()
```

### Camera Configuration

```python
# Get I2C interface to camera
i2c = hololink.get_i2c(bus=0, address=0x34)

# Set focus
i2c.write_word(0x0300, 0xFF20)  # Focus position

# Set exposure (2 bytes)
i2c.write_byte(0x0202, 0x06)
i2c.write_byte(0x0203, 0x00)

# Set analog gain
i2c.write_word(0x0204, 0x0180)  # 1.5x gain

# Read back settings
exposure = i2c.read_word(0x0202)
gain = i2c.read_word(0x0204)
print(f"Exposure: {exposure}, Gain: {gain}")
```

### Register Read/Write

```python
# Read 32-bit register
value = hololink.read_dword(0x00001000)

# Write 32-bit register
hololink.write_dword(0x00001000, 0xDEADBEEF)

# Read block of data
data = hololink.read_block(0x00001000, 256)
print(f"Read {len(data)} bytes")
```

---

## Common Errors and Solutions

| Error | Cause | Solution |
|-------|-------|----------|
| Device unreachable | Wrong IP address | Verify IP with `Enumerator::find_channel()` |
| I2C operation fails | Bus number wrong | Check device datasheet for I2C bus |
| Register read returns 0 | Device not started | Call `hololink.start()` first |
| Frame gaps on next run | Global state cached | Call `Hololink::reset_framework()` |
| Socket timeout | Device overloaded | Increase timeout or reduce frame rate |

---

## Thread Safety

- Hololink class is **NOT thread-safe**
- Use separate Hololink instances for different threads
- I2C/SPI operations are **blocking**
- GXF operators handle threading internally

---

## Performance Considerations

- Register I/O latency: ~1-2ms per operation
- I2C operations: ~10-100µs depending on transfer size
- Frame reception: Limited by network (1Gbps ~ 240MB/s max)
- Multiple sequential I2C writes: Group into blocks when possible

---

## Related Files

- Implementation: `hololink/core/hololink.cpp` (1800+ lines)
- Header: `hololink/core/hololink.hpp`
- Serialization: `hololink/core/serializer.hpp`, `deserializer.hpp`
- Networking: `hololink/core/networking.hpp`
- Logging: `hololink/core/logging.hpp`

