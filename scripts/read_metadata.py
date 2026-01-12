import sys
import argparse
import json
import datetime
from typing import Any, Dict
import re

from hololink import Enumerator, DataChannel, Timeout


def _clip_center(text: str, width: int) -> str:
    if len(text) > width:
        if width >= 3:
            text = text[: width - 3] + "..."
        else:
            text = text[:width]
    return text.center(width)


# Helpers to make byte-like metadata JSON-safe and readable
def _parse_vector_uint8_string(s: str):
    if not isinstance(s, str) or "VectorUInt8[" not in s:
        return None
    try:
        inner = s[s.find("[") + 1 : s.rfind("]")]
        toks = [t.strip() for t in inner.split(",") if t.strip() and t.strip() != "..."]
        vals = []
        for t in toks:
            if all(c in "0123456789abcdefABCDEF" for c in t):
                vals.append(int(t, 16))
            else:
                vals.append(int(t))
        return vals
    except Exception:
        return None


def _normalize_hwaddr(v: Any) -> str | None:
    try:
        if isinstance(v, (bytes, bytearray, memoryview)):
            b = bytes(v)
            return ":".join(f"{x:02x}" for x in b)
        # Iterable of ints (works for VectorUInt8)
        if hasattr(v, "__iter__") and not isinstance(v, (str, bytes, bytearray, dict)):
            return ":".join(f"{int(x) & 0xFF:02x}" for x in v)
        if isinstance(v, str):
            parsed = _parse_vector_uint8_string(v)
            if parsed is not None:
                return ":".join(f"{x:02x}" for x in parsed)
    except Exception:
        return None
    return None


def _json_safe(obj: Any) -> Any:
    # Convert non-serializable types to primitives
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in obj.items():
            kl = str(k).lower()
            if kl in ("hardware_address", "hwaddr"):
                mac = _normalize_hwaddr(v)
                out[k] = mac if mac is not None else _json_safe(v)
            else:
                out[k] = _json_safe(v)
        return out
    if isinstance(obj, (bytes, bytearray, memoryview)):
        return list(bytes(obj))
    # Generic iterable of ints -> list[int]
    try:
        if hasattr(obj, "__iter__") and not isinstance(obj, (str, bytes, bytearray, dict)):
            seq = [int(x) for x in obj]
            return seq
    except Exception:
        pass
    # Fallback: leave as-is (json will handle primitives) or stringify
    return obj


def print_metadata_table(title: str, metadata: Dict[str, Any], width: int = 120, show_serial_header: bool = True) -> None:
    sep = "-" * width
    inner_full = width - 2
    left_w = (width - 3) // 2
    right_w = (width - 3) - left_w

    def _row_single(text: str):
        print(sep)
        print("|" + _clip_center(text, inner_full) + "|")

    def _row_double(left: str, right: str):
        print(sep)
        print(
            "|" + _clip_center(left, left_w) + "|" + _clip_center(right, right_w) + "|"
        )

    if show_serial_header and title:
        _row_single(title)
    _row_single("metadata:")

    items = []
    if isinstance(metadata, dict):
        try:
            keys = sorted(metadata.keys())
        except Exception:
            keys = list(metadata.keys())
        for k in keys:
            v = metadata.get(k)
            kl = str(k).lower()
            if kl in ("hardware_address", "hwaddr"):
                try:
                    seq = None
                    if isinstance(v, (bytes, bytearray, memoryview)):
                        seq = bytes(v)
                    elif not isinstance(v, (str, bytes, bytearray)) and hasattr(v, "__iter__"):
                        seq = list(v)
                    if seq is not None:
                        v = "(" + ", ".join(f"{int(x):02x}" for x in seq) + ")"
                except Exception:
                    pass
            items.append(f"{k}: {v}")
    else:
        s = str(metadata)
        parts = [p.strip() for p in s.split(",") if p.strip()]
        items.extend(parts)

    if not items:
        _row_double("<no metadata>", "")
        print(sep)
        return

    it = iter(items)
    for left in it:
        right = next(it, "")
        _row_double(left, right)
    print(sep)


