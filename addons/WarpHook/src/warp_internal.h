/* warp_internal.h —— 宿主内部共享的符号表。
 *
 * 拆分前所有东西都在一个 warp_host.c 里，靠 static 藏着；拆成多个翻译
 * 单元之后，这些符号必须彼此可见，于是统一在这里登记一遍。
 * 对外导出面仍然只有 DllMain 一个，这里的东西不出这个 DLL。
 */
#pragma once
#include "warp_layout.h"

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
extern int           g_last_vals[WARP_MAX_HOOKS][4];
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

/* ---- 函数 ---- */
void warp_pump_commands(void);
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
void warp_fire(int hook_index);
int warp_probe_int(const char *klass_name, const char *method_name, void *obj);
int warp_on_event(int hook_index, void *self, int argc,
                  void *a1, void *a2, void *a3);
void *warp_pick_thunk(int index, int argc);
int warp_kill_game(void);
void __stdcall hk_warp_pump(void *self);
int warp_install_hooks(void);
void warp_uninstall(void);
unsigned int warp_hook_signature(void);
extern unsigned int g_hook_sig;
DWORD WINAPI warp_thread(LPVOID param);
void warp_start(void);
void warp_stop_cleanup(void);
