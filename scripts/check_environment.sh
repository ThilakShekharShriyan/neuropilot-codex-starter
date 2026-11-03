#!/usr/bin/env bash
set +e
echo "== NeuroPilot environment check =="
echo "Architecture: $(uname -m)"
echo "macOS: $(sw_vers -productVersion 2>/dev/null || echo unknown)"
echo "Disk:"
df -h . 2>/dev/null | tail -n 1
echo
for bin in git rustc cargo python3 uv node pnpm; do
  if command -v "$bin" >/dev/null 2>&1; then
    printf "%-10s %s\n" "$bin" "$("$bin" --version 2>&1 | head -n 1)"
  else
    printf "%-10s MISSING\n" "$bin"
  fi
done
echo
if xcode-select -p >/dev/null 2>&1; then
  echo "Xcode CLT: $(xcode-select -p)"
else
  echo "Xcode CLT: MISSING"
fi
echo
echo "RAM:"
sysctl -n hw.memsize 2>/dev/null | awk '{printf "%.1f GiB\n", $1/1024/1024/1024}'
echo "Rust toolchain: $(rustup show active-toolchain 2>/dev/null || echo unavailable)"
echo "Note: this script reports only; it does not install or modify anything."
