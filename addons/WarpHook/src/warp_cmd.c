/* warp_cmd.c —— 命令泵：py 主动下发的命令在主线程执行
 *
 * 由 warp_host.c 拆分而来（原第 941-1127 行）。
 * P6 起命令槽不再只有弹窗/杀进程：还有对象构造（MAKE/STR）、方法调用（CALL）
 * 和槽释放（RELEASE）。构造出来的对象挂 il2cpp 强句柄防 GC 收走，写进对象槽；
 * 等下一次同槽写入或 py 主动 release 时解掉。句柄表在 DLL 静态内存
 * （g_gc_handles），不进共享内存 —— 对象槽本身只有指针，Python 不需要看到句柄。
 */
#include "warp_internal.h"

/* ------------------------------------------------------------------ */
/* 命令泵                                                              */
/*                                                                     */
/* py 侧 `host.popup("...")` 只是往命令槽里写一句话并递增序号；真正     */
/* 弹窗发生在游戏主线程（FixedUpdate / 任意钩子命中）里。这样调用方    */
/* 像写普通代码一样一行搞定，又不用担心理线程碰 Unity UI。              */
/* ------------------------------------------------------------------ */

/* 每个对象槽至多一个强句柄，0 = 这槽上的对象没挂句柄（cache 钩子落的裸指针）。 */
unsigned int g_gc_handles[WARP_OBJECT_COUNT];

/* 往对象槽落一个指针。所有写入都走这里：写之前先把旧句柄解掉，同一槽被
 * 反复 make 时前面的对象能正常被 GC 回收，不会攒一桌面没用的强引用。 */
void warp_slot_put(int slot, void *obj, int with_handle)
{
    void **objs;

    if (slot < 0 || slot >= WARP_OBJECT_COUNT)
        return;
    objs = warp_objects();
    if (!objs)
        return;
    if (g_gc_handles[slot] && g_ic.gchandle_free) {
        g_ic.gchandle_free(g_gc_handles[slot]);
        g_gc_handles[slot] = 0;
    }
    objs[slot] = obj;
    if (with_handle && obj && g_ic.gchandle_new)
        g_gc_handles[slot] = g_ic.gchandle_new(obj, 1);
}

void *warp_slot_get(int slot)
{
    void **objs;

    if (slot < 0 || slot >= WARP_OBJECT_COUNT)
        return NULL;
    objs = warp_objects();
    return objs ? objs[slot] : NULL;
}

/* ------------------------------------------------------------------ */
/* 对象构造与方法调用（P6）                                             */
/*                                                                     */
/* 参数值从 vars[0..5] 来（打包字里带 argc），每个参数的类型记在         */
/* cmd_text 的 "#..." 后缀里：i=int32、f=float、p=引用（vars 值就是      */
/* 指针）。runtime_invoke 的 params 要「指向参数值的指针」，所以这里     */
/* 按类型把 vars 搬进本地缓冲再取址 —— 引用类型搬的是指针本身。          */
/* 返回值：box 值（int/float）在 +0x10 解包写 vars[6]；引用返回落        */
/* vars[7] 指定的槽并挂句柄。                                           */
/* ------------------------------------------------------------------ */

/* 解析 "#iifp" 后缀。没有后缀时全按 int 处理（构造大多没有参数，这里
 * 宽松点省得 py 忘写后缀就炸）。 */
static void warp_cmd_argkinds(const char *text, char *kinds, int max)
{
    const char *hash = strchr(text, '#');
    int i = 0;

    if (hash) {
        for (hash++; *hash && i < max; hash++) {
            if (*hash == WARP_CMD_ARG_I || *hash == WARP_CMD_ARG_F ||
                *hash == WARP_CMD_ARG_P)
                kinds[i++] = *hash;
        }
    }
    for (; i < max; i++)
        kinds[i] = WARP_CMD_ARG_I;
}

/* 从 cmd_text 头部截出一段名字（到 '#'、'\0' 或 max 为止）。 */
static void warp_cmd_name_until(const char *text, char *out, size_t max)
{
    const char *end = text;
    size_t n;

    while (*end && *end != '#' && *end != ':' && (size_t)(end - text) < max - 1)
        end++;
    n = (size_t)(end - text);
    memcpy(out, text, n);
    out[n] = '\0';
}

