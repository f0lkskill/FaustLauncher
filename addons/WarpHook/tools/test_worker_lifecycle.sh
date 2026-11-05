#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../../.."
CC=${CC:-x86_64-w64-mingw32-gcc}
MH="mods/瓦伦希娜终极重置版本/source/third_party/minhook"
OUT="${TMPDIR:-/tmp}/warphookobj"
mkdir -p "$OUT"
SOURCES=(addons/WarpHook/src/warp_*.c)
KEEP=()
for src in "${SOURCES[@]}"; do
  [[ "$src" == */warp_cmd.c || "$src" == */warp_host.c ]] || KEEP+=("$src")
done
"$CC" -O2 -Wall -static-libgcc -o "$OUT/test_worker_lifecycle.exe" \
  addons/WarpHook/tools/test_worker_lifecycle.c "${KEEP[@]}" \
  "$MH/src/hook.c" "$MH/src/buffer.c" "$MH/src/trampoline.c" "$MH/src/hde/hde64.c" \
  -I addons/WarpHook/src -I "$MH/include" -I "$MH/src/hde"
"$OUT/test_worker_lifecycle.exe"
