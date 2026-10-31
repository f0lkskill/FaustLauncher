/* warp_cmd.c —— 命令泵：py 主动下发的命令在主线程执行
 *
 * 由 warp_host.c 拆分而来（原第 941-1127 行）。
 * P6 起命令槽不再只有弹窗/杀进程：还有对象构造（MAKE/STR）、方法调用（CALL）
 * 和槽释放（RELEASE）。构造出来的对象挂 il2cpp 强句柄防 GC 收走，写进对象槽；
 * 等下一次同槽写入或 py 主动 release 时解掉。句柄表在 DLL 静态内存
 * （g_gc_handles），不进共享内存 —— 对象槽本身只有指针，Python 不需要看到句柄。
 */
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <setjmp.h>

#include "warp_internal.h"

/* ------------------------------------------------------------------ */
/* 命令泵                                                              */
/*                                                                     */
/* py 侧 `host.popup("...")` 只是往命令槽里写一句话并递增序号；真正     */
/* 弹窗发生在游戏主线程（FixedUpdate / 任意钩子命中）里。这样调用方    */
/* 像写普通代码一样一行搞定，又不用担心理线程碰 Unity UI。              */
/* ------------------------------------------------------------------ */

/* ------------------------------------------------------------------ */
/* invoke 保护                                                         */
/*                                                                     */
/* 调用方传错参数、或时机不对（比如不在战斗里调战斗音频接口），il2cpp   */
/* 或者它内部的 native 代码会直接访问违例，把整个游戏带走。这里用一个   */
/* VEH 只接管「我们正在 invoke」这个窗口里的异常，把它变成一次失败的    */
/* 返回值。                                                            */
/*                                                                     */
/* longjmp 会跳过 il2cpp 的栈展开，异常之后它自己的中间状态可能不干净， */
/* 所以异常路径只做「退出去」：命令返回失败、钩子里当没读到。正常路径   */
/* 完全不受影响（VEH 只在异常时才会被调用）。                          */
/* ------------------------------------------------------------------ */

static jmp_buf s_invoke_jmp;
static volatile LONG s_invoke_depth;
static volatile DWORD s_invoke_tid; /* 谁在 invoke —— VEH 必须认线程 */
static PVOID s_invoke_veh;

static LONG CALLBACK warp_invoke_veh(EXCEPTION_POINTERS *ep)
{
    (void)ep;
    if (s_invoke_depth <= 0)
        return EXCEPTION_CONTINUE_SEARCH;
    /* 只拦我们自己那次 invoke 所在的线程。别的线程这时候炸，跟我们无关， */
    /* 拿它的栈去 longjmp 到 s_invoke_jmp 会把两层栈都弄坏。 */
    if (GetCurrentThreadId() != s_invoke_tid)
        return EXCEPTION_CONTINUE_SEARCH;
    s_invoke_depth = 0;
    longjmp(s_invoke_jmp, 1);
}

void *warp_safe_invoke(void *method, void *target, void **params, void **exc)
{
    void *ret = NULL;

    if (!method || !g_ic.runtime_invoke) {
        if (exc)
            *exc = NULL;
        return NULL;
    }
    if (0) {
        /* 0.9.14：VEH + longjmp 这条路废弃了。真机上它「接住」第一击之后，
         * 游戏还能再活一分多钟，然后崩在完全无关的地方（Player.log 栈上
         * 一个 warp_host 帧都没有）—— 因为 longjmp 跳过了 il2cpp 的托管栈
         * 展开，运行时状态是脏的。托管异常本来就由 &exc 正常返回，不需要
         * 我们插手；原生 AV 拦下来也救不回来，只会把状态弄得更烂。
         * 真正的护栏改在 Python 侧：Host.call 只认白名单里的方法。 */
        if (!s_invoke_veh)
            s_invoke_veh = AddVectoredExceptionHandler(1, warp_invoke_veh);
    }
    if (exc)
        *exc = NULL;
    if (1) {
        s_invoke_tid = GetCurrentThreadId();
        s_invoke_depth++;
        ret = g_ic.runtime_invoke(method, target, params, exc);
        s_invoke_depth--;
        s_invoke_tid = 0;
    } else {
        /* 跳回来了：调用炸了。给上层一个非 NULL 的 exc，按「抛异常」处理。 */
        s_invoke_depth = 0;
        s_invoke_tid = 0;
        ret = NULL;
        if (exc)
            *exc = (void *)(ULONG_PTR)1;
    }
    return ret;
}

/* v10.2: GC 句柄表 —— 必须 pointer-sized。0.9.14 以前它是 unsigned int[32]，
 * 而 Unity 6（Boehm 64 位）的 il2cpp_gchandle_new 返回 64 位句柄：存进 32 位
 * 槽位被截断，之后 gchandle_free(截断值) 直接 AV —— 这才是 0.9.15 拆句柄时
 * 误判的「句柄不可信」的真因。拆句柄后换来新雷：make_str 造的字符串裸指针
 * 躺在共享内存里，GC 扫描范围不含 MAP，下一次 GC 就把字符串回收，随后的
 * call 拿到悬空指针崩在游戏内部（0.9.18 / 0.9.19 / 0.9.21 三次
 * IsLoadedBank 崩溃同根）。所以句柄回归，并且用完整 64 位。 */
static uintptr_t g_gc_handles[WARP_OBJECT_COUNT];

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
    if (g_gc_handles[slot]) {
        if (g_ic.gchandle_free)
            g_ic.gchandle_free(g_gc_handles[slot]);
        g_gc_handles[slot] = 0;
    }
    objs[slot] = obj;
    if (with_handle && obj && g_ic.gchandle_new)
        g_gc_handles[slot] = g_ic.gchandle_new(obj, 0);
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
                *hash == WARP_CMD_ARG_P || *hash == WARP_CMD_ARG_M)
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

