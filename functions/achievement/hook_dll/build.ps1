# functions/achievement/hook_dll/build.ps1  (ASCII only: PowerShell 5.1 reads .ps1 as ANSI without BOM)
# Build the battle event watcher DLL: battle_watch.c -> battle_watch.dll
# Requirements: MinGW-w64 gcc + MinHook sources
#   MinHook lookup order: -MinHookDir param > $env:LCTA_MINHOOK_DIR >
#                         default D:\LCTA_CheatingCore-main\vendor\minhook
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File functions\achievement\hook_dll\build.ps1
param([string]$MinHookDir = $env:LCTA_MINHOOK_DIR)
$ErrorActionPreference = "Stop"

$Here = $PSScriptRoot
$MinHookFallback = 'D:\LCTA_CheatingCore-main\vendor\minhook'

if (-not $MinHookDir) {
    if (Test-Path (Join-Path $MinHookFallback 'include\MinHook.h')) {
        $MinHookDir = $MinHookFallback
    }
}
if (-not $MinHookDir) {
    Write-Host "ERROR: MinHook dir not set. Pass -MinHookDir pointing to a dir containing include/MinHook.h" -ForegroundColor Red
    exit 1
}

$MinHookInclude = Join-Path $MinHookDir "include"
$MinHookHde = Join-Path $MinHookDir "src\hde"

$gcc = Get-Command gcc -ErrorAction SilentlyContinue
if (-not $gcc) {
    Write-Host "ERROR: gcc not found. Install MinGW-w64" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path (Join-Path $MinHookInclude 'MinHook.h'))) {
    Write-Host "ERROR: MinHook.h missing at $MinHookInclude\MinHook.h" -ForegroundColor Red
    exit 1
}

$src = Join-Path $Here "battle_watch.c"
$out = Join-Path $Here "battle_watch.dll"
$minhookSrcs = @(
    (Join-Path $MinHookDir "src\hook.c"),
    (Join-Path $MinHookDir "src\buffer.c"),
    (Join-Path $MinHookDir "src\trampoline.c"),
    (Join-Path $MinHookHde "hde64.c")
)

Write-Host "Building battle_watch.c -> battle_watch.dll ..."
gcc -shared -O2 -s -static-libgcc -o $out $src $minhookSrcs -I $MinHookInclude -I $MinHookHde
if ($LASTEXITCODE -ne 0) {
    Write-Host "Build FAILED" -ForegroundColor Red
    exit 1
}
Write-Host "Done: $out" -ForegroundColor Green