def flatten(d: Dict[str, Any], prefix: str = "", out: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if out is None:
        out = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else str(k)
        if isinstance(v, dict):
            flatten(v, key, out)
        else:
            out[key] = v
    return out


def _get_by_path(meta: Any, path: str) -> Any:
    parts = [p for p in path.split(".") if p]
    cur = meta
    for p in parts:
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(p)
        elif hasattr(cur, "get"):
            try:
                cur = cur.get(p)
            except Exception:
                return None
        else:
            return None
    return cur


def _format_for_output(key: str, value: Any) -> Any:
    kl = key.lower()
    if kl in ("hardware_address", "hwaddr") or ("mac" in kl and "camera" not in kl):
        mac = _normalize_hwaddr(value)
        return mac if mac is not None else value
    return value


def search_metadata_value(peer_ip: str | None, key: str, timeout: int = 2) -> Any:
    # Prefer direct channel if peer_ip specified
    if peer_ip:
        meta = Enumerator.find_channel(channel_ip=peer_ip)
        if not meta:
            return None
        val = _get_by_path(meta, key)
        return _format_for_output(key, val)

    # Otherwise enumerate and return first device's value
    found: Any = None

    def on_meta(m: Dict[str, Any]):
        nonlocal found
        found = _get_by_path(m, key)
        return False  # stop after first

    try:
        Enumerator().enumerated(on_meta, Timeout(timeout))
    except Exception:
        return None
    return _format_for_output(key, found)


def main() -> None:
    
    # Avoid banner when using --searchmeta
    # (other scripts may parse stdout)

    parser = argparse.ArgumentParser(description="Read and print Hololink device metadata")
    parser.add_argument("--peer-ip", help="Hololink channel IP to query")
    parser.add_argument("--list", action="store_true", help="Enumerate devices and print metadata")
    parser.add_argument("--timeout", type=int, default=2, help="Enumeration timeout in seconds (default: 2)")
    parser.add_argument("--json", action="store_true", help="Output as JSON instead of a table")
    parser.add_argument("--flatten", action="store_true", help="Flatten nested metadata keys (dot notation)")
    parser.add_argument("--keys", nargs="*", help="Limit output to specific metadata keys (supports dot paths with --flatten)")
    parser.add_argument("--searchmeta", default="", help="Return only the value of the given metadata key (supports dotted paths). Suppresses normal output.")
    args = parser.parse_args()

    # If searching for a single metadata key, return just that value and exit
    if args.searchmeta:
        val = search_metadata_value(args.peer_ip, args.searchmeta, args.timeout)
        # Print only the value; no extra text
        if val is None:
            # Print empty line if not found (keeps CLI quiet)
            print("")
        else:
            print(val)
        return

    def emit(sn: str, meta: Dict[str, Any]):
        if args.flatten:
            meta_out = flatten(meta)
        else:
            meta_out = dict(meta)
        if args.keys:
            filtered = {k: meta_out.get(k) for k in args.keys}
        else:
            filtered = meta_out
        if args.json:
            payload = {
                "metadata": _json_safe(filtered)
            }
            text = json.dumps(payload, indent=2, sort_keys=True)
            print(text)
            # Also persist to a timestamped file in the current directory
            ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
            fname = f"hololink_meta_{ts}.json"
            try:
                with open(fname, "w", encoding="utf-8") as f:
                    f.write(text)
                print(f"Saved JSON to {fname}")
            except Exception as e:
                print(f"Failed to save JSON: {e}", file=sys.stderr)
        else:
            # serial number is part of metadata; avoid redundant header
            print_metadata_table(f"serial number: {sn}", filtered, show_serial_header=False)

    if args.list or not args.peer_ip:
        devices: Dict[str, Dict[str, Any]] = {}

        
        def on_meta(m: Dict[str, Any]):
            sn = m.get("serial_number") or m.get("serial") or m.get("sn") or "<unknown>"
            if sn not in devices:
                devices[sn] = m
            
            return True

        try:
            Enumerator().enumerated(on_meta, Timeout(args.timeout))
        except Exception as e:
            print(f"Enumeration failed: {e}", file=sys.stderr)
            sys.exit(1)

        if not devices:
            print("No Hololink devices found.")
            sys.exit(0)

        for sn, meta in devices.items():
            emit(sn, meta)
        return

    # Query a specific device by IP
    try:
        meta = Enumerator.find_channel(channel_ip=args.peer_ip)
        if not meta:
            raise RuntimeError("Enumerator.find_channel returned empty metadata")
        sn = meta.get("serial_number") or "<unknown>"
        emit(sn, meta)
    except Exception as e:
        print(f"Failed to read metadata: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
