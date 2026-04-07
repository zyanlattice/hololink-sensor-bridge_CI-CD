from holoscan.core import Application
import sys
import time

import hololink as hololink_module

def main(timeout_seconds: int = 10) -> tuple[bool, str, dict]:
    """Detect network interface connected to Hololink device."""
    print("Starting Hololink device detection...")
    
    metrics = {
        "timeout_seconds": timeout_seconds,
        "devices_found": 0,
        "serial_numbers": [],
        "interfaces": [],
        "detection_success": False,
    }
    
    try:
        devices = {}
        def on_meta(m):
            sn = m.get("serial_number")
            if sn and sn not in devices:
                devices[sn] = m
            return True
        
        # Retry logic to handle "Interrupted system call" errors when tests run back-to-back
        max_retries = 3
        retry_delay = 0.5  # Start with 500ms
        enumeration_success = False
        
        for attempt in range(max_retries):
            try:
                hololink_module.Enumerator().enumerated(on_meta, hololink_module.Timeout(timeout_seconds))
                enumeration_success = True
                break
            except RuntimeError as e:
                if "Interrupted system call" in str(e) and attempt < max_retries - 1:
                    print(f"⚠ Interrupted system call on attempt {attempt + 1}/{max_retries}, retrying after {retry_delay}s delay...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    raise
        
        if not enumeration_success:
            print(f"✗ Device enumeration failed after {max_retries} attempts")
            return False, f"Enumeration failed after {max_retries} attempts", metrics
        
        # Populate metrics
        metrics["devices_found"] = len(devices)
        
        for _sn, meta in devices.items():
            sn = meta.get("serial_number")
            if sn:
                metrics["serial_numbers"].append(sn)
            
            iface = meta.get("interface") or meta.get("interface_name")
            if isinstance(iface, str) and iface:
                metrics["interfaces"].append(iface)
                metrics["detection_success"] = True
                metrics["detected_interface"] = iface
                print(f"✓ Detected Hololink device: {sn} on interface {iface}")
                print(f"\n📊 Metrics: {metrics}")
                return True, f"Detected interface: {iface}", metrics
        
        # No valid interface found
        print("✗ No Hololink interface detected")
        print(f"\n📊 Metrics: {metrics}")
        return False, "No Hololink interface detected", metrics
        
    except Exception as e:
        metrics["error"] = str(e)
        print(f"✗ Error during detection: {e}")
        print(f"\n📊 Metrics: {metrics}")
        return False, f"Detection failed: {str(e)}", metrics

if __name__ == "__main__":
    holoscan_app = Application()
    success, message, metrics = main()
    if success:
        print(f"Detected Hololink interface: {metrics.get('detected_interface')}")
    else:
        print("No Hololink interface detected.")
    sys.exit(0 if success else 1)