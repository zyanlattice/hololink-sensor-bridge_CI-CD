"""
USB Relay Control Module
Cross-platform support for Windows and Ubuntu/Linux.

Dependencies:
- Windows: scripts/dll/USB_RELAY_DEVICE.dll
- Linux:   scripts/dll/usb_relay_device.so

Usage Option 1 - Context Manager (Automatic cleanup):
    from control_relay_dll import RelayController, relay_xon, relay_xoff
    
    with RelayController():
        relay_xon(1)   # Turn ON relay 1
        relay_xoff(1)  # Turn OFF relay 1
    # cleanup() called automatically

Usage Option 2 - Manual (Must call cleanup):
    from control_relay_dll import relay_xon, relay_xoff, initialize, cleanup
    
    initialize()
    relay_xon(1)
    relay_xoff(1)
    cleanup()  # Don't forget!
    
Direct run:
    python control_relay_dll.py
"""

import ctypes
import os
import platform
from ctypes import Structure, POINTER, c_char_p, c_int, c_void_p

# ============================================================================
# Library Setup
# ============================================================================

script_dir = os.path.dirname(os.path.abspath(__file__))
dll_dir = os.path.join(script_dir, "dll")

if platform.system() == "Windows":
    DLL_PATH = os.path.join(dll_dir, "USB_RELAY_DEVICE.dll")
else:  # Linux/Ubuntu
    DLL_PATH = os.path.join(dll_dir, "usb_relay_device.so")

# Device info structure
class USBRelayDeviceInfo(Structure):
    pass

USBRelayDeviceInfo._fields_ = [
    ("serial_number", c_char_p),
    ("device_path", c_char_p),
    ("type", c_int),
    ("next", POINTER(USBRelayDeviceInfo))
]

# Global state
_relay_lib = None
_device_handle = None
_device_info = None


def _load_library():
    """Load the USB relay library (lazy loading)."""
    global _relay_lib
    
    if _relay_lib is not None:
        return _relay_lib
    
    if not os.path.exists(DLL_PATH):
        raise FileNotFoundError(
            f"USB relay library not found: {DLL_PATH}\n"
            f"Expected location: {DLL_PATH}\n"
            f"Please ensure the USB relay library is installed:\n"
            f"  - Windows: USB_RELAY_DEVICE.dll\n"
            f"  - Linux:   usb_relay_device.so"
        )
    
    try:
        _relay_lib = ctypes.CDLL(DLL_PATH)
    except OSError as e:
        raise OSError(
            f"Failed to load USB relay library: {DLL_PATH}\n"
            f"Error: {e}\n"
            f"On Linux, you may need to install dependencies:\n"
            f"  sudo apt-get install libhidapi-dev libhidapi-hidraw0 libhidapi-libusb0"
        ) from e
    
    # Define function signatures
    _relay_lib.usb_relay_init.argtypes = []
    _relay_lib.usb_relay_init.restype = c_int

    _relay_lib.usb_relay_exit.argtypes = []
    _relay_lib.usb_relay_exit.restype = c_int

    _relay_lib.usb_relay_device_enumerate.argtypes = []
    _relay_lib.usb_relay_device_enumerate.restype = POINTER(USBRelayDeviceInfo)

    _relay_lib.usb_relay_device_free_enumerate.argtypes = [POINTER(USBRelayDeviceInfo)]
    _relay_lib.usb_relay_device_free_enumerate.restype = None

    _relay_lib.usb_relay_device_open.argtypes = [POINTER(USBRelayDeviceInfo)]
    _relay_lib.usb_relay_device_open.restype = c_void_p

    _relay_lib.usb_relay_device_close.argtypes = [c_void_p]
    _relay_lib.usb_relay_device_close.restype = None

    _relay_lib.usb_relay_device_open_one_relay_channel.argtypes = [c_void_p, c_int]
    _relay_lib.usb_relay_device_open_one_relay_channel.restype = c_int

    _relay_lib.usb_relay_device_close_one_relay_channel.argtypes = [c_void_p, c_int]
    _relay_lib.usb_relay_device_close_one_relay_channel.restype = c_int

    _relay_lib.usb_relay_device_open_all_relay_channel.argtypes = [c_void_p]
    _relay_lib.usb_relay_device_open_all_relay_channel.restype = c_int

    _relay_lib.usb_relay_device_close_all_relay_channel.argtypes = [c_void_p]
    _relay_lib.usb_relay_device_close_all_relay_channel.restype = c_int
    
    return _relay_lib

