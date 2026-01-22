#!/bin/bash
set -euo pipefail

version=""
bitstream_path=""
md5=""
peer_ip=""
max_saves=1
manifest=""


usage() {
  cat >&2 <<'EOF'
Usage: --version <version> --bitstream-path <bitstream_path> --peer-ip <peer_ip> [--md5 <md5>] [--manifest <manifest_path>] [--max-saves <number>]
EOF
  exit 2
}


# Parse long options; note the trailing ':' means the option requires a value #|| usage
PARSED_ARGS=$(getopt -o '' \
  -l version:,bitstream-path:,md5:,peer-ip:,manifest:,max-saves: -- "$@") 
eval set -- "$PARSED_ARGS"

while true; do
  case "$1" in
    --version)         version="$2"; shift 2 ;;
    --bitstream-path)  bitstream_path="$2"; shift 2 ;;
    --md5)             md5="$2"; shift 2 ;;
    --peer-ip)         peer_ip="$2"; shift 2 ;;
    --max-saves)      max_saves="$2"; shift 2 ;;
    --manifest)        manifest="$2"; shift 2 ;;  # expects a string value
    --) shift; break ;;
    *) usage ;;
  esac
done

# Basic validation
#if [[ -z "$version" || -z "$bitstream_path" || -z "$peer_ip" || -z "$md5"]]; then
if [[ -z "$version" || -z "$bitstream_path" || -z "$peer_ip" ]]; then
  usage
fi


################################### Debug ########################################

echo "Version:         $version"
echo "Bitstream Path:  $bitstream_path"
echo "MD5:             $md5"
echo "Peer IP:         $peer_ip"
echo "Manifest:        ${manifest:-<none>}"

###################################################################################

cd /home/lattice/HSB/holoscan-sensor-bridge
xhost +

# Get Docker configuration from demo.sh approach
ROOT="$(pwd)"
DOCKER_VERSION="$(cat VERSION)"
IMAGE_NAME="hololink-demo"

# Generate unique container name with timestamp
CONTAINER_NAME="demo_bitstream_prog"
#CONTAINER_NAME="demo_bitstream_prog_$(date +%Y%m%d_%H%M%S)"

# Clean up any existing container with this name (from previous failed runs)
echo "Checking for existing container..."
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  echo "Removing existing container: $CONTAINER_NAME"
  docker rm -f "$CONTAINER_NAME"
fi

# Cleanup function
cleanup() {
  local exit_code=$?
  echo ""
  printf '=%.0s' {1..90}
  echo " "
  if [ $exit_code -eq 0 ]; then
    echo "✓ Script completed successfully with exit code: $exit_code"
  else
    echo "✗ Script failed with exit code: $exit_code"
  fi
  printf '=%.0s' {1..90}
  echo ""
  exit $exit_code
}

# Set up trap to cleanup on script exit (success, failure, or Ctrl+C)
trap cleanup EXIT INT TERM

echo "Invoking Docker with bitstream environment variables..."


# Add -it only when stdout is a TTY
DOCKER_IT=()
if [[ -t 1 ]]; then
  DOCKER_IT=(-it)
fi

# Run Docker directly with all necessary flags
docker run "${DOCKER_IT[@]}" --rm \
  --net host \
  --gpus all \
  --runtime=nvidia \
  --shm-size=1gb \
  --privileged \
  --name "$CONTAINER_NAME" \
  -v "${ROOT}":"${ROOT}" \
  -v /home/lattice:/home/lattice \
  -v /sys/bus/pci/devices:/sys/bus/pci/devices \
  -v /sys/kernel/mm/hugepages:/sys/kernel/mm/hugepages \
  -v /dev:/dev \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v /tmp/argus_socket:/tmp/argus_socket \
  -v /sys/devices:/sys/devices \
  -v /var/nvidia/nvcam/settings:/var/nvidia/nvcam/settings \
  -w "${ROOT}" \
  -e NVIDIA_DRIVER_CAPABILITIES=graphics,video,compute,utility,display \
  -e NVIDIA_VISIBLE_DEVICES=all \
  -e DISPLAY="${DISPLAY}" \
  -e XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR}" \
  -e enableRawReprocess=2 \
  -e VERSION="$version" \
  -e BITSTREAM_PATH="$bitstream_path" \
  -e MD5="$md5" \
  -e PEER_IP="$peer_ip" \
  -e MAX_SAVES="$max_saves" \
  -e MANIFEST="$manifest" \
  "${IMAGE_NAME}:${DOCKER_VERSION}" bash -lc '/home/lattice/HSB/CI_CD/scripts/doc_py_script.sh'
  #${IMAGE_NAME}:${DOCKER_VERSION}" bash -lc 'cd /home/lattice/HSB/CI_CD && python3 bitstream_programmer_wrapper.py'



