#!/usr/bin/env python3
"""
Start Streamlit dashboard with graceful shutdown support.
Run this instead of: streamlit run local_browser_dashboard.py

Supports:
  - Ctrl+C to stop
  - Graceful signal handling
  - Custom port support
"""

import subprocess
import sys
import signal

def main():
    port = 8501
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            print(f"Usage: python start_dashboard.py [port]")
            print(f"Default port: 8501")
            sys.exit(1)
    
    print(f"\n🚀 Starting Streamlit dashboard on port {port}...")
    print(f"📊 Open: http://localhost:{port}")
    print(f"⏹️  Press Ctrl+C to stop\n")
    
    cmd = [
        sys.executable, "-m", "streamlit", "run",
        "local_browser_dashboard.py",
        f"--server.port={port}",
        "--logger.level=info"
    ]
    
    try:
        process = subprocess.Popen(cmd)
        process.wait()
    except KeyboardInterrupt:
        print("\n\n⏹️  Stopping dashboard...")
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
        print("✓ Dashboard stopped")
        sys.exit(0)

if __name__ == "__main__":
    main()