/* ---- 按参数类型选重载（v10） -------------------------------------
 * 老路子 warp_find_method 只按「名字 + 参数个数」找，碰到
 * IsLoadedBank(AssetReference) / IsLoadedBank(string) 这种同参数个数的
 * 重载会挑错，把字符串当对象指针传进去 —— 崩在游戏内部（0.9.16 实测）。
 * 这里照旧插件 BattleBGMExtend 的 method() 做法，把每个参数的类型名也
 * 一起比一遍。类型串写在 cmd_text 的 '|' 之后，逗号分隔：
 *   S=System.String  B=System.Boolean  I=System.Int32  F=System.Single
 *   L=System.Int64   D=System.Double   V=System.Void
 *   O 或 ?=不校验（任意类型）
 * 末尾带 '&' 表示 byref（例如 EventInstance&），比对时按 byref 处理。
 */
static void warp_cmd_sig(const char *text, char *sig, size_t max)
{
    const char *bar;
    size_t n;

    sig[0] = '\0';
    if (!text || max < 2)
        return;
    bar = strchr(text, '|');
    if (!bar)
        return;
    bar++;
    n = strlen(bar);
    if (n >= max)
        n = max - 1;
    memcpy(sig, bar, n);
    sig[n] = '\0';
}

static const char *warp_type_full(char abbr)
{
    switch (abbr) {
    case 'S': return "System.String";
    case 'B': return "System.Boolean";
    case 'I': return "System.Int32";
    case 'F': return "System.Single";
    case 'L': return "System.Int64";
    case 'D': return "System.Double";
    case 'V': return "System.Void";
    default:  return NULL;
    }
}

/* 比对第 index 个参数；want 可以是单字符缩写，也可以是全名。 */
static int warp_param_matches(const void *method, int index, const char *want)
{
    const void *type;
    char *actual;
    char buf[96];
    size_t n;
    int ok;

    if (!g_ic.method_get_param || !g_ic.type_get_name)
        return 0;
    n = strlen(want);
    while (n && (want[n - 1] == '&' || want[n - 1] == ' '))
        n--;
    if (n == 0)
        return 0;
    if (n == 1 && (want[0] == 'O' || want[0] == '?'))
        return 1;                       /* 通配，不校验 */
    if (n == 1) {
        const char *full = warp_type_full(want[0]);

        if (!full)
            return 0;
        n = strlen(full);
        if (n >= sizeof(buf))
            return 0;
        memcpy(buf, full, n + 1);
    } else {
        if (n >= sizeof(buf))
            n = sizeof(buf) - 1;
        memcpy(buf, want, n);
        buf[n] = '\0';
    }
    type = g_ic.method_get_param(method, (unsigned int)index);
    if (!type)
        return 0;
    actual = g_ic.type_get_name(type);
    if (!actual)
        return 0;
    ok = (strcmp(actual, buf) == 0);
    if (!ok) {
        /* 有的版本把 byref 写成 "Type&"，也认 */
        size_t alen = strlen(actual);
        size_t blen = strlen(buf);

        if (alen == blen + 1 && actual[alen - 1] == '&' &&
            strncmp(actual, buf, blen) == 0)
            ok = 1;
    }
    if (g_ic.free_mem)
        g_ic.free_mem(actual);
    return ok;
}

static int warp_sig_match(const void *method, int argc, const char *sig)
{
    const char *p = sig;
    int i;

    for (i = 0; i < argc; i++) {
        const char *comma = strchr(p, ',');
        size_t n = comma ? (size_t)(comma - p) : strlen(p);
        char want[96];

        if (n >= sizeof(want))
            n = sizeof(want) - 1;
        memcpy(want, p, n);
        want[n] = '\0';
        if (!warp_param_matches(method, i, want))
            return 0;
        if (!comma)
            return (i == argc - 1);
        p = comma + 1;
    }
    return 1;
}

