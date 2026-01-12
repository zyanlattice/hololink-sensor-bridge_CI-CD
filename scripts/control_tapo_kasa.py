import argparse
import asyncio
import os
import sys
from typing import Optional
from kasa import Discover, Credentials

async def run_device(ip: str, email: str, password: str, plug_index: Optional[int] = None, toggle_on: Optional[int] = None, toggle_off :  Optional[int] = None, list_only: bool = False, check_children: bool = False):

    dev = await Discover.discover_single(ip, credentials=Credentials(email, password))
    try:
        await dev.update()
        print(dev)

        # List plugs (children) if this is a strip
        children = getattr(dev, "children", None) or []
        plug_cnt = len(children) + 1  # Including main device as plug 1
        if check_children:
            return len(children)

        if plug_cnt:
            if not toggle_on and not toggle_off and list_only is False:
                # Just show the state of the specified plug
                if plug_index is not None:
                    if plug_index < 0 or plug_index >= plug_cnt:
                        print(f"Error: plug index {plug_index} is out of range (1 to {plug_cnt-1})")
                        sys.exit(1)
                else:
                    print(f"Error: plug index 0 is out of range (1 to {plug_cnt-1})")
                    sys.exit(1)
                plug = children[plug_index-1]
                await plug.update()
                return print(f"Plug {plug_index}: alias={plug.alias} is {'on' if plug.is_on else 'off'}")

            if not toggle_on and not toggle_off and list_only:
                print(f"Plug count: {plug_cnt-1}")
                for idx, plug in enumerate(children):
                    # Refresh individual plug state and print details
                    await plug.update()
                    print(f"[{idx+1}] alias={plug.alias} is_on={plug.is_on}")

            if toggle_on:
                # Optionally toggle a specific plug
                await toggle_plug(plug_cnt, children, toggle_on=toggle_on)
            elif toggle_off:
                await toggle_plug(plug_cnt, children, toggle_off=toggle_off)
    finally:
        # Close underlying HTTP session to avoid aiohttp warnings
        if hasattr(dev, "protocol") and hasattr(dev.protocol, "close"):
            await dev.protocol.close()
   

async def toggle_plug(plug_cnt: int, children, toggle_on:  Optional[int] = None, toggle_off:  Optional[int] = None):
    
    if toggle_on is not None:
        if toggle_on < 0 or toggle_on >= plug_cnt:
            print(f"Error: plug index {toggle_on} is out of range (1 to {plug_cnt-1})")
            sys.exit(1)
        plug = children[toggle_on-1]
        await plug.update()
        if toggle_on:
            if not plug.is_on:
                await plug.turn_on()
                print(f"Plug {toggle_on} turned on")
            else:
                print(f"Plug {toggle_on} is already on")
    elif toggle_off is not None:
        if toggle_off < 0 or toggle_off >= plug_cnt:
            print(f"Error: plug index {toggle_off} is out of range (1 to {plug_cnt-1})")
            sys.exit(1)
        plug = children[toggle_off-1]
        await plug.update()
        if toggle_off:
            if plug.is_on:
                await plug.turn_off()
                print(f"Plug {toggle_off} turned off")
            else:
                print(f"Plug {toggle_off} is already off")
    else:
        print(f"Error: plug index 0 is out of range (1 to {plug_cnt-1})")
        sys.exit(1)
        
    
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Toggle or inspect Tapo/Kasa power strip plugs")
    # parser.add_argument("--ip", help="Device IP (TAPO_IP)")
    # parser.add_argument("--email", help="Account email (TAPO_EMAIL)")
    # parser.add_argument("--password", help="Account password (TAPO_PASSWORD)")
    parser.add_argument("--ip", help="Device IP (TAPO_IP)", default="192.168.1.136")
    parser.add_argument("--email", help="Account email (TAPO_EMAIL)", default="ZhengYan.Wong@latticesemi.com")
    parser.add_argument("--password", help="Account password (TAPO_PASSWORD)", default="password@lattice")
    parser.add_argument("--plug", type=int, default=None, help="Plug index to act on")
    parser.add_argument("--toggle_on", type=int, default=None, help="Turn on the specified plug")
    parser.add_argument("--toggle_off", type=int, default=None, help="Turn off the specified plug")
    parser.add_argument("--list", action="store_true", help="List device and plug information")
    parser.add_argument("--plug-state", type=int, default=None, help="Show the state of the specified plug")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    ip = args.ip #or os.getenv("TAPO_IP")
    email = args.email #or os.getenv("TAPO_EMAIL")
    password = args.password #or os.getenv("TAPO_PASSWORD")

    #missing = [name for name, val in (("--ip/TAPO_IP", ip), ("--email/TAPO_EMAIL", email), ("--password/TAPO_PASSWORD", password)) if not val]
    missing = [name for name, val in (("--ip", ip), ("--email", email), ("--password", password)) if not val]
    if missing:
        print("Missing required connection info: " + ", ".join(missing))
        print("Provide flags or set env vars TAPO_IP, TAPO_EMAIL, TAPO_PASSWORD.")
        raise SystemExit(2)

    # if args.plug is not None:
    #     args.plug -=1 # Convert to 0-based index
    # if args.plug_state is not None:
    #     args.plug_state -=1 # Convert to 0-based index    

    if args.list:
        # Just list device and plug info
        asyncio.run(run_device(ip, email, password, list_only=True))
    elif args.plug_state:
        # Just show the state of the specified plug
        asyncio.run(run_device(ip, email, password, args.plug_state))
    elif args.toggle_on or args.toggle_off:
        # Toggle the specified plug
        asyncio.run(run_device(ip, email, password, toggle_on=args.toggle_on, toggle_off=args.toggle_off))
    elif args.toggle_on is None or args.toggle_off is None:
        print(f"Error: plug index 0 is out of range (1 to {asyncio.run(run_device(ip, email, password, check_children=True))})")
    else:
        print("No action specified. Use --list, --plug_state, --toggle_on, or --toggle_off.")

if __name__ == "__main__":
    main()