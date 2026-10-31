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
    ULONGLONG g_sig_pending = 0;

    (void)param;
    if (!warp_open_map())
        warp_log("open map failed", (int)GetLastError());
    /* 构建戳：注入的是哪一版 DLL，日志里必须看得出来。
     * 真机排查踩过一次「源码改了、机器上跑的仍是上一版 DLL」，症状是读链
     * 语义对不上（新的 kind/step 全落进旧分支，输出全是垃圾值），从现象
     * 反推源码根本推不出来。编完看一眼这行就知道换没换新。 */
    warp_log("build " __DATE__ " " __TIME__ " proto v" WARP_STR(WARP_VERSION), 0);
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

        if (g_installed) {
            /* 钩子表变了就重装：插件在游戏运行中改配置不该逼用户重开。
               等 400ms 稳定期，避开 Python 端写表的中间状态。 */
            unsigned int sig = warp_hook_signature();
            ULONGLONG now2 = GetTickCount64();

            if (sig == g_hook_sig) {
                g_sig_pending = 0;
            } else if (!g_sig_pending) {
                g_sig_pending = now2;
            } else if (now2 - g_sig_pending > 400) {
                warp_log("hook table changed, reinstalling", 0);
                warp_uninstall();
                g_sig_pending = 0;
            }

            /* 装配阶段「类还没加载」的槽，每两秒回来补一次 —— il2cpp 的类
               是按需加载的，战斗类要等真的进战斗才存在。不补的话这些钩子
               一辈子装不上，插件表现成「逻辑不执行也不报错」。 */
            {
                static ULONGLONG last_retry;
                if (now2 - last_retry > 2000) {
                    last_retry = now2;
                    warp_retry_hooks();
                }
            }
            continue;
        }

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
