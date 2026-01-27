from holoscan.core import Application

import hololink as hololink_module

def main(timeout_seconds: int = 10) -> str:
    """Detect network interface connected to Hololink device."""
    print("Starting Hololink device detection...")
    
    try:
        devices = {}
        def on_meta(m):
            sn = m.get("serial_number")
            if sn and sn not in devices:
                devices[sn] = m
            return True
        hololink_module.Enumerator().enumerated(on_meta, hololink_module.Timeout(timeout_seconds))
        for _sn, meta in devices.items():
            iface = meta.get("interface") or meta.get("interface_name")
            if isinstance(iface, str) and iface:
                return iface
    except Exception:
        pass
    return None

if __name__ == "__main__":
    holoscan_app = Application()
    interface = main()
    if interface:
        print(f"Detected Hololink interface: {interface}")
    else:
        print("No Hololink interface detected.")