static int warp_cmd_build_params(int argc, const char *kinds,
                                 void *params[], int *ival, float *fval,
                                 void **pval)
{
    int i;

    if (argc > 6)
        return WARP_CMD_RES_BAD_ARGC;
    for (i = 0; i < argc; i++) {
        int v = g_hdr->vars[i];
        switch (kinds[i]) {
        case WARP_CMD_ARG_F:
            ival[i] = v;                    /* vars 里存的就是 float 的位模式 */
            memcpy(&fval[i], &ival[i], 4);
            params[i] = &fval[i];
            break;
        case WARP_CMD_ARG_P:
            pval[i] = (void *)(intptr_t)v;
            params[i] = &pval[i];
            break;
        default:
            ival[i] = v;
            params[i] = &ival[i];
            break;
        }
    }
    return 0;
}

int warp_cmd_make(int argc, int slot, const char *argkinds_text)
{
    char kinds[8];
    void *params[6] = {0};      /* 零初始化：桩/游调试环境可以安全扫整个数组 */
    int ival[6];
    float fval[6];
    void *pval[6];
    void *klass;
    void *obj = NULL;
    int rc;

    if (slot < 0 || slot >= WARP_OBJECT_COUNT)
        return WARP_CMD_RES_BAD_SLOT;
    {
        char name[64];
        warp_cmd_name_until(g_hdr->cmd_text, name, sizeof(name));
        klass = warp_find_class(g_domain, name);
    }
    if (!klass)
        return WARP_CMD_RES_NO_CLASS;
    obj = g_ic.object_new(klass);       /* object_new 只分配不调构造 */
    if (!obj)
        return WARP_CMD_RES_FAIL;
    if (argc > 0) {
        void *ctor = warp_find_method(klass, ".ctor", argc);
        void *exc = NULL;

        if (!ctor) {
            return WARP_CMD_RES_NO_METHOD;
        }
        warp_cmd_argkinds(argkinds_text, kinds, 6);
        rc = warp_cmd_build_params(argc, kinds, params, ival, fval, pval);
        if (rc)
            return rc;
        g_ic.runtime_invoke(ctor, obj, params, &exc);
        if (exc)
            return WARP_CMD_RES_EXCEPTION;
    }
    warp_slot_put(slot, obj, 1);
    return WARP_CMD_RES_OK;
}

int warp_cmd_call(int argc, int slot, int retkind, int out_slot, const char *argkinds_text)
{
    char kinds[8];
    void *params[6] = {0};
    int ival[6];
    float fval[6];
    void *pval[6];
    char name[64];
    char mname[48];
    const char *sep;
    void *klass;
    void *method;
    void *target = NULL;
    void *ret;
    void *exc = NULL;
    int rc;

    if (out_slot >= WARP_OBJECT_COUNT)
        return WARP_CMD_RES_BAD_SLOT;
    /* 槽号打包成一个字节，-1 落进来是 0xFF —— 约定 0xFF = 静态调用。 */
    if (slot >= WARP_OBJECT_COUNT) {
        if (slot != 0xFF)
            return WARP_CMD_RES_BAD_SLOT;
        slot = -1;
    }
    /* cmd_text = "Ns.Klass::Method#kind..."；类名必有，this 可选（slot<0 = 静态调用）。 */
    sep = strstr(g_hdr->cmd_text, "::");
    if (!sep)
        return WARP_CMD_RES_NO_METHOD;
    warp_cmd_name_until(g_hdr->cmd_text, name, sizeof(name));
    warp_cmd_name_until(sep + 2, mname, sizeof(mname));
    klass = warp_find_class(g_domain, name);
    if (!klass)
        return WARP_CMD_RES_NO_CLASS;
    method = warp_find_method(klass, mname, argc);
    if (!method)
        return WARP_CMD_RES_NO_METHOD;
    if (slot >= 0) {
        target = warp_slot_get(slot);
        if (!target)
            return WARP_CMD_RES_FAIL;      /* 槽是空的，对象可能已被释放 */
    }
    warp_cmd_argkinds(sep, kinds, 6);
    rc = warp_cmd_build_params(argc, kinds, params, ival, fval, pval);
    if (rc)
        return rc;
    ret = g_ic.runtime_invoke(method, target, params, &exc);
    if (exc)
        return WARP_CMD_RES_EXCEPTION;
    if (retkind == WARP_CMD_RET_INT32 || retkind == WARP_CMD_RET_FLOAT) {
        /* box 出来的值类型对象，真值在 +0x10（对象头 8B + klass 8B）。 */
        if (ret) {
            int bits = *(const int *)((const char *)ret + 0x10);
            g_hdr->vars[6] = bits;
        } else {
            g_hdr->vars[6] = 0;
        }
    } else if (retkind == WARP_CMD_RET_REF) {
        if (out_slot < 0)
            return WARP_CMD_RES_BAD_SLOT;
        /* 返回的引用挂强句柄，py 用完 release —— 不挂的话下次 GC 一到就没了。 */
        warp_slot_put(out_slot, ret, 1);
    }
    return WARP_CMD_RES_OK;
}

