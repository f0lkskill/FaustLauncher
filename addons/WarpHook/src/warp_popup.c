/* warp_popup.c —— 原版弹窗 + 结束进程
 *
 * 由 warp_host.c 拆分而来（原第 551-638 行）。
 */
#include <string.h>

#include "warp_internal.h"

/* ------------------------------------------------------------------ */
/* 原版弹窗                                                            */
/* ------------------------------------------------------------------ */

/* 弹窗相关的托管对象必须自己留根。
 *
 * ``il2cpp_string_new`` 造出来的字符串、``get_Instance`` 取回来的单例，在 C 侧
 * 都只是裸指针；Boehm GC 只扫托管栈和静态区，看不到这两个指针，于是随时可能
 * 把对象收走。收走之后 ``OpenGlobalPopup`` 拿到的是一个空壳，界面上就出现
 * 「弹窗框出来了，正文一个字都没有」—— 概率取决于 GC 什么时候跑，所以表现为
 * 偶发。这里给它们挂强句柄；句柄只申请不释放（环形覆盖最近的若干个），因为
 * ``gchandle_free`` 一旦撞上 GC 移动对象的窗口就会 AV（见 warp_cmd.c 的注释，
 * 为这个崩过好几次进程）。一次弹窗泄漏一个句柄，量级完全可以接受。 */
#define WARP_POPUP_KEEP 32
static uintptr_t g_popup_keep[WARP_POPUP_KEEP];
static int g_popup_keep_at;

static void warp_keep_object(void *obj)
{
    uintptr_t handle;

    if (!obj || !g_ic.gchandle_new)
        return;
    handle = g_ic.gchandle_new(obj, 1);
    if (!handle)
        return;
    g_popup_keep[g_popup_keep_at++ % WARP_POPUP_KEEP] = handle;
}

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
        warp_keep_object(mgr);
    }
    mgr = g_popup_mgr_cached;

    text = g_ic.string_new(utf8);
    if (!text) {
        warp_log("popup: string_new failed", 0);
        return 0;
    }
    warp_keep_object(text);

    params[0] = text;
    params[1] = NULL;                 /* DelegateEvent 留空 */
    exc = NULL;
    g_ic.runtime_invoke(g_popup_open_method, mgr, params, &exc);
    if (exc) {
        warp_log("popup: invoke threw", 0);
        return 0;
    }
    warp_log("popup: ok text len", (int)strlen(utf8));
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