# ============================================================================
# Public API
# ============================================================================

def initialize():
    """
    Initialize the USB relay library and open the first device.
    Call this before using relay_xon() or relay_xoff().
    
    Returns:
        bool: True if successful, False otherwise
    """
    global _device_handle, _device_info
    
    # Load library (lazy loading)
    relay_lib = _load_library()
    
    # Initialize library
    result = relay_lib.usb_relay_init()
    if result != 0:
        return False
    
    # Enumerate devices
    _device_info = relay_lib.usb_relay_device_enumerate()
    if not _device_info:
        relay_lib.usb_relay_exit()
        return False
    
    # Open first device
    _device_handle = relay_lib.usb_relay_device_open(_device_info)
    if not _device_handle:
        relay_lib.usb_relay_device_free_enumerate(_device_info)
        relay_lib.usb_relay_exit()
        return False
    
    return True


def relay_xon(relay):
    """
    Turn ON a specific relay.
    
    Args:
        relay (int): Relay number (1-4 for 4-channel board)
    
    Returns:
        bool: True if successful, False otherwise
    """
    if _device_handle is None:
        raise RuntimeError("Relay not initialized. Call initialize() first.")
    
    relay_lib = _load_library()
    result = relay_lib.usb_relay_device_open_one_relay_channel(_device_handle, relay)
    return result == 0


def relay_xoff(relay):
    """
    Turn OFF a specific relay.
    
    Args:
        relay (int): Relay number (1-4 for 4-channel board)
    
    Returns:
        bool: True if successful, False otherwise
    """
    if _device_handle is None:
        raise RuntimeError("Relay not initialized. Call initialize() first.")
    
    relay_lib = _load_library()
    result = relay_lib.usb_relay_device_close_one_relay_channel(_device_handle, relay)
    return result == 0


def cleanup():
    """
    Clean up resources and close the device.
    Call this when done using relays.
    """
    global _device_handle, _device_info
    
    relay_lib = _load_library()
    
    if _device_handle:
        relay_lib.usb_relay_device_close(_device_handle)
        _device_handle = None
    
    if _device_info:
        relay_lib.usb_relay_device_free_enumerate(_device_info)
        _device_info = None
    
    relay_lib.usb_relay_exit()


class RelayController:
    """
    Context manager for automatic cleanup.
    
    Usage:
        with RelayController():
            relay_xon(1)
            relay_xoff(1)
        # cleanup() called automatically
    """
    def __enter__(self):
        if not initialize():
            raise RuntimeError("Failed to initialize relay device")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        cleanup()
        return False


# ============================================================================
# Example Usage (when run as script)
# ============================================================================

def sample():
    import time
    
    print("=" * 60)
    print("USB Relay Control - Example Usage")
    print("=" * 60)
    
    # Example 1: Using context manager (recommended - auto cleanup)
    print("\nExample 1: Context Manager (auto cleanup)")
    print("-" * 60)
    with RelayController():
        print("✓ Device initialized")
        print("  Turning ON relay 1...")
        relay_xon(1)
        print("  ✓ Relay 1 ON")
        time.sleep(1)
        
        print("  Turning OFF relay 1...")
        relay_xoff(1)
        print("  ✓ Relay 1 OFF")
    print("✓ Auto cleanup completed\n")
    
    # Example 2: Manual management
    print("Example 2: Manual Management")
    print("-" * 60)
    if not initialize():
        print("ERROR: Failed to initialize")
        exit(1)
    
    print("✓ Device initialized")
    print("  Turning ON relay 2...")
    relay_xon(2)
    print("  ✓ Relay 2 ON")
    time.sleep(1)
    
    print("  Turning OFF relay 2...")
    relay_xoff(2)
    print("  ✓ Relay 2 OFF")
    
    cleanup()
    print("✓ Manual cleanup completed\n")
    
    print("=" * 60)
    print("Done!")
    print("=" * 60)

def main():
    try:
        sample()
    except Exception as e:
        print(f"Error: {e}")
        print("Make sure the USB relay is connected and the appropriate DLL/so file is in the 'dll' folder.")


if __name__ == "__main__":
    main()
