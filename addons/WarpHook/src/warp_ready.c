/* warp_ready.c —— 就绪门闩：等程序集、等域、等引擎
 *
 * 由 warp_host.c 拆分而来（原第 416-475 行）。
 */
#include "warp_internal.h"

/* ------------------------------------------------------------------ */
/* 就绪门闩：五阶段                                                    */
/* ------------------------------------------------------------------ */

int warp_wait_ready(void)
{
    void *domain;
    void **asm_list;
    size_t count = 0;

    if (g_armed)
        return 1;

    /* 阶段 0：DLL 被映射 */
    if (!GetModuleHandleW(L"GameAssembly.dll")) {
        if (g_hdr)
            g_hdr->ga_found = 0;
        return 0;
    }
    if (g_hdr && g_hdr->ga_found < 1)
        g_hdr->ga_found = 1;

    /* 阶段 1：拿到导出名 */
    if (!warp_bind_exports())
        return 0;

    /* 阶段 2：域指针 */
    domain = g_ic.domain_get();
    if (!domain)
        return 0;
    g_domain = domain;
    if (g_hdr && g_hdr->ga_found < 2)
        g_hdr->ga_found = 2;

    /* 阶段 3：程序集数组成形。域在、程序集没灌完时碰运行时接口必崩 */
    asm_list = g_ic.domain_get_assemblies(domain, &count);
    if (!asm_list || count < WARP_MIN_ASSEMBLIES)
        return 0;

    /* 阶段 4：稳定窗。中间态抖动会让刚刚拿到的类指针失效 */
    if (!g_armed) {
        static ULONGLONG first_ok = 0;
        if (!first_ok) {
            first_ok = GetTickCount64();
            warp_log("assemblies ready, settling", (int)count);
            return 0;
        }
        if (GetTickCount64() - first_ok < WARP_SETTLE_MS)
            return 0;
    }

    if (g_hdr) {
        g_hdr->ga_found = 3;
        g_hdr->boot_at = GetTickCount64();
    }
    g_armed = 1;
    warp_log("engine ready", (int)count);
    return 1;
}

