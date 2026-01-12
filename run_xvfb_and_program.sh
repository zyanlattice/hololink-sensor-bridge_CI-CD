#!/usr/bin/env bash
set -euo pipefail
export TERM=dumb

# ----------------------------
# Usage
# ----------------------------
usage() {
  cat <<'USAGE'
Usage: run_xvfb_and_program.sh [--bitstream-path PATH] [--md5 MD5SUM]

Optional arguments:
  --bitstream-path   Path to the bitstream (.bit) file. Default:
                     /home/lattice/HSB/holoscan-sensor-bridge/fpga_cpnx_versa_0104_2507.bit
  --md5              Expected MD5 hash of the bitstream. Default:
                     7aad2f1676e08b54a4938306dcb7e437
  --help             Show this help and exit.

Environment variables (optional):
  DISPLAY_ID   Xvfb display (default: :0)
  XVFB_SCREEN  Xvfb screen definition (default: 1920x1080x24)
  WORK_DIR     Working directory to cd into (default: \$PWD)
USAGE
}

# ----------------------------
# Local defaults (no external passing required)
# ----------------------------
DISPLAY_ID="${DISPLAY_ID:-:0}"
XVFB_SCREEN="${XVFB_SCREEN:-1920x1080x24}"
WORK_DIR="${WORK_DIR:-$PWD}"

# Defaults for overridable parameters
BITSTREAM_PATH_DEFAULT="/home/lattice/HSB/holoscan-sensor-bridge/fpga_cpnx_versa_0104_2507.bit"
MD5_DEFAULT="7aad2f1676e08b54a4938306dcb7e437"

BITSTREAM_PATH="$BITSTREAM_PATH_DEFAULT"
BITSTREAM_MD5="$MD5_DEFAULT"

# ----------------------------
# Parse CLI arguments (long options)
# ----------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --bitstream-path)
      if [[ $# -lt 2 ]]; then
        echo "[ERROR] --bitstream-path requires a value." >&2
        exit 2
      fi
      BITSTREAM_PATH="$2"
      shift 2
      ;;
    --md5)
      if [[ $# -lt 2 ]]; then
        echo "[ERROR] --md5 requires a value." >&2
        exit 2
      fi
      BITSTREAM_MD5="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "[ERROR] Unknown argument: $1" >&2
      echo
      usage
      exit 2
      ;;
  esac
done

# ----------------------------
# Fixed command components
# ----------------------------
VERSION="2507"
PEER_IP="192.168.0.2"
MANIFEST="programmer_manifest.yaml"

# Build the app command with resolved parameters
APP_CMD=(
  ./Program_Bitstream.sh
  --version "$VERSION"
  --bitstream-path "$BITSTREAM_PATH"
  --peer-ip "$PEER_IP"
  --md5 "$BITSTREAM_MD5"
  --manifest "$MANIFEST"
)

# ----------------------------
# Pre-flight checks
# ----------------------------
echo "[INFO] Changing to working directory: $WORK_DIR"
cd "$WORK_DIR"

# Ensure required tools exist
if ! command -v Xvfb >/dev/null 2>&1; then
  echo "[ERROR] Xvfb not found. Please install it (e.g., 'sudo apt-get install xvfb')." >&2
  exit 1
fi

# Optional: verify the app script exists (if it's a file in this directory)
if [[ ! -x "./Program_Bitstream.sh" ]]; then
  echo "[WARN] ./Program_Bitstream.sh not found as an executable in $WORK_DIR."
  echo "      If it's in PATH or installed system-wide, this warning can be ignored."
fi

# ----------------------------
# Start Xvfb
# ----------------------------
display="$DISPLAY_ID"
screen="$XVFB_SCREEN"

cleanup() {
  echo "[INFO] Cleaning up Xvfb on $display"
  pkill -f "^Xvfb $display" 2>/dev/null || true
}
trap cleanup EXIT

echo "[INFO] Killing any existing Xvfb on $display"
pkill -f "^Xvfb $display" 2>/dev/null || true

LOG_FILE="/tmp/xvfb_${display//:/}.log"
echo "[INFO] Starting Xvfb $display with screen $screen (log: $LOG_FILE)"
nohup Xvfb "$display" -screen 0 "$screen" >"$LOG_FILE" 2>&1 &

# Give Xvfb a moment to initialize
sleep 1

echo "[INFO] Setting DISPLAY=$display"
export DISPLAY="$display"

# ----------------------------
# Run the app command
# ----------------------------
echo "[INFO] Running app: ${APP_CMD[*]}"
set +e
"${APP_CMD[@]}"
APP_EXIT=$?
set -e

if [[ $APP_EXIT -ne 0 ]]; then
  echo "[ERROR] App failed with exit code: $APP_EXIT"
  exit "$APP_EXIT"
else
  echo "[INFO] App completed successfully (exit: $APP_EXIT)"
fi

echo "[INFO] Done."
exit "$APP_EXIT"

