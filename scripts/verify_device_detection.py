from holoscan.core import Application
import sys

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
        hololink_module.Enumerator().enumerated(on_meta, hololink_module.Timeout(timeout_seconds))
        
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