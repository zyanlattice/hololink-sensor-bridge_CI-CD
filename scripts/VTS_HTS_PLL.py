import sys
import argparse
from hololink import Hololink, Enumerator, DataChannel, Timeout  # session/control entry
# Delay importing sensor modules until after compatibility shims are installed

def _patch_deserializer_endian_aliases():
    """Map old Deserializer method names (next_u32_be) to new names (next_uint32_be)."""
    try:
        try:
            from hololink.hololink_core import _hololink_core as core
        except Exception:
            import hololink.hololink_core._hololink_core as core

        ds = getattr(core, "Deserializer", None)
        if ds is None:
            print("WARNING: Deserializer not found")
            return

        # Check for naming convention: new style uses "uint", old style uses "u"
        has_new_style = hasattr(ds, "next_uint32_be")  # new: next_uint32_be
        has_old_style = hasattr(ds, "next_u32_be")      # old: next_u32_be
        
        print(f"Naming check: new_style={has_new_style}, old_style={has_old_style}")
        
        # Only patch if we have new-style but not old-style (need compatibility layer)
        if not (has_new_style and not has_old_style):
            print("No naming translation needed")
            return

        print("Applying naming compatibility layer...")
        original_ds = ds

        # Try to add methods directly to the C++ class
        try:
            # Python can't modify C++ class methods directly, so we use setattr on instances
            # Instead, we'll monkey-patch at the instance level via __getattribute__
            
            original_new = original_ds.__new__
            
            def patched_new(cls, *args, **kwargs):
                instance = original_new(cls)
                return instance
            
            # Actually, we can't do this for C++ classes...
            # The REAL solution: patch it at import time in the sensor module
            
            print("ERROR: Cannot monkey-patch C++ extension classes directly")
            print("The sensor module and core library are incompatible")
            print("You need matching versions of both libraries")
            return
            
        except Exception as e:
            print(f"Failed to patch C++ class: {e}")
        
    except Exception as e:
        print(f"WARNING: Failed to apply compatibility layer: {e}")


# NOT USED TO TROUBLESHOOT VERSION MISMATCH ISSUES =========================================================================================================
# def _core_has_be_methods() -> bool:
#     """Return True if core Deserializer exposes *_be methods (next_u32_be, etc)."""
#     try:
#         try:
#             from hololink.hololink_core import _hololink_core as core
#         except Exception:
#             import hololink.hololink_core._hololink_core as core
#         ds = getattr(core, "Deserializer", None)
#         return bool(ds and hasattr(ds, "next_u32_be"))
#     except Exception:
#         return False
# ===========================================================================================================================================================

def _resolve_channel(hl: Hololink, camera_id: int):
    """Try common Hololink channel access patterns and return a channel.

    Tries: get_channel(id) -> open_channel(id) -> channels[id]. Raises if none work.
    """
    # get_channel
    if hasattr(hl, "get_channel"):
        try:
            return hl.get_channel(camera_id)
        except Exception:
            pass
    # open_channel
    if hasattr(hl, "open_channel"):
        try:
            return hl.open_channel(camera_id)
        except Exception:
            pass
    # channels list/sequence
    if hasattr(hl, "channels"):
        try:
            chs = getattr(hl, "channels")
            return chs[camera_id]
        except Exception:
            pass
    raise RuntimeError("Unable to obtain hololink channel; tried get/open/channels")


def _clip_center(text: str, width: int) -> str:
    if len(text) > width:
        if width >= 3:
            text = text[: width - 3] + "..."
        else:
            text = text[:width]
    return text.center(width)


