/* warp_host.c —— 控制线程与入口
 *
 * 由 warp_host.c 拆分而来（原第 1128-1241 行）。
 */
#include "warp_internal.h"

/* ------------------------------------------------------------------ */
/* 控制线程                                                            */
/* ------------------------------------------------------------------ */

DWORD WINAPI warp_thread(LPVOID param)
{
    ULONGLONG start = GetTickCount64();

    (void)param;
    if (!warp_open_map())
        warp_log("open map failed", (int)GetLastError());
    warp_status(WARP_ST_IDLE, WARP_ERR_OK);

    for (;;) {
        if (WaitForSingleObject(g_stop, WARP_POLL_MS) == WAIT_OBJECT_0)
            break;

        if (!g_hdr)
            continue;

        /* 心跳：启动器断开后进入 standalone，继续按内存快照跑 */
        if (g_hdr->heartbeat != 0) {
            ULONGLONG now = GetTickCount64();
            DWORD beat = (DWORD)g_hdr->heartbeat;
            if (now > WARP_HB_STALE_MS && (DWORD)(now - beat) > WARP_HB_STALE_MS) {
                if (!g_hdr->standalone) {
                    g_hdr->standalone = 1;
                    warp_log("launcher gone, standalone", 1);
                }
            }
        }

        if (g_installed)
            continue;

        if (!GetModuleHandleW(L"GameAssembly.dll")) {
            if (GetTickCount64() - start > WARP_GA_TIMEOUT_MS) {
                warp_status(WARP_ST_ERROR, WARP_ERR_GA_TIMEOUT);
                start = GetTickCount64();   /* 重置，别一直刷 */
            }
            continue;
        }
        if (g_hdr->ga_found < 1)
            g_hdr->ga_found = 1;
        warp_status(WARP_ST_LOADING, WARP_ERR_OK);

        if (!warp_wait_ready())
            continue;

        warp_install_hooks();
    }

    warp_uninstall();
    return 0;
}

/* ------------------------------------------------------------------ */
/* 入口                                                                */
/* ------------------------------------------------------------------ */

void warp_start(void)
{
    if (g_thread)
        return;
    g_rng = (unsigned int)(GetTickCount64() ^ (ULONGLONG)(ULONG_PTR)&g_rng);
    g_stop = CreateEventW(NULL, TRUE, FALSE, NULL);
    if (!g_stop)
        return;
    g_thread = CreateThread(NULL, 0, warp_thread, NULL, 0, NULL);
    if (g_thread)
        CloseHandle(g_thread);
}

void warp_stop_cleanup(void)
{
    if (g_stop)
        SetEvent(g_stop);
    /* 不同步等待：在 DllMain 里等线程会和 loader lock 抢，实测会卡死 */
    if (g_hdr) {
        UnmapViewOfFile(g_hdr);
        g_hdr = NULL;
    }
    if (g_map) {
        CloseHandle(g_map);
        g_map = NULL;
    }
}

BOOL APIENTRY DllMain(HMODULE module, DWORD reason, LPVOID reserved)
{
    (void)reserved;

    if (reason == DLL_PROCESS_ATTACH) {
        g_hinst = module;
        DisableThreadLibraryCalls(module);
        warp_start();
    } else if (reason == DLL_PROCESS_DETACH) {
        warp_stop_cleanup();
    }
    return TRUE;
}

/* 供调试/测试查询 */
__declspec(dllexport) int WarpHostVersion(void)
{
    return WARP_VERSION;
}

__declspec(dllexport) int WarpHostState(void)
{
    if (!g_hdr)
        return -1;
    return g_hdr->status;
}
