/* warp_state.c —— il2cpp 接口表实例、全局变量、日志与随机数
 *
 * 由 warp_host.c 拆分而来（原第 162-292 行）。
 */
#include "warp_internal.h"

WARP_IC g_ic;

/* 必须和 Python 侧 IL2CPP_EXPORTS 顺序一致 */
const char *g_export_names[WARP_EXPORT_COUNT] = {
    "il2cpp_domain_get",
    "il2cpp_domain_get_assemblies",
    "il2cpp_assembly_get_image",
    "il2cpp_class_from_name",
    "il2cpp_class_get_method_from_name",
    "il2cpp_string_new",
    "il2cpp_runtime_invoke",
    "il2cpp_thread_attach",
    "il2cpp_object_new",
    "il2cpp_class_get_type",
    "il2cpp_type_get_object",
    "il2cpp_array_new",
    "il2cpp_class_get_parent",
};

/* ------------------------------------------------------------------ */
/* 全局状态                                                            */
/* ------------------------------------------------------------------ */

HINSTANCE     g_hinst;
HANDLE        g_map = NULL;
LONG        g_hit_count[WARP_MAX_HOOKS];  /* 每个钩子自己被命中多少次 */
ULONGLONG   g_last_fire[WARP_MAX_HOOKS];  /* 每个钩子上次执行动作的时刻 */
WARP_HEADER  *g_hdr = NULL;

WARP_HOOK    *g_warp_hooks = NULL;      /* 指向 map 内 128 偏移 */
char         *g_texts = NULL;      /* 指向 map 内 2176 偏移 */
char         *g_exports = NULL;    /* 指向 map 内 6272 偏移 */

HANDLE        g_thread = NULL;
HANDLE        g_stop = NULL;

WARP_SLOT g_slots[WARP_MAX_HOOKS];
int  g_installed = 0;
int  g_ic_ready = 0;
int  g_armed = 0;             /* 1 = 门闩已通过 */

void *g_popup_mgr_method = NULL;   /* GlobalGameManager.get_Instance */
void *g_domain = NULL;             /* 就绪后缓存的 il2cpp 域，探针要用 */
void *g_popup_open_method = NULL;  /* GlobalGameManager.OpenGlobalPopup */
void *g_popup_mgr_cached = NULL;   /* 缓存的单例实例（主线程里取） */

unsigned int g_rng = 0x9E3779B9u;

/* ------------------------------------------------------------------ */
/* 小工具                                                              */
/* ------------------------------------------------------------------ */

void warp_log(const char *msg, int value)
{
    char line[160];
    char path[MAX_PATH];
    HANDLE f;
    DWORD wrote = 0;
    int n;

    if (!g_hinst)
        return;
    if (!GetModuleFileNameA(g_hinst, path, MAX_PATH))
        return;
    {
        char *slash = path;
        char *p = path;
        while (*p) {
            if (*p == '\\' || *p == '/')
                slash = p;
            p++;
        }
        *(slash + 1) = 0;
    }
    lstrcatA(path, "warp_host.log");

    n = wsprintfA(line, "[warp][t%lu] %s (%d)\r\n",
                  (unsigned long)GetCurrentThreadId(), msg, value);
    f = CreateFileA(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
                    NULL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (f != INVALID_HANDLE_VALUE) {
        WriteFile(f, line, (DWORD)n, &wrote, NULL);
        CloseHandle(f);
    }

    if (g_hdr) {
        lstrcpynA(g_hdr->log_tail, msg, WARP_LOG_LEN);
    }
}

void warp_status(int st, int err)
{
    if (!g_hdr)
        return;
    g_hdr->status = st;
    if (err)
        g_hdr->last_error = err;
}

unsigned int warp_rand(void)
{
    unsigned int x = g_rng;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    g_rng = x;
    return x;
}
