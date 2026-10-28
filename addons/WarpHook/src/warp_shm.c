/* warp_shm.c —— 共享内存：打开、校验、初始化视图指针
 *
 * 由 warp_host.c 拆分而来（原第 294-340 行）。
 */
#include "warp_internal.h"

/* ------------------------------------------------------------------ */
/* 共享内存                                                            */
/* ------------------------------------------------------------------ */

int warp_open_map(void)
{
    char name[256];
    DWORD n;

    if (g_map)
        return 1;

    n = GetEnvironmentVariableA("WARP_HOST_MAP", name, (DWORD)sizeof(name));
    if (n == 0 || n >= sizeof(name))
        lstrcpynA(name, "Local\\WarpHost_Default", (int)sizeof(name));

    g_map = OpenFileMappingA(FILE_MAP_ALL_ACCESS, FALSE, name);
    if (!g_map)
        g_map = CreateFileMappingA(INVALID_HANDLE_VALUE, NULL, PAGE_READWRITE,
                                   0, WARP_MAP_BYTES, name);
    if (!g_map)
        return 0;

    g_hdr = (WARP_HEADER *)MapViewOfFile(g_map, FILE_MAP_ALL_ACCESS, 0, 0, WARP_MAP_BYTES);
    if (!g_hdr) {
        warp_log("map view failed", (int)GetLastError());
        CloseHandle(g_map);
        g_map = NULL;
        return 0;
    }

    g_warp_hooks   = (WARP_HOOK *)((char *)g_hdr + WARP_HOOK_OFFSET);
    g_texts   = (char *)g_hdr + WARP_TEXTS_OFFSET;
    g_exports = (char *)g_hdr + WARP_EXPORTS_OFFSET;

    if (g_hdr->magic != WARP_MAGIC) {
        /* 第一次创建：把头部初始化干净，其余交给 Python 填 */
        ZeroMemory(g_hdr, WARP_MAP_BYTES);
        g_hdr->magic = WARP_MAGIC;
        g_hdr->version = WARP_VERSION;
        g_hdr->status = WARP_ST_IDLE;
        g_hdr->dedupe_ms = 800;
        warp_log("map created", WARP_MAP_BYTES);
    }
    return 1;
}

