#!/usr/bin/env bash
set -euo pipefail

echo "architecture=$(uname -m)"
echo "macos=$(sw_vers -productVersion 2>/dev/null || echo unknown)"
ram_bytes="$(sysctl -n hw.memsize 2>/dev/null || echo 0)"
ram_gib="$(awk -v bytes="$ram_bytes" 'BEGIN {printf "%.1f", bytes/1024/1024/1024}')"
echo "ram_gib=$ram_gib"
echo "disk_available=$(df -h . | awk 'NR==2 {print $4}')"
echo "xcode_clt=$(xcode-select -p 2>/dev/null || echo missing)"
