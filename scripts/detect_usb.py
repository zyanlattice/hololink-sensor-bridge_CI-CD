# file: watch_usb_wmi.py
import time
import re
import sys

import win32com.client  # installed with pywin32
import pythoncom
import wmi  # pip install wmi

# HID Class GUID (official)
GUID_DEVCLASS_HIDCLASS = "{745A17A0-74D3-11D0-B6FE-00A0C90F57DA}"
# “Ports (COM & LPT)” Class GUID (often where USB-Serial/FTDI shows up)
GUID_DEVCLASS_PORTS = "{4d36e978-e325-11ce-bfc1-08002be10318}"
# FTDI USB vendor ID
FTDI_VID = "VID_0403"

# Simple heuristics to classify HID vs FTDI from WMI properties
def classify_device(pnp_device_id: str, class_guid: str, name: str) -> str:
    name_l = (name or "").lower()
    pnp_l = (pnp_device_id or "").upper()
    class_l = (class_guid or "").upper()

    # FTDI heuristics
    if FTDI_VID in pnp_l:
        return "FTDI (VID_0403 detected)"
    if "usb serial port" in name_l or "usb serial converter" in name_l or "ftdi" in name_l:
        return "Likely FTDI (USB-Serial)"

    # HID heuristics
    if class_l == GUID_DEVCLASS_HIDCLASS.upper():
        return "HID (HID class GUID)"
    if "hid-compliant" in name_l or "usb input device" in name_l:
        return "Likely HID"

    # Ports class could still be Prolific/Silabs/etc., not only FTDI
    if class_l == GUID_DEVCLASS_PORTS.upper():
        return "Serial (Ports class) – could be FTDI/Prolific/SiLabs; check VID/PID"

    return "Unknown (inspect VID/PID and ClassGuid)"

def main():
    print("Watching for newly added USB PnP devices… (Ctrl+C to stop)")
    # We watch for any new PnP entity; you can restrict to USB if desired
    c = wmi.WMI()

    # This event fires when a new PnP entity is created.
    # Win32_PnPEntity has useful fields: Name, PNPDeviceID, ClassGuid, Manufacturer, etc.
    watcher = c.watch_for(
        notification_type="Creation",
        wmi_class="Win32_PnPEntity"
    )

    while True:
        pythoncom.PumpWaitingMessages()
        try:
            evt = watcher()  # blocks until a device appears
            name = getattr(evt, "Name", None)
            pnpid = getattr(evt, "PNPDeviceID", None)
            class_guid = getattr(evt, "ClassGuid", None)
            mfg = getattr(evt, "Manufacturer", None)
            desc = getattr(evt, "Description", None)

            kind = classify_device(pnpid, class_guid, name)

            print("\n=== New PnP Device Detected ===")
            print(f"Name        : {name}")
            print(f"Description : {desc}")
            print(f"Manufacturer: {mfg}")
            print(f"ClassGuid   : {class_guid}")
            print(f"PNPDeviceID : {pnpid}")
            print(f"Classification → {kind}")
            print("Hint: In Device Manager, check Details → Hardware Ids for VID/PID.\n")

        except KeyboardInterrupt:
            print("\nStopping watcher.")
            sys.exit(0)
        except Exception as e:
            # Transient errors can happen during device churn; continue watching
            print(f"[warn] Event error: {e}")
            time.sleep(1)

if __name__ == "__main__":
    main()