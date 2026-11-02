/* warp_host.c —— 控制线程与入口
 *
 * 由 warp_host.c 拆分而来（原第 1128-1241 行）。
 */
#include "warp_internal.h"

/* 进程正在退出（由 DllMain 的 DETACH 置位）。这时控制线程只许安静退出，
 * 绝不能再碰 MinHook —— 见 warp_thread 末尾的说明。 */
static volatile LONG g_detaching = 0;

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
                    /* 先放行软锁，再标记 standalone：换曲锁这类锁着的钩子
                     * 会一直丢弃游戏自己的调用，启动器没了就再没人解锁，
                     * 战斗里会彻底没有 BGM。拦截类的钩子不受影响。 */
                    int released = warp_release_soft_locks();
                    g_hdr->standalone = 1;
                    warp_log("launcher gone, standalone", released);
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

    /* 进程退出时直接收工：MinHook 的 DisableHook 要挂起游戏里所有其它线程
     * 去回填原始字节，而这一刻系统正在拆线程（有的已经进了终止流程、有的
     * 卡在加载器锁里），挂起/恢复可能永远等不到回应 —— 表现就是「点退出，
     * 窗口卡住不动」。进程反正要结束了，补丁和被改写的代码页由 OS 一并回收，
     * 这里再补一次 DisableHook 没有收益，只有风险。 */
    if (!g_detaching) {
        warp_uninstall();
        warp_work_stop();
    }
    return 0;
}

/* ------------------------------------------------------------------ */
/* 入口                                                                */
/* ------------------------------------------------------------------ */

void warp_start(void)
{
    if (g_thread)
        return;
    /* Detours may still be on arbitrary game stacks after DisableHook. Pin
     * the module: FreeLibrary must not unmap their return addresses/code. */
    {
        HMODULE pinned;
        if (!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
                                GET_MODULE_HANDLE_EX_FLAG_PIN,
                                (LPCWSTR)(ULONG_PTR)warp_start, &pinned))
            return;
    }
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
    /* 先立退出标记，再叫醒线程：控制线程看到标记就直接 return。 */
    g_detaching = 1;
    if (g_stop)
        SetEvent(g_stop);
    /* Called under loader lock: never wait or unmap the shared view here.
     * A worker or detour can still use it. The pinned host/map are reclaimed
     * by the OS on process exit, not by racing an in-flight game callback. */
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
