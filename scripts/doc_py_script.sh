#!/usr/bin/env bash
set -euo pipefail



# Read from environment variables (passed from parent script)
version="${VERSION:-}"
bitstream_path="${BITSTREAM_PATH:-}"
md5="${MD5:-}"
peer_ip="${PEER_IP:-}"
manifest="${MANIFEST:-}"

echo "=== Received Environment Variables ==="
echo "Version:         $version"
echo "Bitstream Path:  $bitstream_path"
echo "MD5:             $md5"
echo "Peer IP:         $peer_ip"
echo "Manifest:        ${manifest:-<none>}"
echo "======================================"




cd /home/lattice/HSB/CI_CD
#python3 bitstream_programmer_wrapper.py 

# Run the Python script with the values from environment variables
if [[ -n "$manifest" ]]; then
  python3 scripts/bitstream_programmer_wrapper.py \
    --bitstream-path "$bitstream_path" \
    --version "$version" \
    --md5 "$md5" \
    --peer-ip "$peer_ip" \
    --manifest "$manifest"
else
  python3 scripts/bitstream_programmer_wrapper.py \
    --bitstream-path "$bitstream_path" \
    --version "$version" \
    --md5 "$md5" \
    --peer-ip "$peer_ip"
fi