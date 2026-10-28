/* warp_popup.c —— 原版弹窗 + 结束进程
 *
 * 由 warp_host.c 拆分而来（原第 551-638 行）。
 */
#include "warp_internal.h"

/* ------------------------------------------------------------------ */
/* 原版弹窗                                                            */
/* ------------------------------------------------------------------ */

void warp_resolve_popup(void *domain)
{
    void *klass;

    if (g_popup_mgr_method && g_popup_open_method) {
        if (g_hdr)
            g_hdr->popup_ok = 1;
        return;
    }

    klass = warp_find_class(domain, "GlobalGameManager");
    if (klass) {
        if (!g_popup_mgr_method)
            g_popup_mgr_method = warp_find_method(klass, "get_Instance", 0);
        if (!g_popup_open_method)
            g_popup_open_method = warp_find_method(klass, "OpenGlobalPopup", 2);
    }
    if (g_hdr)
        g_hdr->popup_ok = (g_popup_mgr_method && g_popup_open_method) ? 1 : 0;
}

/* 必须在游戏主线程调用（弹窗要 new 游戏对象） */
int warp_show_popup(const char *utf8)
{
    void *mgr = NULL;
    void *exc = NULL;
    void *text;
    void *params[2];

    if (!utf8 || !utf8[0]) {
        warp_log("popup: empty text", 0);
        return 0;
    }
    if (!g_ic.runtime_invoke || !g_ic.string_new) {
        warp_log("popup: il2cpp api missing", 0);
        return 0;
    }
    if (!g_popup_mgr_method || !g_popup_open_method) {
        warp_log("popup: methods missing", 0);
        return 0;
    }

    if (!g_popup_mgr_cached) {
        mgr = g_ic.runtime_invoke(g_popup_mgr_method, NULL, NULL, &exc);
        if (!mgr) {
            warp_log("popup: manager null", exc ? 1 : 0);
            return 0;
        }
        g_popup_mgr_cached = mgr;
    }
    mgr = g_popup_mgr_cached;

    text = g_ic.string_new(utf8);
    if (!text) {
        warp_log("popup: string_new failed", 0);
        return 0;
    }

    params[0] = text;
    params[1] = NULL;                 /* DelegateEvent 留空 */
    exc = NULL;
    g_ic.runtime_invoke(g_popup_open_method, mgr, params, &exc);
    if (exc) {
        warp_log("popup: invoke threw", 0);
        return 0;
    }
    warp_log("popup: ok", 0);
    return 1;
}

/* ------------------------------------------------------------------ */
/* 结束进程（独立线程，不占主线程）                                    */
/* ------------------------------------------------------------------ */

DWORD WINAPI warp_kill_thread(LPVOID param)
{
    DWORD delay = (DWORD)(ULONG_PTR)param;
    if (delay)
        Sleep(delay);
    warp_log("kill process", (int)delay);
    TerminateProcess(GetCurrentProcess(), 0);
    return 0;
}

