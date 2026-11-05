#!/usr/bin/env bash
# Independent candidate only; never writes addons/WarpHook/warp_host.dll.
set -euo pipefail
cd "$(dirname "$0")/../../.."
CC=${CC:-x86_64-w64-mingw32-gcc}
MH="mods/瓦伦希娜终极重置版本/source/third_party/minhook"
OUT="${TMPDIR:-/tmp}/warphookobj"
mkdir -p "$OUT"
"$CC" -shared -O2 -Wall -s -static-libgcc -o "$OUT/warp_host_candidate.dll" \
  addons/WarpHook/src/warp_*.c \
  "$MH/src/hook.c" "$MH/src/buffer.c" "$MH/src/trampoline.c" "$MH/src/hde/hde64.c" \
  -I addons/WarpHook/src -I "$MH/include" -I "$MH/src/hde"
sha256sum "$OUT/warp_host_candidate.dll"