int warp_cmd_str(int slot)
{
    void *str;

    if (slot < 0 || slot >= WARP_OBJECT_COUNT)
        return WARP_CMD_RES_BAD_SLOT;
    str = g_ic.string_new(g_hdr->cmd_text);
    if (!str)
        return WARP_CMD_RES_FAIL;
    warp_slot_put(slot, str, 1);
    return WARP_CMD_RES_OK;
}

int warp_cmd_release(int slot)
{
    if (slot < 0 || slot >= WARP_OBJECT_COUNT)
        return WARP_CMD_RES_BAD_SLOT;
    warp_slot_put(slot, NULL, 0);
    return WARP_CMD_RES_OK;
}

int warp_kill_game(void)
{
    HANDLE proc = GetCurrentProcess();
    TerminateProcess(proc, 0);
    return 0;
}

void   *g_pump_target = NULL;
void   *g_pump_original = NULL;
int     g_pump_installed = 0;

/* 装完那一刻的钩子表指纹。控制线程拿它和当前映射里的表比对，变了就重装 ——
   插件在游戏运行中改钩子表（切插件、改设置）不该逼着用户重开游戏。 */
unsigned int g_hook_sig = 0;

unsigned int warp_hook_signature(void)
{
    unsigned int hash = 2166136261u;   /* FNV-1a 32 */
    int i;

    for (i = 0; i < WARP_MAX_HOOKS; i++) {
        const WARP_HOOK *h = &g_warp_hooks[i];
        const unsigned char *p;
        int k;

        for (p = (const unsigned char *)h->klass, k = 0; k < WARP_KLASS_LEN && *p; k++, p++)
            hash = (hash ^ *p) * 16777619u;
        hash = (hash ^ (unsigned char)'|') * 16777619u;
        for (p = (const unsigned char *)h->method, k = 0; k < WARP_METHOD_LEN && *p; k++, p++)
            hash = (hash ^ *p) * 16777619u;
        hash = (hash ^ (unsigned char)'|') * 16777619u;
        hash = (hash ^ (unsigned int)(h->argc & 0xff)) * 16777619u;
        hash = (hash ^ (unsigned int)(h->actions & 0xff)) * 16777619u;
        hash = (hash ^ (unsigned int)(h->flags & 0xff)) * 16777619u;
    }
    return hash;
}

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

    switch (WARP_CMD_CODE(type)) {
    case WARP_CMD_POPUP:
        rc = warp_show_popup(g_hdr->cmd_text) ? 0 : 1;
        if (rc == 0 && g_hdr)
            g_hdr->fired++;
        break;
    case WARP_CMD_KILL:
        rc = warp_kill_game();
        break;
    case WARP_CMD_MAKE:
        rc = warp_cmd_make(WARP_CMD_ARGC(type), WARP_CMD_SLOT(type), g_hdr->cmd_text);
        if (rc == 0 && g_hdr)
            g_hdr->fired++;
        break;
    case WARP_CMD_CALL:
        rc = warp_cmd_call(WARP_CMD_ARGC(type), WARP_CMD_SLOT(type),
                           WARP_CMD_RETKIND(type), (int)g_hdr->vars[7],
                           g_hdr->cmd_text);
        if (rc == 0 && g_hdr)
            g_hdr->fired++;
        break;
    case WARP_CMD_STR:
        rc = warp_cmd_str(WARP_CMD_SLOT(type));
        if (rc == 0 && g_hdr)
            g_hdr->fired++;
        break;
    case WARP_CMD_RELEASE:
        rc = warp_cmd_release(WARP_CMD_SLOT(type));
        break;
    default:
        rc = WARP_CMD_RES_UNKNOWN;      /* 未知命令 */
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
    g_hook_sig = warp_hook_signature();
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
    /* 归零，否则控制线程会一直以为「已经装好了」而不去重装新表 */
    g_installed = 0;
    if (g_hdr) {
        g_hdr->hook_installed = 0;
        g_hdr->hooked = 0;
    }
}