static void *warp_find_method_typed(void *klass, const char *name, int argc,
                                    const char *sig)
{
    void *iter = NULL;
    const void *m;

    if (!g_ic.class_get_methods || !g_ic.method_get_name ||
        !g_ic.method_get_param_count)
        return NULL;
    while ((m = g_ic.class_get_methods(klass, &iter)) != NULL) {
        if (strcmp(g_ic.method_get_name(m), name) != 0)
            continue;
        if ((int)g_ic.method_get_param_count(m) != argc)
            continue;
        if (warp_sig_match(m, argc, sig))
            return (void *)m;
    }
    return NULL;
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
            /* v10.1：vars 只有 32 位，塞 64 位指针必被截断（游戏拿到野指针直接 AV）。
             * 现在约定 vars 里放的是「对象槽号」，指针在宿主侧查表取。 */
            if (v < 0 || v >= WARP_OBJECT_COUNT)
                return WARP_CMD_RES_BAD_ARGC;
            pval[i] = warp_objects()[v];
            params[i] = &pval[i];
            break;
        case WARP_CMD_ARG_M:
            /* out 参数：v 是 MAP 内缓冲的块内偏移，直接把那块地址给 il2cpp。
             * 游戏往这里写值类型（如 FMOD EventInstance），Python 侧读同一块。 */
            if (v < 0 || v >= WARP_CMD_BUF_COUNT * WARP_CMD_BUF_SIZE)
                return WARP_CMD_RES_BAD_ARGC;
            params[i] = (char *)g_hdr + WARP_CMD_BUF_OFFSET + v;
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

/* ------------------------------------------------------------------ */
/* methodPointer 直调（v0.9.24）                                        */
/*                                                                     */
/* runtime_invoke 在本机就是有毒：六次崩溃的 AV 全部落在 invoke 路径，  */
/* 连最简单的静态 getter 都炸（v0.9.23 真机验证，worker 舱接住后确认）。*/
/* 旧插件 BattleBGMExtend 稳跑多年靠的从来不是 runtime_invoke —— 它取   */
/* MethodInfo 第一个字段（methodPointer），VirtualQuery 验证指针落在    */
/* GameAssembly 里之后直接按 C 调用约定调。这里照搬：                   */
/*   实例方法  ret f(this, args..., const MethodInfo*)                  */
/*   静态方法  ret f(args..., const MethodInfo*)                        */
/*   引用返回  隐藏 sret 首参（Win x64：大于 8 字节的返回走 rcx）        */
/* bool/int 返回在 rax 低 32 位（il2cpp 代码生成对 bool 做 movzx，高位  */
/* 干净）；float 返回在 xmm0。参数只收 64 位通用寄存器可容的形状         */
/* （指针/整型）—— 浮点参数、更多参数以后按需再加。                     */
/* ------------------------------------------------------------------ */

/* methodPointer 必须落在 GameAssembly 的可执行页里才敢调。 */
static int warp_direct_fp_ok(const void *fp)
{
    MEMORY_BASIC_INFORMATION mb;
    HMODULE ga;

    if (!fp || !VirtualQuery(fp, &mb, sizeof(mb)))
        return 0;
    ga = GetModuleHandleW(L"GameAssembly.dll");
    if (!ga || mb.AllocationBase != (void *)ga)
        return 0;
    return (mb.Protect & (PAGE_EXECUTE | PAGE_EXECUTE_READ |
                          PAGE_EXECUTE_READWRITE |
                          PAGE_EXECUTE_WRITECOPY)) != 0;
}

#define WDC_VA_0
#define WDC_VA_1 void *,
#define WDC_VA_2 void *, void *,
#define WDC_VA_3 void *, void *, void *,
#define WDC_VA_4 void *, void *, void *, void *,
#define WDC_VA_5 void *, void *, void *, void *, void *,

#define WDC_AI_0
#define WDC_AI_1 a[0],
#define WDC_AI_2 a[0], a[1],
#define WDC_AI_3 a[0], a[1], a[2],
#define WDC_AI_4 a[0], a[1], a[2], a[3],
#define WDC_AI_5 a[0], a[1], a[2], a[3], a[4],

#define WDC_INVOKE(N) do { \
    if (retkind == WARP_CMD_RET_REF) { \
        void *sret = NULL; \
        if (target) \
            ((void (*)(void *, WDC_VA_##N void *, void *))fp)(&sret, target, WDC_AI_##N mi); \
        else \
            ((void (*)(WDC_VA_##N void *, void *))fp)(&sret, WDC_AI_##N mi); \
        *out_ref = sret; \
    } else if (retkind == WARP_CMD_RET_FLOAT) { \
        if (target) \
            *out_flt = ((float (*)(void *, WDC_VA_##N void *))fp)(target, WDC_AI_##N mi); \
        else \
            *out_flt = ((float (*)(WDC_VA_##N void *))fp)(WDC_AI_##N mi); \
    } else { \
        if (target) \
            *out_int = (long long)(uintptr_t)((void *(*)(void *, WDC_VA_##N void *))fp)(target, WDC_AI_##N mi); \
        else \
            *out_int = (long long)(uintptr_t)((void *(*)(WDC_VA_##N void *))fp)(WDC_AI_##N mi); \
    } } while (0)

/* 返回 0 成功（值经 out_int/out_flt/out_ref 带出）；负数 = 没进调用就失败。 */
static int warp_direct_call(void *method, void *target, void **params, int argc,
                            int retkind, long long *out_int, float *out_flt,
                            void **out_ref)
{
    void *a[5] = {0};
    void *fp;
    void *mi = method;
    int i;

    if (!method)
        return -1;
    memcpy(&fp, method, sizeof(fp));    /* MethodInfo 首字段 = methodPointer */
    if (!warp_direct_fp_ok(fp))
        return -2;
    if (argc < 0 || argc > 5)
        return -3;
    for (i = 0; i < argc; i++)
        a[i] = params[i] ? *(void **)params[i] : NULL;

    switch (argc) {
    case 0: WDC_INVOKE(0); break;
    case 1: WDC_INVOKE(1); break;
    case 2: WDC_INVOKE(2); break;
    case 3: WDC_INVOKE(3); break;
    case 4: WDC_INVOKE(4); break;
    default: WDC_INVOKE(5); break;
    }
    return 0;
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
    int rc;

    if (out_slot >= WARP_OBJECT_COUNT)
        return WARP_CMD_RES_BAD_SLOT;
    /* 槽号打包成一个字节，-1 落进来是 0xFF —— 约定 0xFF = 静态调用。 */
    if (slot >= WARP_OBJECT_COUNT) {
        if (slot != 0xFF)
            return WARP_CMD_RES_BAD_SLOT;
        slot = -1;
    }
    /* text = "Ns.Klass::Method#kind..."；类名必有，this 可选（slot<0 = 静态调用）。
     * v0.9.23 起文本由调用方传入（泵传 g_hdr->cmd_text，worker 传任务拷贝），
     * 函数本身不再读共享 MAP —— worker 执行期间 py 覆盖 cmd_text 也不会撕裂。 */
    if (!argkinds_text || !argkinds_text[0])
        return WARP_CMD_RES_NO_METHOD;
    sep = strstr(argkinds_text, "::");
    if (!sep)
        return WARP_CMD_RES_NO_METHOD;
    warp_cmd_name_until(argkinds_text, name, sizeof(name));
    warp_cmd_name_until(sep + 2, mname, sizeof(mname));
    klass = warp_find_class(g_domain, name);
    if (!klass)
        return WARP_CMD_RES_NO_CLASS;
    {
        char sig[WARP_CMD_SIG_MAX];

        warp_cmd_sig(sep, sig, sizeof(sig));
        if (sig[0])
            method = warp_find_method_typed(klass, mname, argc, sig);
        else
            method = warp_find_method(klass, mname, argc);
    }
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
    /* v0.9.24：runtime_invoke 在本机有毒（六次崩溃全在这条路径上），改走
     * 旧插件的 methodPointer 直调；方法查找、参数打包、签名匹配都不变。
     * worker 舱的 VEH 保护仍在 —— 万一游戏方法自己有毒，照样只记一次失败。 */
    {
        long long bits = 0;
        float xf = 0.0f;
        void *ref = NULL;

        rc = warp_direct_call(method, target, params, argc, retkind,
                              &bits, &xf, &ref);
        if (rc)
            return WARP_CMD_RES_FAIL;  /* -1 无方法 / -2 指针验证不过 / -3 参数超限 */
        if (retkind == WARP_CMD_RET_INT32)
            g_hdr->vars[6] = (int)(bits & 0xFFFFFFFFll);
        else if (retkind == WARP_CMD_RET_FLOAT) {
            memcpy(&g_hdr->vars[6], &xf, 4);   /* 位模式直通，py 侧按 float 解 */
        } else if (retkind == WARP_CMD_RET_REF) {
            if (out_slot < 0)
                return WARP_CMD_RES_BAD_SLOT;
            /* 返回的引用挂强句柄，py 用完 release —— 不挂的话下次 GC 一到就没了。 */
            warp_slot_put(out_slot, ref, 1);
        }
    }
    return WARP_CMD_RES_OK;
}

int warp_cmd_str(int slot, const char *text)
{
    void *str;

    if (slot < 0 || slot >= WARP_OBJECT_COUNT)
        return WARP_CMD_RES_BAD_SLOT;
    str = g_ic.string_new(text ? text : "");
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

/* v7 代读：Python 把一条读链写进 MAP 尾部的 cmd_read 段，这里在游戏主线程上
 * 按槽取对象、执行链，结果写 vars[6]（值）与 vars[7]（遍历链的活跃数）。
 *
 * 为什么要绕命令通道这么一圈：插件跑在启动器进程，游戏对象在另一个进程里，
 * 插件自己按地址读就是访问违规（0.9.8 之前 read_object 就是这么崩的）。
 * 只有这里的 warp_can_read 校验才有意义 —— 读到坏地址当"没读到"返回。 */
int warp_cmd_read(int slot)
{
    WARP_READ *r;
    void *self;
    int out[WARP_EVENT_SLOTS];
    int total = 0;
    int ok, i;

    if (slot < 0 || slot >= WARP_OBJECT_COUNT)
        return WARP_CMD_RES_BAD_SLOT;
    if (!g_hdr)
        return WARP_CMD_RES_FAIL;

    self = warp_slot_get(slot);
    if (!self)
        return WARP_CMD_RES_FAIL;   /* 槽是空的：钩子还没命中过，或对象已被释放 */

    r = (WARP_READ *)(void *)((char *)g_hdr + WARP_CMD_READ_OFFSET);
    for (i = 0; i < WARP_EVENT_SLOTS; i++)
        out[i] = 0;

    ok = warp_read_chain(r, self, 0, NULL, NULL, NULL, NULL, NULL, NULL,
                         -1, out, &total);
    g_hdr->vars[6] = out[0];
    g_hdr->vars[7] = total;
    return ok ? WARP_CMD_RES_OK : WARP_CMD_RES_FAIL;
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
    /* 顺手把 self（GlobalGameManager 单例）缓存进对象槽 29：外面要读
       场景 / 时间缩放直接读这个槽，不必自己再钩 FixedUpdate —— 那会把
       命令泵的入口抢掉（真机实测：抢了就 pump: no free entry point，
       CMD_READ 全废）。 */
    if (self)
        warp_slot_put(WARP_SLOT_SCENE, self, 0);
    warp_pump_commands();
    warp_pump_ticks();
}

/* 共享 tick 槽：小插件（battle_snark 的立绘淡出）把「每帧回调」注册进
   objects[30]=WARP_TICK_MAGIC / objects[31]=函数指针，泵每帧代跑一次。
   v0.9.1 同目标双钩崩游戏的教训——别的模块不再各自挂钩子，改协作调用。
   回调跑在游戏主线程（FixedUpdate detour 里），il2cpp 调用安全。 */
#define WARP_TICK_MAGIC ((void *)(size_t)0x534B5431ull)   /* "SKT1" */
void warp_pump_ticks(void)
{
    void **slot;
    void (*tick)(void);
    if (!g_hdr)
        return;
    slot = (void **)((char *)g_hdr + WARP_OBJECTS_OFFSET);
    if (slot[WARP_SLOT_TICK_MAGIC] != WARP_TICK_MAGIC)
        return;
    tick = (void (*)(void))slot[WARP_SLOT_TICK_FN];
    if (tick)
        tick();
}

/* 诊断：列出某类里同名方法的全部重载签名。

    只碰 il2cpp 的元数据接口（class_get_methods / method_get_name /
    method_get_param_count / method_get_param / method_get_return_type /
    type_get_name），**绝不 runtime_invoke**。所以它是安全的 —— 在搞不清
    某个方法有几个重载、签名长什么样之前，先跑这个，别拿游戏进程试错。

    结果按 ``\0`` 分隔写进 MAP 尾部的命令缓冲（WARP_CMD_BUF_* 那段，
    4×64=256 字节），py 侧用 read_buf(0) 取回。 */
static int warp_cmd_list(const char *text_src)
{
    char text[WARP_CMD_TEXT_LEN];
    char name[64];
    char mname[48];
    char sig[WARP_CMD_SIG_MAX];
    char line[224];
    char *out = (char *)g_hdr + WARP_CMD_BUF_OFFSET;
    size_t cap = (size_t)WARP_CMD_BUF_COUNT * WARP_CMD_BUF_SIZE;
    const char *sep;
    void *klass;
    void *iter = NULL;
    void *m;
    size_t used = 0;
    int count = 0;
    int depth;

    if (!g_ic.class_get_methods || !g_ic.method_get_name ||
        !g_ic.method_get_param_count || !g_ic.method_get_param ||
        !g_ic.method_get_return_type || !g_ic.type_get_name)
        return WARP_CMD_RES_NO_METHOD;
    if (!text_src || !text_src[0])
        return WARP_CMD_RES_NO_METHOD;

    /* 先在本地副本上把 "|签名" 切掉，否则方法名会连签名一起被读出来。 */
    lstrcpynA(text, text_src, sizeof(text));
    warp_cmd_sig(text_src, sig, sizeof(sig));
    {
        char *bar = strchr(text, '|');
        if (bar)
            *bar = 0;
    }
    sep = strstr(text, "::");
    if (!sep)
        return WARP_CMD_RES_NO_METHOD;
    warp_cmd_name_until(text, name, sizeof(name));
    warp_cmd_name_until(sep + 2, mname, sizeof(mname));
    klass = warp_find_class(g_domain, name);
    if (!klass)
        return WARP_CMD_RES_NO_CLASS;

    /* 整块清零：只清 out[0] 的话上一次 LIST 的残留行还在，py 侧按 \0 切分
     * 会切出「m.Boolean)->S」这类碎片（0.9.21 真机输出证实过）。 */
    memset(out, 0, cap);
    /* 沿基类链往上找：il2cpp_class_get_methods 只列本类声明的方法，
       get_Instance 这类继承来的 getter 必须往上走才能列出来。 */
    for (depth = 0; klass != NULL && depth < 8; depth++) {
    iter = NULL;
    while ((m = g_ic.class_get_methods(klass, &iter)) != NULL) {
        const char *mn = g_ic.method_get_name(m);
        int argc;
        int i;
        size_t n;

        if (!mn || strcmp(mn, mname) != 0)
            continue;
        argc = (int)g_ic.method_get_param_count(m);
        n = (size_t)snprintf(line, sizeof(line), "%s(", mn);
        for (i = 0; i < argc && n + 1 < sizeof(line); i++) {
            char *tn = g_ic.type_get_name(g_ic.method_get_param(m, (uint32_t)i));
            n += (size_t)snprintf(line + n, sizeof(line) - n, "%s%s",
                                  i ? "," : "", tn ? tn : "?");
            if (tn && g_ic.free_mem)
                g_ic.free_mem(tn);
        }
        {
            char *rt = g_ic.type_get_name(g_ic.method_get_return_type(m));
            if (n + 5 < sizeof(line))
                snprintf(line + n, sizeof(line) - n, ")->%s", rt ? rt : "?");
            if (rt && g_ic.free_mem)
                g_ic.free_mem(rt);
        }
        if (sig[0] && warp_sig_match(m, argc, sig) &&
            n + 9 < sizeof(line))
            snprintf(line + n, sizeof(line) - n, " [match]");
        if (used + strlen(line) + 1 >= cap)
            break;
        lstrcpynA(out + used, line, (int)(cap - used));
        used += strlen(line) + 1;
        count++;
    }
    klass = g_ic.class_get_parent ? g_ic.class_get_parent(klass) : NULL;
    }
    return count > 0 ? 0 : WARP_CMD_RES_NO_METHOD;
}

/* ------------------------------------------------------------------ */
/* worker 线程：invoke 类命令的隔离舱（v0.9.23）                        */
/*                                                                     */
/* 六次崩溃的教训：CALL/LIST/MAKE/STR 这类要进 il2cpp 元数据与 runtime  */
/* 的命令跑在游戏主线程（FixedUpdate 泵）上，一旦踩到坏指针就是整个进程  */
/* 陪葬；在栈上挂 VEH+longjmp 救场又会弄脏 trampoline 链（0.9.12-0.9.14）。*/
/* 旧插件 BattleBGMExtend 在自己的 worker 线程 attach 后 runtime_invoke  */
/* 稳跑多年 —— 这次彻底照抄它的线程模型：invoke 类命令全部投递 worker，  */
/* 主线程泵只负责投递；worker 上挂只认自己 TID 的 VEH，就算踩到 AV 也是  */
/* longjmp 回 worker 循环顶记一次失败，进程不死。                        */
/* ------------------------------------------------------------------ */

typedef struct {
    int  seq;                       /* 对应提交时的 hdr->cmd_seq */
    int  type;                      /* 完整打包的命令字 */
    int  out_slot;                  /* call 的 vars[7] */
    char text[WARP_CMD_TEXT_LEN];   /* cmd_text 的任务私有拷贝 */
} WARP_WORK;

static HANDLE s_work_ev;
static HANDLE s_work_thread;
static DWORD  s_work_tid;
static volatile LONG s_work_quit;
static volatile LONG s_work_armed;      /* jmp_buf 是否有效（VEH 里判断） */
static jmp_buf s_work_jmp;
static void  *s_veh;
static CRITICAL_SECTION s_work_cs;
static WARP_WORK s_work;

/* 只接 worker 自己线程的 AV。主线程任何异常都不经这里（CONTINUE_SEARCH），
 * 不重演 0.9.12「任何线程的 AV 都被 longjmp 进别人的栈」的事故。 */
static LONG WINAPI work_veh(EXCEPTION_POINTERS *ep)
{
    (void)ep;
    if (s_work_armed && GetCurrentThreadId() == s_work_tid) {
        s_work_armed = 0;
        longjmp(s_work_jmp, 1);
    }
    return EXCEPTION_CONTINUE_SEARCH;
}

static DWORD WINAPI work_main(LPVOID arg)
{
    (void)arg;
    /* 旧插件哲学：worker 线程先 attach 再碰 il2cpp，一次就够。 */
    if (g_ic.thread_attach) {
        void *dom = g_domain ? g_domain :
                    (g_ic.domain_get ? g_ic.domain_get() : NULL);
        if (dom)
            g_ic.thread_attach(dom);
    }
    for (;;) {
        DWORD w = WaitForSingleObject(s_work_ev, 1000);
        if (s_work_quit)
            break;
        if (w != WAIT_OBJECT_0)
            continue;
        {
            WARP_WORK job;
            volatile int jseq;          /* longjmp 后寄存器变量不可靠 */
            int rc = WARP_CMD_RES_FAIL;

            EnterCriticalSection(&s_work_cs);
            job = s_work;
            LeaveCriticalSection(&s_work_cs);
            jseq = job.seq;

            if (setjmp(s_work_jmp) == 0) {
                /* armed 必须在 setjmp 正常返回之后再置位：否则 AV 落在
                   setjmp 前的窗口里，VEH 会 longjmp 进未初始化的 jmp_buf。 */
                s_work_armed = 1;
                switch (WARP_CMD_CODE(job.type)) {
                case WARP_CMD_MAKE:
                    rc = warp_cmd_make(WARP_CMD_ARGC(job.type),
                                       WARP_CMD_SLOT(job.type), job.text);
                    if (rc == 0 && g_hdr)
                        g_hdr->fired++;
                    break;
                case WARP_CMD_CALL:
                    rc = warp_cmd_call(WARP_CMD_ARGC(job.type),
                                       WARP_CMD_SLOT(job.type),
                                       WARP_CMD_RETKIND(job.type), job.out_slot,
                                       job.text);
                    if (rc == 0 && g_hdr)
                        g_hdr->fired++;
                    break;
                case WARP_CMD_STR:
                    rc = warp_cmd_str(WARP_CMD_SLOT(job.type), job.text);
                    if (rc == 0 && g_hdr)
                        g_hdr->fired++;
                    break;
                case WARP_CMD_LIST:
                    rc = warp_cmd_list(job.text);
                    break;
                default:
                    rc = WARP_CMD_RES_UNKNOWN;
                    break;
                }
            } else {
                /* VEH 接住 AV 跳回这里：命令记失败，线程活着继续下一单。 */
                warp_log("worker: exception recovered", 0);
                rc = WARP_CMD_RES_FAIL;
            }
            s_work_armed = 0;

            if (g_hdr) {
                g_hdr->cmd_result = rc;
                g_hdr->cmd_ack = jseq;
            }
        }
    }
    return 0;
}

void warp_work_start(void)
{
    if (s_work_thread)
        return;
    InitializeCriticalSection(&s_work_cs);
    s_work_quit = 0;
    s_work_armed = 0;
    s_work_ev = CreateEventW(NULL, FALSE, FALSE, NULL);
    s_veh = AddVectoredExceptionHandler(1, work_veh);
    s_work_thread = CreateThread(NULL, 0, work_main, NULL, 0, &s_work_tid);
    if (!s_work_thread) {
        warp_log("worker: create failed", 0);
        if (s_veh) {
            RemoveVectoredExceptionHandler(s_veh);
            s_veh = NULL;
        }
        if (s_work_ev) {
            CloseHandle(s_work_ev);
            s_work_ev = NULL;
        }
        DeleteCriticalSection(&s_work_cs);
        return;
    }
    warp_log("worker started", 0);
}

void warp_work_stop(void)
{
    if (s_work_thread) {
        s_work_quit = 1;
        SetEvent(s_work_ev);
        if (WaitForSingleObject(s_work_thread, 3000) != WAIT_OBJECT_0)
            warp_log("worker: stop timeout", 0);
        CloseHandle(s_work_thread);
        s_work_thread = NULL;
    }
    if (s_veh) {
        RemoveVectoredExceptionHandler(s_veh);
        s_veh = NULL;
    }
    s_work_armed = 0;
    if (s_work_ev) {
        CloseHandle(s_work_ev);
        s_work_ev = NULL;
    }
    DeleteCriticalSection(&s_work_cs);
}

/* 泵投递一个任务。返回 0=已受理（结果稍后由 worker 写回），非 0=没跑成。 */
static int work_submit(int seq, int type, int out_slot)
{
    WARP_WORK job;

    if (!s_work_thread || s_work_quit || !s_work_ev || !g_hdr)
        return -1;
    ZeroMemory(&job, sizeof(job));
    job.seq = seq;
    job.type = type;
    job.out_slot = out_slot;
    lstrcpynA(job.text, g_hdr->cmd_text, WARP_CMD_TEXT_LEN);
    EnterCriticalSection(&s_work_cs);
    s_work = job;
    LeaveCriticalSection(&s_work_cs);
    SetEvent(s_work_ev);
    return 0;
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
    /* 先记账再执行：弹窗里可能重入（弹窗自己又触发钩子），不能重复执行。
       但记账之后、执行完之前 cmd_result 还停在上一条的旧值 —— py 侧一看到
       ack 到位就把旧值当成结果读走，表现为莫名其妙的「失败(-1)」。所以
       先标成 BUSY，真跑完再把 rc 写回。 */
    g_hdr->cmd_ack = seq;
    g_hdr->cmd_result = WARP_CMD_RES_BUSY;

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
    case WARP_CMD_CALL:
    case WARP_CMD_STR:
    case WARP_CMD_LIST:
        /* v0.9.23：这四类要进 il2cpp runtime/元数据的命令全部投递 worker
         * 隔离舱，主线程泵不再亲自执行（六次崩溃都在这条路径上）。先标
         * BUSY，结果与 ack 由 worker 写回；worker 没起来就记 FAIL，绝不
         * 回退主线程执行。 */
        g_hdr->cmd_result = WARP_CMD_RES_BUSY;
        if (work_submit(seq, type, (int)g_hdr->vars[7]) != 0) {
            g_hdr->cmd_result = WARP_CMD_RES_FAIL;
            warp_log("worker unavailable, cmd dropped", 0);
        }
        rc = -1;                        /* 告诉尾部：结果已有人写，别覆盖 */
        break;
    case WARP_CMD_RELEASE:
        rc = warp_cmd_release(WARP_CMD_SLOT(type));
        break;
    case WARP_CMD_READ:
        /* 代读不是"动作"，不计 fired —— 它是查询，每秒可以来几十次 */
        rc = warp_cmd_read(WARP_CMD_SLOT(type));
        break;
    default:
        rc = WARP_CMD_RES_UNKNOWN;      /* 未知命令 */
        break;
    }

    if (g_hdr && rc != -1)
        g_hdr->cmd_result = rc;
}

/* 目标入口是不是已经被别的模块（或本表其他条目）钩过了。
 *
 * 各 DLL 的 MinHook 实例互不知情：两个 DLL 钩同一个方法会形成嵌套跳板链，
 * 后挂者把自己的 original 指向前者的 thunk，调用一次、两边逻辑各跑两遍，
 * 挂载时机一撞就是撕裂的跳板 —— v0.9.1 真机上就是这么把游戏崩掉的。
 * 入口是 E9（近 jmp）或 FF 25（间接 jmp）就视为已占用：少装一个钩子、
 * 降级运行，好过崩掉整个进程。必须在 MH_CreateHook 之前检查 —— create
 * 时 MinHook 会把别人的 jmp 当普通指令拷进跳板，嵌套就成立了。 */
static int warp_target_taken(void *target)
{
    unsigned char pro[6];
    MEMORY_BASIC_INFORMATION mb;
    int j;

    if (!target)
        return 0;
    if (!VirtualQuery(target, &mb, sizeof(mb)) ||
        mb.State != MEM_COMMIT ||
        (mb.Protect & (PAGE_NOACCESS | PAGE_GUARD)))
        return 0;
    CopyMemory(pro, target, sizeof(pro));
    if (pro[0] == 0xE9)
        return 1;
    if (pro[0] == 0xFF && pro[1] == 0x25)
        return 1;
    for (j = 0; j < WARP_MAX_HOOKS; j++) {
        if (g_slots[j].installed && g_slots[j].target == target)
            return 1;   /* 表内两条钩子配了同一方法，同样不许 */
    }
    return 0;
}

/* MinHook 初始化只做一次；重试路径也要能确保它已经就绪。 */
static BOOL s_mh_ready = FALSE;

static BOOL warp_mh_ensure(void)
{
    MH_STATUS st;

    if (s_mh_ready)
        return TRUE;
    st = MH_Initialize();
    if (st == MH_OK || st == MH_ERROR_ALREADY_INITIALIZED) {
        s_mh_ready = TRUE;
        return TRUE;
    }
    return FALSE;
}

int warp_install_hooks(void)
{
    void *domain;
    int i;
    int installed = 0;
    int total = 0;
    BOOL mh_ready = FALSE;

    /* 自检：thunk 表每个数组必须全槽非空。v0.9.1 把 16 槽扩到 32 时
     * 初始化实例漏补一半，槽 16+ 的 thunk 全是 NULL，装钩全数死在
     * "unsupported argc"——而且日志打印的是 argc 值，极具迷惑性。
     * 这里在装钩前把这类结构性错误显式掀出来。 */
    {
        void *const *const tabs[10] = {
            g_thunks0, g_thunks1, g_thunks2, g_thunks3, g_thunks4,
            g_thunks5, g_thunks6, g_thunks7, g_thunks8, g_thunks9
        };
        int t;
        for (t = 0; t < 10; t++) {
            if (!tabs[t][WARP_MAX_HOOKS - 1]) {
                warp_log("thunk table truncated (argc slot)", t);
                warp_status(WARP_ST_ERROR, WARP_ERR_MH_INIT);
                return 0;
            }
        }
    }

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
        /* GlobalGameManager 的 FixedUpdate / Update 是命令泵自己占的入口：
         * 用户钩了它，pump 就找不到空位，CMD_READ / 弹窗 / 每帧回调全线
         * 失效（真机实测日志：pump: no free entry point）。场景对象宿主
         * 已经每帧缓存进 WARP_SLOT_SCENE，改读那个槽即可。 */
        if (!strcmp(h->klass, "GlobalGameManager")
            && (!strcmp(h->method, "FixedUpdate") || !strcmp(h->method, "Update")))
            warp_log("warn: GlobalGameManager timeline is the command pump "
                     "entry, hooking it disables CMD_READ (slot)", i);
        if (g_slots[i].installed) {
            installed++;
            continue;
        }

        klass = warp_find_class(domain, h->klass);
        if (!klass) {            warp_log("hook: class not found", i);
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
            if (!warp_mh_ensure()) {
                warp_status(WARP_ST_ERROR, WARP_ERR_MH_INIT);
                warp_log("MH_Initialize failed", 0);
                return installed;
            }
            mh_ready = TRUE;
        }
        if (warp_target_taken(target)) {
            warp_log("hook: target already hooked elsewhere", i);
            continue;
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
       跑到的主线程入口，否则 py 主动调用 popup 要等到下次抽卡才生效。
       FixedUpdate 若已被别的模块钩走（warp_target_taken），退而求其次用
       Update —— 再被占用就只能放弃命令通道，事件钩子照常工作。 */
    if (mh_ready && !g_pump_installed) {
        static const char *PUMP_CANDIDATES[] = { "FixedUpdate", "Update" };
        int ci;
        for (ci = 0; ci < 2 && !g_pump_installed; ci++) {
            void *gklass = warp_find_class(domain, "GlobalGameManager");
            void *gmethod = gklass ? warp_find_method(gklass, PUMP_CANDIDATES[ci], 0) : NULL;
            void *gtarget = gmethod ? warp_method_pointer(gmethod) : NULL;
            if (!gtarget || warp_target_taken(gtarget))
                continue;
            if (MH_CreateHook(gtarget, hk_warp_pump, &g_pump_original) == MH_OK) {
                if (MH_EnableHook(gtarget) == MH_OK) {
                    g_pump_target = gtarget;
                    g_pump_installed = 1;
                    warp_log("pump hook installed on", ci);
                } else {
                    MH_RemoveHook(gtarget);
                }
            }
        }
        if (!g_pump_installed)
            warp_log("pump: no free entry point, cmd channel off", 0);
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

    /* worker 隔离舱随钩子装配一起就位：domain 已就绪（上面 find_class 用过），
       invoke 类命令从此有了安全的落脚点。 */
    warp_work_start();
    return installed;
}

int warp_retry_hooks(void)
{
    void *domain;
    int i;
    int newly = 0;

    if (!g_hdr || !g_ic_ready)
        return 0;
    domain = g_ic.domain_get();
    if (!domain)
        return 0;

    /* il2cpp 的类是按需加载的：DLL 在 engine ready 时就装配，那时战斗类
       （BattleObjectManager 之类）往往还没被游戏代码碰过，class_from_name
       返回 NULL。装配阶段放弃的槽如果就这么算了，那些钩子一辈子装不上 ——
       表现是「插件逻辑不执行、也不报错」。所以主循环定期回来重试一次。 */
    for (i = 0; i < WARP_MAX_HOOKS; i++) {
        WARP_HOOK *h = &g_warp_hooks[i];
        void *klass;
        void *method;
        void *target;
        void *thunk;

        if (!h->klass[0] || !h->method[0])
            continue;
        if (g_slots[i].installed)
            continue;
        klass = warp_find_class(domain, h->klass);
        if (!klass)
            continue;
        method = warp_find_method(klass, h->method, h->argc);
        if (!method)
            continue;
        target = warp_method_pointer(method);
        if (!target)
            continue;
        thunk = warp_pick_thunk(i, h->argc);
        if (!thunk)
            continue;
        if (warp_target_taken(target))
            continue;
        if (!warp_mh_ensure())
            continue;
        g_slots[i].argc = h->argc;
        if (MH_CreateHook(target, thunk, &g_slots[i].original) != MH_OK)
            continue;
        if (MH_EnableHook(target) != MH_OK) {
            MH_RemoveHook(target);
            continue;
        }
        g_slots[i].target = target;
        g_slots[i].installed = TRUE;
        newly++;
        warp_log("hook installed (late)", i);
    }
    if (newly && g_hdr) {
        g_installed += newly;
        g_hdr->hook_installed = g_installed;
        g_hdr->hooked = g_installed > 0 ? 1 : 0;
    }
    return newly;
}

void warp_uninstall(void)
{
    int i;
    /* 先停 worker：它可能正在 invoke，带着 trampoline 外的栈等它退出，
     * 之后才能安全拆 MinHook 与 VEH。 */
    warp_work_stop();
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
    /* MH_Uninitialize 之后必须把「已初始化」的标志也清掉：0.9.12 里忘了
     * 复位，第二次重装时 warp_mh_ensure 看见 TRUE 直接返回，MinHook 其实
     * 已经 uninit —— 结果 23 条钩子全部 "hook: create failed"，整张表死掉
     * （真机 2026-10-31 18:35 撞到，只能重启游戏）。 */
    s_mh_ready = FALSE;
    /* 归零，否则控制线程会一直以为「已经装好了」而不去重装新表 */
    g_installed = 0;
    if (g_hdr) {
        g_hdr->hook_installed = 0;
        g_hdr->hooked = 0;
    }
}

