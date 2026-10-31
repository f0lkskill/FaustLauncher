/* warp_internal.h —— 宿主内部共享的符号表。
 *
 * 拆分前所有东西都在一个 warp_host.c 里，靠 static 藏着；拆成多个翻译
 * 单元之后，这些符号必须彼此可见，于是统一在这里登记一遍。
 * 对外导出面仍然只有 DllMain 一个，这里的东西不出这个 DLL。
 */
#pragma once
#include "warp_layout.h"
#include <string.h>
#include <setjmp.h>

/* ---- 类型 ---- */
typedef struct {
    fn_domain_get                 domain_get;
    fn_domain_get_assemblies      domain_get_assemblies;
    fn_assembly_get_image         assembly_get_image;
    fn_class_from_name            class_from_name;
    fn_class_get_method_from_name class_get_method_from_name;
    fn_string_new                 string_new;
    fn_runtime_invoke             runtime_invoke;
    fn_thread_attach              thread_attach;
    fn_object_new                 object_new;
    fn_class_get_type             class_get_type;
    fn_type_get_object            type_get_object;
    fn_array_new                  array_new;
    fn_class_get_parent           class_get_parent;
    fn_gchandle_new               gchandle_new;
    fn_gchandle_free              gchandle_free;
    fn_class_get_methods              class_get_methods;
    fn_method_get_name              method_get_name;
    fn_method_get_param_count              method_get_param_count;
    fn_method_get_param              method_get_param;
    fn_method_get_return_type              method_get_return_type;
    fn_type_get_name              type_get_name;
    fn_free_mem              free_mem;
} WARP_IC;

typedef struct {
    void *target;
    void *original;
    BOOL  installed;
    int   argc;
} WARP_SLOT;

/* ---- 全局状态 ---- */
extern HINSTANCE     g_hinst;
extern HANDLE        g_map;
extern LONG          g_hit_count[WARP_MAX_HOOKS];
extern ULONGLONG     g_last_fire[WARP_MAX_HOOKS];
extern int           g_last_vals[WARP_MAX_HOOKS][WARP_EVENT_SLOTS];
extern unsigned char g_last_valid[WARP_MAX_HOOKS];
extern WARP_HEADER  *g_hdr;
extern WARP_HOOK    *g_warp_hooks;
extern char         *g_texts;
extern char         *g_exports;
extern HANDLE        g_thread;
extern HANDLE        g_stop;
extern WARP_IC       g_ic;
extern const char   *g_export_names[WARP_EXPORT_COUNT];
extern WARP_SLOT     g_slots[WARP_MAX_HOOKS];
extern int           g_installed;
extern int           g_ic_ready;
extern int           g_armed;
extern void         *g_domain;
extern void         *g_popup_mgr_method;
extern void         *g_popup_open_method;
extern void         *g_popup_mgr_cached;
extern unsigned int  g_rng;
extern void         *g_pump_target;
extern void         *g_pump_original;
extern int           g_pump_installed;
extern void *const   g_thunks0[WARP_MAX_HOOKS];
extern void *const   g_thunks1[WARP_MAX_HOOKS];
extern void *const   g_thunks2[WARP_MAX_HOOKS];
extern void *const   g_thunks3[WARP_MAX_HOOKS];
extern void *const   g_thunks4[WARP_MAX_HOOKS];
extern void *const   g_thunks5[WARP_MAX_HOOKS];
extern void *const   g_thunks6[WARP_MAX_HOOKS];
extern void *const   g_thunks7[WARP_MAX_HOOKS];
extern void *const   g_thunks8[WARP_MAX_HOOKS];
extern void *const   g_thunks9[WARP_MAX_HOOKS];

/* ---- 函数 ---- */
void warp_pump_commands(void);
void warp_pump_ticks(void);   /* objects[30]/[31] 共享 tick 槽（battle_snark 淡出） */
void warp_log(const char *msg, int value);
void warp_status(int st, int err);
unsigned int warp_rand(void);
int warp_open_map(void);
void *find_export(HMODULE ga, int index);
int warp_bind_exports(void);
int warp_wait_ready(void);
void *warp_find_class(void *domain, const char *name);
void *warp_find_method(void *klass, const char *name, int argc);
void *warp_method_pointer(void *method);
void warp_resolve_popup(void *domain);
int warp_show_popup(const char *utf8);
DWORD WINAPI warp_kill_thread(LPVOID param);
const char *warp_pick_text(int base);
/* v8：命中时该钩子要不要改写第 arg 个参数；返回替换指针，NULL = 不改。 */
void *warp_rewrite_value(int hook_index, int arg_index);
void warp_fire(int hook_index);
int warp_probe_int(const char *klass_name, const char *method_name, void *obj);
int warp_on_event(int hook_index, void *self, int argc,
                  void *a1, void *a2, void *a3,
                  void *a4, void *a5, void *a6);
void warp_on_event_post(int hook_index, WARP_HOOK *h, void *self, int argc,
                        void *a1, void *a2, void *a3,
                        void *a4, void *a5, void *a6, int ret);
int warp_emits_post(const WARP_HOOK *h);
static inline WARP_HOOK *warp_hook_at(int index)
{
    if (!g_warp_hooks || index < 0 || index >= WARP_MAX_HOOKS)
        return NULL;
    return &g_warp_hooks[index];
}
void *warp_pick_thunk(int index, int argc);
void **warp_objects(void);
void warp_slot_put(int slot, void *obj, int with_handle);
void *warp_slot_get(int slot);
/* v7：命令通道代读要复用钩子那条读链执行器（原来只在 warp_action.c 内部用）。
 * nth=-1 是普通求值，iter_total 只有遍历链才有意义。返回 1 成功 / 0 没读到。 */
int warp_read_chain(const WARP_READ *r, void *self, int argc,
                    void *a1, void *a2, void *a3,
                    void *a4, void *a5, void *a6, int nth, int *out,
                    int *iter_total);
/* 从第 slot 个对象槽出发执行 cmd_read 段里的那条链，结果写 vars[6]（值）
 * 与 vars[7]（遍历链的活跃数）。返回 WARP_CMD_RES_*。 */
int warp_cmd_read(int slot);

/* 带异常保护地调一个 il2cpp 方法（VEH 接管访问违例）。 */
void *warp_safe_invoke(void *method, void *target, void **params, void **exc);

/* 重试装配阶段因「类还没加载」而失败的钩子槽，返回新装上的数量。 */
int warp_retry_hooks(void);
int warp_cmd_make(int argc, int slot, const char *argkinds);
int warp_cmd_call(int argc, int slot, int retkind, int out_slot, const char *argkinds);
int warp_cmd_str(int slot);
int warp_cmd_release(int slot);
int warp_kill_game(void);
void __stdcall hk_warp_pump(void *self);
int warp_install_hooks(void);
void warp_uninstall(void);
unsigned int warp_hook_signature(void);
extern unsigned int g_hook_sig;
DWORD WINAPI warp_thread(LPVOID param);
void warp_start(void);
void warp_stop_cleanup(void);