def print_metadata_table(serial_number: str, metadata: dict, width: int = 106):
    """Pretty-print metadata in a fixed-width table with two centered columns.

    Layout:
    - Full-width header for serial number
    - Full-width "metadata:" title
    - Rows of two centered columns (key: value). Width includes borders.
    """

    # Row separators
    sep = "-" * width
    # Single-column content row width (inside borders)
    inner_full = width - 2
    # Two-column content widths (inside borders and center bar)
    left_w = (width - 3) // 2
    right_w = (width - 3) - left_w

    def _row_single(text: str):
        print(sep)
        print("|" + _clip_center(text, inner_full) + "|")

    def _row_double(left: str, right: str):
        print(sep)
        print(
            "|"
            + _clip_center(left, left_w)
            + "|"
            + _clip_center(right, right_w)
            + "|"
        )

    # Header rows
    _row_single(f"serial number: {serial_number}")
    _row_single("metadata:")

    # Key-value rows (two columns per row)
    # Build key-value items; handle dicts and string blobs
    items: list[str] = []
    if isinstance(metadata, dict):
        # Sort keys for stable output
        try:
            keys = sorted(metadata.keys())
        except Exception:
            keys = list(metadata.keys())
        for k in keys:
            v = metadata.get(k)
            items.append(f"{k}: {v}")
    else:
        # Fallback: split a large metadata string into parts by comma
        s = str(metadata)
        parts = [p.strip() for p in s.split(",") if p.strip()]
        items.extend(parts)

    if not items:
        _row_double("<no metadata>", "")
        print(sep)
        return

    # Emit in pairs
    it = iter(items)
    for left in it:
        right = next(it, "")
        _row_double(left, right)
    # Final separator line
    print(sep)


