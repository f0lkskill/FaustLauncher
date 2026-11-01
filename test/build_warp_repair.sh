#!/usr/bin/env bash
set -euo pipefail
GCC=/d/env/mingw64/bin/gcc.exe
MH=test/_bgmref2/BattleBGMExtend-main/src/third_party/minhook
COMMON=("$MH/src/hook.c" "$MH/src/buffer.c" "$MH/src/trampoline.c" "$MH/src/hde/hde64.c")
INC=(-I addons/WarpHook/src -I "$MH/include" -I "$MH/src/hde")
"$GCC" -shared -O2 -Wall -s -static-libgcc -o test/warp_host_native_candidate.dll addons/WarpHook/src/warp_*.c "${COMMON[@]}" "${INC[@]}"
SOURCES=()
for source in addons/WarpHook/src/warp_*.c; do
  case "$source" in */warp_host.c|*/warp_cmd.c) ;; *) SOURCES+=("$source");; esac
done
"$GCC" -O2 -Wall -static-libgcc -o test/warp_native_regression.exe test/warp_native_regression.c "${SOURCES[@]}" "${COMMON[@]}" "${INC[@]}"
echo 'Native candidate and regression built.'
