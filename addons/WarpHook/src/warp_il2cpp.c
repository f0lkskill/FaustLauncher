/* warp_il2cpp.c —— 导出名绑定：找函数地址、填接口表
 *
 * 由 warp_host.c 拆分而来（原第 341-415 行）。
 */
#include "warp_internal.h"

/* ------------------------------------------------------------------ */
/* 导出名绑定                                                          */
/* ------------------------------------------------------------------ */

void *find_export(HMODULE ga, int index)
{
    const char *canonical;
    const char *mapped;
    void *addr;

    if (index < 0 || index >= WARP_EXPORT_COUNT)
        return NULL;
    canonical = g_export_names[index];

    /* 共享内存里那一列是 Python 算好的「混淆名」，可能为空 */
    mapped = g_exports ? (g_exports + index * WARP_NAME_MAX) : NULL;
    if (mapped && mapped[0]) {
        addr = (void *)GetProcAddress(ga, mapped);
        if (addr)
            return addr;
    }
    /* 兜底：有些版本的导出名没被混淆，直接按原名找 */
    addr = (void *)GetProcAddress(ga, canonical);
    if (addr)
        return addr;
    return NULL;
}

int warp_bind_exports(void)
{
    HMODULE ga;
    int i;
    int got = 0;

    if (g_ic_ready)
        return 1;

    ga = GetModuleHandleW(L"GameAssembly.dll");
    if (!ga)
        return 0;

    g_ic.domain_get                 = (fn_domain_get)find_export(ga, 0);
    g_ic.domain_get_assemblies      = (fn_domain_get_assemblies)find_export(ga, 1);
    g_ic.assembly_get_image         = (fn_assembly_get_image)find_export(ga, 2);
    g_ic.class_from_name            = (fn_class_from_name)find_export(ga, 3);
    g_ic.class_get_method_from_name = (fn_class_get_method_from_name)find_export(ga, 4);
    g_ic.string_new                 = (fn_string_new)find_export(ga, 5);
    g_ic.runtime_invoke             = (fn_runtime_invoke)find_export(ga, 6);
    g_ic.thread_attach              = (fn_thread_attach)find_export(ga, 7);
    g_ic.object_new                 = (fn_object_new)find_export(ga, 8);
    g_ic.class_get_type             = (fn_class_get_type)find_export(ga, 9);
    g_ic.type_get_object            = (fn_type_get_object)find_export(ga, 10);
    g_ic.array_new                  = (fn_array_new)find_export(ga, 11);
    g_ic.class_get_parent           = (fn_class_get_parent)find_export(ga, 12);
    /* gchandle 两个是对象构造（P6）用的：构造出来的对象挂强句柄防 GC 收走。
     * 缺了不致命 —— make/str 退化为裸指针落槽（对象可能在用之前被回收），
     * 所以不进「前 5 个」那种命脉检查。 */
    g_ic.gchandle_new               = (fn_gchandle_new)find_export(ga, 13);
    g_ic.gchandle_free              = (fn_gchandle_free)find_export(ga, 14);

    for (i = 0; i < WARP_EXPORT_COUNT; i++) {
        void *p = find_export(ga, i);
        if (p)
            got++;
    }

    /* 前 5 个是元数据查询的命脉，缺一个就没法干活 */
    if (!g_ic.domain_get || !g_ic.domain_get_assemblies ||
        !g_ic.assembly_get_image || !g_ic.class_from_name ||
        !g_ic.class_get_method_from_name) {
        warp_status(WARP_ST_ERROR, WARP_ERR_NO_IL2CPP);
        warp_log("bind exports failed", got);
        return 0;
    }

    g_ic_ready = 1;
    /* 前面几轮可能失败过（初始化早期导出表还是空的），这里成功就把
     * 那条残留错误清掉 —— 否则状态行会一直挂着「取不到 il2cpp 接口」，
     * 明明已经能用，看日志的人会以为坏了。 */
    if (g_hdr && g_hdr->last_error == WARP_ERR_NO_IL2CPP)
        g_hdr->last_error = 0;
    warp_log("bind exports ok", got);
    return 1;
}


/* warp_il2cpp.c —— 类与方法查询
 *
 * 由 warp_host.c 拆分而来（原第 476-550 行）。
 */
#include "warp_internal.h"

/* ------------------------------------------------------------------ */
/* 类与方法查询                                                        */
/* ------------------------------------------------------------------ */

void *warp_find_class(void *domain, const char *name)
{
    size_t count = 0;
    void **asm_list;
    size_t i;
    char ns_buf[64];
    const char *dot;
    const char *type_name;

    if (!name || !name[0])
        return NULL;

    /* 名字里带点就是「命名空间.类名」——按**最后一个**点分割：
     * 命名空间自身可以带点（LimbusCompany.RailwayDungeon.HistoryLibs），
     * 类名永远是末段。v0.9.2 之前按第一个点分，多级命名空间全灭。 */
    dot = strrchr(name, '.');
    if (dot && (size_t)(dot - name) < sizeof(ns_buf)) {
        memcpy(ns_buf, name, (size_t)(dot - name));
        ns_buf[dot - name] = '\0';
        type_name = dot + 1;
    } else {
        ns_buf[0] = '\0';
        type_name = name;
    }

    asm_list = g_ic.domain_get_assemblies(domain, &count);
    if (!asm_list)
        return NULL;

    /* 第一遍：ns + 短名精确查（标准路径）。 */
    for (i = 0; i < count; i++) {
        void *image = g_ic.assembly_get_image(asm_list[i]);
        void *klass;
        if (!image)
            continue;
        if (ns_buf[0]) {
            klass = g_ic.class_from_name(image, ns_buf, type_name);
            if (klass)
                return klass;
            continue;
        }
        klass = g_ic.class_from_name(image, "", type_name);
        if (klass)
            return klass;
        klass = g_ic.class_from_name(image, "System", type_name);
        if (klass)
            return klass;
    }
    if (!ns_buf[0])
        goto not_found;

    /* 第二遍兜底：只按短名扫全图（ns=""）。真机 v0.9.3 实证铁路三类
     * （LimbusCompany.RailwayDungeon.*）精确 ns 查询全灭而短名类能找到
     * —— 有些版本的 metadata 里 ns 字符串和 C# 逻辑命名空间对不上，
     * 短名至少能把类捞回来。短名撞名概率低，先到先得。 */
    for (i = 0; i < count; i++) {
        void *image = g_ic.assembly_get_image(asm_list[i]);
        void *klass;
        if (!image)
            continue;
        klass = g_ic.class_from_name(image, "", type_name);
        if (klass)
            return klass;
    }

not_found:
    return NULL;
}

/* 沿继承链找方法：class_get_method_from_name 只查本类 */
void *warp_find_method(void *klass, const char *name, int argc)
{
    void *cur = klass;
    int depth = 0;

    while (cur && depth < 32) {
        void *m = g_ic.class_get_method_from_name(cur, name, argc);
        if (m)
            return m;
        if (!g_ic.class_get_parent)
            break;
        cur = g_ic.class_get_parent(cur);
        depth++;
    }
    return NULL;
}

void *warp_method_pointer(void *method)
{
    return method ? *(void **)method : NULL;
}

