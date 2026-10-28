/* warp_cmd.c —— 命令泵：py 主动下发的命令在主线程执行
 *
 * 由 warp_host.c 拆分而来（原第 941-1127 行）。
 */
#include "warp_internal.h"

/* ------------------------------------------------------------------ */
/* 命令泵                                                              */
/*                                                                     */
/* py 侧 `host.popup("...")` 只是往命令槽里写一句话并递增序号；真正     */
/* 弹窗发生在游戏主线程（FixedUpdate / 任意钩子命中）里。这样调用方    */
/* 像写普通代码一样一行搞定，又不用担心理线程碰 Unity UI。              */
/* ------------------------------------------------------------------ */


int warp_kill_game(void)
{
    HANDLE proc = GetCurrentProcess();
    TerminateProcess(proc, 0);
    return 0;
}

void   *g_pump_target = NULL;
void   *g_pump_original = NULL;
int     g_pump_installed = 0;

/* 宿主自己补的那条「泵点」：没有用户钩子的时候也能每帧跑一次命令泵。 */
void __stdcall hk_warp_pump(void *self)
{
    typedef void (__stdcall *warp_fixedupdate_fn)(void *);
    if (g_pump_original)
        ((warp_fixedupdate_fn)g_pump_original)(self);
    warp_pump_commands();
}

void warp_pump_commands(void)
{
    int seq;
    int type;
    int rc = 0;

    if (!g_hdr)
        return;

    seq = g_hdr->cmd_seq;
    if (seq == g_hdr->cmd_ack)
        return;

    type = g_hdr->cmd_type;
    /* 先记账再执行：弹窗里可能重入（弹窗自己又触发钩子），不能重复执行。 */
    g_hdr->cmd_ack = seq;

    switch (type) {
    case WARP_CMD_POPUP:
        rc = warp_show_popup(g_hdr->cmd_text) ? 0 : 1;
        if (rc == 0 && g_hdr)
            g_hdr->fired++;
        break;
    case WARP_CMD_KILL:
        rc = warp_kill_game();
        break;
    default:
        rc = 2;                 /* 未知命令 */
        break;
    }

    if (g_hdr)
        g_hdr->cmd_result = rc;
}

int warp_install_hooks(void)
{
    void *domain;
    int i;
    int installed = 0;
    int total = 0;
    BOOL mh_ready = FALSE;

    domain = g_ic.domain_get();
    if (!domain)
        return 0;

    warp_resolve_popup(domain);
    warp_status(WARP_ST_HOOKING, WARP_ERR_OK);

    for (i = 0; i < WARP_MAX_HOOKS; i++) {
        WARP_HOOK *h = &g_warp_hooks[i];
        void *klass;
        void *method;
        void *target;
        void *thunk;

        if (!h->klass[0] || !h->method[0])
            continue;
        total++;
        if (g_slots[i].installed) {
            installed++;
            continue;
        }

        klass = warp_find_class(domain, h->klass);
        if (!klass) {
            warp_log("hook: class not found", i);
            continue;
        }
        method = warp_find_method(klass, h->method, h->argc);
        if (!method) {
            warp_log("hook: method not found", i);
            continue;
        }
        target = warp_method_pointer(method);
        if (!target) {
            warp_log("hook: null method pointer", i);
            continue;
        }
        thunk = warp_pick_thunk(i, h->argc);
        if (!thunk) {
            warp_log("hook: unsupported argc", h->argc);
            continue;
        }

        if (!mh_ready) {
            if (MH_Initialize() != MH_OK) {
                warp_status(WARP_ST_ERROR, WARP_ERR_MH_INIT);
                warp_log("MH_Initialize failed", 0);
                return installed;
            }
            mh_ready = TRUE;
        }

        g_slots[i].argc = h->argc;
        if (MH_CreateHook(target, thunk, &g_slots[i].original) != MH_OK) {
            warp_log("hook: create failed", i);
            continue;
        }
        if (MH_EnableHook(target) != MH_OK) {
            warp_log("hook: enable failed", i);
            continue;
        }
        g_slots[i].target = target;
        g_slots[i].installed = TRUE;
        installed++;
        warp_log("hook installed", i);
    }

    /* 用户没钩 FixedUpdate 的话，宿主自己补一条：命令泵需要一个每帧都会
       跑到的主线程入口，否则 py 主动调用 popup 要等到下次抽卡才生效。 */
    if (mh_ready && !g_pump_installed) {
        void *gklass = warp_find_class(domain, "GlobalGameManager");
        void *gmethod = gklass ? warp_find_method(gklass, "FixedUpdate", 0) : NULL;
        void *gtarget = gmethod ? warp_method_pointer(gmethod) : NULL;
        if (gtarget && MH_CreateHook(gtarget, hk_warp_pump, &g_pump_original) == MH_OK) {
            if (MH_EnableHook(gtarget) == MH_OK) {
                g_pump_target = gtarget;
                g_pump_installed = 1;
                warp_log("pump hook installed", 0);
            }
        }
    }

    g_installed = installed;
    if (g_hdr) {
        g_hdr->hook_total = total;
        g_hdr->hook_installed = installed;
        g_hdr->hooked = installed > 0 ? 1 : 0;
    }

    if (installed > 0) {
        warp_status(WARP_ST_HOOKED, WARP_ERR_OK);
    } else if (total > 0) {
        warp_status(WARP_ST_ERROR, WARP_ERR_NO_TARGET);
    }
    return installed;
}

void warp_uninstall(void)
{
    int i;
    for (i = 0; i < WARP_MAX_HOOKS; i++) {
        if (!g_slots[i].installed)
            continue;
        MH_DisableHook(g_slots[i].target);
        MH_RemoveHook(g_slots[i].target);
        g_slots[i].installed = FALSE;
    }
    if (g_pump_installed) {
        MH_DisableHook(g_pump_target);
        MH_RemoveHook(g_pump_target);
        g_pump_installed = 0;
    }
    MH_Uninitialize();
}