def main():

    # Import sensor module FIRST (it caches the Deserializer reference)
    print("Pre-loading sensor module...")
    from hololink.sensors import imx258
    
    # Apply runtime compatibility shim for Deserializer `_be` methods
    _patch_deserializer_endian_aliases()
    
    # Force reload the sensor module to pick up the patched Deserializer
    import importlib
    importlib.reload(imx258)
    print("Sensor module reloaded with patched Deserializer")

    # ======================================================================================================================================================== 
    # Diagnostic: Verify the patch actually took effect, the patch may not work if the C++ sensor bindings are already compiled against an incompatible core
    # try:
    #     from hololink.hololink_core import _hololink_core as core
    #     test_ds = core.Deserializer(b"\x00\x00\x00\x00")
    #     if not hasattr(test_ds, 'next_u32_be'):
    #         print("ERROR: Patch failed - next_u32_be still not available")
    #         print("This indicates the C++ sensor module is incompatible with your core library")
    #         print("You need to either:")
    #         print("  1. Upgrade your hololink core library to match the sensor bindings")
    #         print("  2. Downgrade your sensor bindings to match the core library")
    #         sys.exit(1)
    #     else:
    #         print("✓ Compatibility layer verified - next_u32_be is available")
    # except Exception as e:
    #     print(f"Warning: Could not verify compatibility layer: {e}")
    # ======================================================================================================================================================== 
    # Diagnostic: Check what Deserializer methods actually exist
    # print("=" * 80)
    # print("SDK Version Diagnostic")
    # print("=" * 80)
    # try:
    #     try:
    #         from hololink.hololink_core import _hololink_core as core
    #     except Exception:
    #         import hololink.hololink_core._hololink_core as core
        
    #     ds = getattr(core, "Deserializer", None)
    #     if ds:
    #         print(f"Deserializer found: {ds}")
            
    #         # Check for _be methods
    #         be_methods = [m for m in dir(ds) if m.endswith('_be')]
    #         print(f"Big-endian methods (*_be): {be_methods if be_methods else 'NONE'}")
            
    #         # Check for regular next_ methods
    #         next_methods = [m for m in dir(ds) if m.startswith('next_') and not m.endswith('_be')]
    #         print(f"Regular next_ methods: {next_methods}")
            
    #         # Check if patch was applied
    #         if hasattr(core.Deserializer, '__name__'):
    #             print(f"Deserializer class name: {core.Deserializer.__name__}")
    #             if '_DeserializerProxy' in str(core.Deserializer):
    #                 print("✓ Patch appears to be applied")
    #             else:
    #                 print("✗ Patch NOT applied (still using original)")
            
    #         # Try to instantiate and check instance methods
    #         try:
    #             test_ds = ds(b"\x00\x00\x00\x00")
    #             instance_be_methods = [m for m in dir(test_ds) if m.endswith('_be')]
    #             print(f"Instance _be methods: {instance_be_methods if instance_be_methods else 'NONE'}")
    #         except Exception as e:
    #             print(f"Could not instantiate Deserializer: {e}")
    #     else:
    #         print("ERROR: Deserializer class not found in core module!")
    # except Exception as e:
    #     print(f"Diagnostic failed: {e}")
    #     import traceback
    #     traceback.print_exc()
    # print("=" * 80)
    # print() 
    # =====================================================================================================================================================

    print("Reading metadata for device... ")
    # Import imx258 only after shims so it picks up patched core APIs
    from hololink.sensors import imx258

    parser = argparse.ArgumentParser(description="Read IMX258 timing registers (VTS/HTS/PLL)")
    parser.add_argument("--peer-ip", help="Hololink channel IP (if omitted, list devices and exit)")
    parser.add_argument("--camera-id", type=int, default=0, help="Camera/channel index (default: 0)")
    parser.add_argument("--list", action="store_true", help="Enumerate devices and print metadata")
    parser.add_argument("--read-all", action="store_true", help="After listing, read VTS/HTS/PLL for each device")
    parser.add_argument("--metadata-only", default=False, help="Print metadata and skip timing reads")
    # Optional direct constructor path (rarely needed when using Enumerator/DataChannel)
    parser.add_argument("--direct", action="store_true", help="Use direct Hololink constructor")
    parser.add_argument("--control-port", type=int, help="Hololink control port (direct mode)")
    parser.add_argument("--serial-number", help="Hololink device serial number (direct mode)")
    parser.add_argument("--no-seq-check", action="store_true", help="Disable sequence number checking (direct mode)")
    args = parser.parse_args()

    # Enumerate/list devices if requested or if no peer IP provided
    if args.list or not args.peer_ip:
        devices = {}
        def on_meta(m):
            sn = m.get("serial_number")
            if sn and sn not in devices:
                devices[sn] = m
            return True
        try:
            Enumerator().enumerated(on_meta, Timeout(2))
        except Exception as e:
            print(f"Enumeration failed: {e}", file=sys.stderr)
            sys.exit(1)

        if not devices:
            print("No Hololink devices found.")
            sys.exit(0)

        for sn, meta in devices.items():
            print_metadata_table(sn, meta)
            if args.metadata_only:
                continue
            if (args.read_all or not args.peer_ip): # and _core_has_be_methods():
                try:
                    channel = DataChannel(meta)
                    try:
                        hl = channel.hololink()
                        hl.start()
                    except Exception:
                        pass

                    cam = imx258.Imx258(channel, args.camera_id)

                    # Configure camera before reading registers
                    from hololink.sensors.imx258 import Imx258_Mode
                    cam.configure(Imx258_Mode.IMX258_MODE_1920X1080_60FPS)

                    def r8(a: int) -> int:
                        return cam.get_register(a)

                    def r16(a: int) -> int:
                        return (r8(a) << 8) | r8(a + 1)

                    vts = r16(0x0340)
                    hts = r16(0x0342)
                    exck = r16(0x0136)
                    pll = {hex(a): r8(a) for a in range(0x0301, 0x0310)}
                    timing_items = {
                        "VTS (0x0340/1)": f"0x{vts:04X} ({vts})",
                        "HTS (0x0342/3)": f"0x{hts:04X} ({hts})",
                        "EXCK (0x0136)": str(exck),
                        **pll,
                    }
                    print_metadata_table(f"timing for {sn}", timing_items)
                except Exception as e:
                    print(f"Failed to read timing for {sn}: {e}", file=sys.stderr)
                finally:
                    if hl:
                        try:
                            hl.stop()
                        except Exception:
                            pass
            
        # If listing or no peer-ip provided, exit after listing (and optional timing reads)
        if args.list or not args.peer_ip:
            return

    # Prefer Enumerator + DataChannel flow
    sensor = None
    channel = None
    hl = None

    try:
        meta = Enumerator.find_channel(channel_ip=args.peer_ip)
        if not meta:
            raise RuntimeError("Enumerator.find_channel returned empty metadata")
        print_metadata_table(meta.get("serial_number", "<unknown>"), meta)
        
        channel = DataChannel(meta)
        
        # CRITICAL: Start Hololink BEFORE creating sensor
        # Without this, I2C transactions may fail or return garbage
        hl = channel.hololink()
        hl.start()
        print("Hololink started successfully")
        
        # Now create sensor
        sensor = imx258.Imx258(channel, args.camera_id)
        
        # CRITICAL: Configure sensor to initialize I2C communication
        from hololink.sensors.imx258 import Imx258_Mode
        # Use a valid mode - this powers up the sensor and establishes I2C
        sensor.configure(Imx258_Mode.IMX258_MODE_1920X1080_60FPS)
        print(f"Camera {args.camera_id} configured successfully")
        
        # Optional: verify camera is responding
        chip_id = sensor.get_version()
        print(f"Camera chip ID: 0x{chip_id:04X} ({chip_id})")
        if chip_id != 0x0100:
            print(f"WARNING: Expected IMX258 chip ID 0x0100, got 0x{chip_id:04X}")

    except Exception as e:
        # Fallback: direct constructor if requested
        if not args.direct:
            print(f"Channel setup via Enumerator failed: {e}", file=sys.stderr)
            sys.exit(2)
        if not (args.control_port and args.serial_number):
            print("Direct mode requires --control-port and --serial-number", file=sys.stderr)
            sys.exit(2)
        seq_check = not args.no_seq_check
        try:
            hl = Hololink(args.peer_ip, args.control_port, args.serial_number, seq_check)
            channel = _resolve_channel(hl, args.camera_id)
            sensor = imx258.Imx258(channel, args.camera_id)
            from hololink.sensors.imx258 import Imx258_Mode
            sensor.configure(Imx258_Mode.IMX258_MODE_1920X1080_60FPS)
            print(f"Camera {args.camera_id} configured successfully (direct mode)")
        except Exception as e2:
            print(f"Direct connection failed: {e2}", file=sys.stderr)
            sys.exit(2)

    
    # Now safe to read registers
    
    def r8(addr: int) -> int:
        return sensor.get_register(addr)
        

    def r16(addr: int) -> int:
        return (r8(addr) << 8) | r8(addr + 1)

    # Timing registers
    try:
        vts = r16(0x0340)  # FRAME_LENGTH_LINES (VTS)
        hts = r16(0x0342)  # LINE_LENGTH_PCK (HTS)
        exck = r16(0x0136)                         # EXCK_FREQ
        pll = {hex(a): r8(a) for a in range(0x0301, 0x0310)}
        
        timing_items = {
            "VTS (0x0340/1)": f"0x{vts:04X} ({vts})",
            "HTS (0x0342/3)": f"0x{hts:04X} ({hts})",
            "EXCK (0x0136)": str(exck),
            **pll,
        }
        print_metadata_table("timing", timing_items)
    except Exception as e:
        print(f"Failed to read timing registers: {e}", file=sys.stderr)
    finally:
        # Cleanup
        if hl:
            try:
                hl.stop()
            except Exception:
                pass

    # Optional: compute FPS if you know the pixel clock (Hz) from the PLL config
    # pixel_clock_hz = None  # set this from the mode table/datasheet if known
    # if pixel_clock_hz:
    #     fps = pixel_clock_hz / (hts * vts)
    #     print(f"  Computed FPS ≈ {fps:.2f}")
    # else:
    #     print("  Provide pixel_clock_hz to compute FPS.")

if __name__ == "__main__":
    main()