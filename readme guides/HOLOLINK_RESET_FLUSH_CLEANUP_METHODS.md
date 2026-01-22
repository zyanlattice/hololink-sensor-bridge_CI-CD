[text](scripts/verify_camera_imx258.py)# Hololink Source Code - Reset, Flush, Cleanup, and Resource Management Methods

## Summary

Found **5 main resource management methods** across the holoscan-sensor-bridge codebase. No explicit `flush()` or `cleanup()` methods found, but comprehensive reset and close mechanisms exist.

---

## Methods Found

### 1. **reset_framework()** - Static Method
**File:** [core/hololink.hpp](../../Downloads/holoscan-sensor-bridge/src/hololink/core/hololink.hpp#L252)  
**Line:** 252 (declaration)  
**Implementation:** [core/hololink.cpp](../../Downloads/holoscan-sensor-bridge/src/hololink/core/hololink.cpp#L193)  
**Implementation Line:** 193

**Signature:**
```cpp
static void Hololink::reset_framework();
```

**Purpose:** Clears the global registry of Hololink devices. Removes all hololink instances tracked in `hololink_by_serial_number` map.

**Implementation Code (lines 193-199 in hololink.cpp):**
```cpp
/*static*/ void Hololink::reset_framework()
{
    auto it = hololink_by_serial_number.begin();
    while (it != hololink_by_serial_number.end()) {
        HSB_LOG_INFO("Removing hololink \"{}\"", it->first);
        it = hololink_by_serial_number.erase(it);
```

---

### 2. **reset()** - Instance Method
**File:** [core/hololink.hpp](../../Downloads/holoscan-sensor-bridge/src/hololink/core/hololink.hpp#L277)  
**Line:** 277 (declaration)  
**Implementation:** [core/hololink.cpp](../../Downloads/holoscan-sensor-bridge/src/hololink/core/hololink.cpp#L266)  
**Implementation Line:** 266

**Signature:**
```cpp
void Hololink::reset();
```

**Purpose:** Performs FPGA/device reset by:
- Initializing SPI interface
- Sending reset commands
- Invoking registered ResetController callbacks

**Implementation Code (lines 266-314 in hololink.cpp):**
```cpp
void Hololink::reset()
{
    std::shared_ptr<Spi> spi = get_spi(RESET_SPI_BUS, /*chip_select*/ 0, /*prescaler*/ 15,
        /*cpol*/ 0, /*cpha*/ 1, /*width*/ 1);
    
    // ... reset logic ...
    
    reset_controller->reset();
}
```

---

### 3. **on_reset()** - Callback Registration
**File:** [core/hololink.hpp](../../Downloads/holoscan-sensor-bridge/src/hololink/core/hololink.hpp#L722)  
**Line:** 722 (declaration)  
**Implementation:** [core/hololink.cpp](../../Downloads/holoscan-sensor-bridge/src/hololink/core/hololink.cpp#L1567)  
**Implementation Line:** 1567

**Signature:**
```cpp
void Hololink::on_reset(std::shared_ptr<Hololink::ResetController> reset_controller);
```

**Purpose:** Registers a reset callback handler. Devices can use this to command reset operations.

**Implementation Code (lines 1567-1569 in hololink.cpp):**
```cpp
void Hololink::on_reset(std::shared_ptr<Hololink::ResetController> reset_controller)
{
    reset_controllers_.push_back(reset_controller);
}
```

---

### 4. **ResetController::reset()** - Virtual Interface
**File:** [core/hololink.hpp](../../Downloads/holoscan-sensor-bridge/src/hololink/core/hololink.hpp#L716)  
**Line:** 716 (declaration)

**Signature:**
```cpp
virtual void ResetController::reset() = 0;
```

**Purpose:** Pure virtual interface for implementing device-specific reset logic. Subclasses implement this method for their respective device reset procedures.

---

### 5. **close()** - Resource Cleanup Methods

#### **5a. LinuxReceiver::close()**
**File:** [operators/linux_receiver/linux_receiver.hpp](../../Downloads/holoscan-sensor-bridge/src/hololink/operators/linux_receiver/linux_receiver.hpp#L74)  
**Line:** 74 (declaration)  
**Implementation:** [operators/linux_receiver/linux_receiver.cpp](../../Downloads/holoscan-sensor-bridge/src/hololink/operators/linux_receiver/linux_receiver.cpp#L397)  
**Implementation Line:** 397

**Signature:**
```cpp
void LinuxReceiver::close();
```

**Purpose:** Sets a flag to encourage the `run()` method to return. Performs graceful shutdown of Linux receiver.

---

#### **5b. RoceReceiver::close()**
**File:** [operators/roce_receiver/roce_receiver.hpp](../../Downloads/holoscan-sensor-bridge/src/hololink/operators/roce_receiver/roce_receiver.hpp#L78)  
**Line:** 78 (declaration)  
**Implementation:** [operators/roce_receiver/roce_receiver.cpp](../../Downloads/holoscan-sensor-bridge/src/hololink/operators/roce_receiver/roce_receiver.cpp#L624)  
**Implementation Line:** 624

**Signature:**
```cpp
void RoceReceiver::close(); // causes the run method to terminate
```

**Purpose:** Causes the RoCE (RDMA over Converged Ethernet) receiver's run method to terminate gracefully.

---

#### **5c. LinuxCoeReceiver::close()**
**File:** [operators/linux_coe_receiver/linux_coe_receiver.hpp](../../Downloads/holoscan-sensor-bridge/src/hololink/operators/linux_coe_receiver/linux_coe_receiver.hpp#L86)  
**Line:** 86 (declaration)  
**Implementation:** [operators/linux_coe_receiver/linux_coe_receiver.cpp](../../Downloads/holoscan-sensor-bridge/src/hololink/operators/linux_coe_receiver/linux_coe_receiver.cpp#L410)  
**Implementation Line:** 410

**Signature:**
```cpp
void LinuxCoeReceiver::close();
```

**Purpose:** Sets a flag to encourage the `run()` method to return. Performs graceful shutdown of Linux CoE (Converged Ethernet) receiver.

---

### 6. **CutCopyPaste::reset()** - GUI Helper
**File:** [common/gui_renderer.hpp](../../Downloads/holoscan-sensor-bridge/src/hololink/common/gui_renderer.hpp#L71)  
**Line:** 71 (declaration)  
**Implementation:** [common/gui_renderer.cpp](../../Downloads/holoscan-sensor-bridge/src/hololink/common/gui_renderer.cpp#L110)  
**Implementation Line:** 110

**Signature:**
```cpp
void CutCopyPaste::reset();
```

**Purpose:** Resets GUI state for cut/copy/paste operations in the GUI renderer.

---

## Python Bindings

**File:** [emulation/hololink/emulation/__init__.py](../../Downloads/holoscan-sensor-bridge/src/hololink/emulation/hololink/emulation/__init__.py)

**Exposed Classes (via C++ pybind11):**
```python
from ._emulation import (
    DataPlane,
    DataPlaneID,
    HSBEmulator,
    IPAddress,
    LinuxDataPlane,
    SensorID,
)
```

The Python emulation module exposes the `HSBEmulator` and related classes via C++ bindings, but the specific reset/close methods are not explicitly re-exported in the `__init__.py`. They would be accessible through the C++ binding objects if exposed in the pybind11 wrapper code.

---

## Key Observations

1. **No explicit `flush()` method** - Resource management uses `close()` instead
2. **No explicit `cleanup()` method** - Destructor and `close()` methods handle cleanup
3. **Reset is two-tiered:**
   - `reset_framework()` - clears global device registry
   - `reset()` - performs device-specific reset via SPI
4. **Close methods are receiver-specific** - LinuxReceiver, RoceReceiver, LinuxCoeReceiver each have their own implementation
5. **ResetController pattern** - Uses callback interface for extensible device-specific resets
6. **GUI component has reset** - CutCopyPaste helper has its own reset for state management

