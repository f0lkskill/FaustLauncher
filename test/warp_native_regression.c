/* Standalone Windows/x64 regression. Includes the production command unit so
 * lifecycle assertions inspect the actual retained MinHook and worker state.
 * Link all other warp_*.c except warp_host.c and warp_cmd.c. Never loads a DLL. */
#include <assert.h>
#include <stdio.h>
#include <windows.h>
/* Standalone EXE acts as GameAssembly only for direct-call page validation.
 * The command implementation and actual native call remain unchanged. */
static HMODULE regression_module(LPCWSTR name) {
    if (name && !wcscmp(name, L"GameAssembly.dll")) return GetModuleHandleW(NULL);
    return GetModuleHandleW(name);
}
#define GetModuleHandleW regression_module
#include "../addons/WarpHook/src/warp_cmd.c"
#undef GetModuleHandleW

static unsigned char map_bytes[WARP_MAP_BYTES];
static HANDLE entered, resume_job;
static volatile LONG strings, frees;
static const uintptr_t sentinel = (uintptr_t)0x123456789abcdef0ULL;
static int runtime_static_calls, runtime_static_null;
static void **static_assemblies(void *domain, size_t *count) {
    static void *items[1] = {(void *)1}; (void)domain; *count=1; return items;
}
static void *static_image(void *assembly) { return assembly; }
static void *static_class(void *image, const char *ns, const char *name) {
    (void)image; (void)ns; return !strcmp(name,"SoundManager") ? (void *)2 : NULL;
}
static void *static_parent(void *klass) { return klass==(void *)2 ? (void *)3 : NULL; }
static void *static_field(void *klass, const char *name) {
    return klass==(void *)3 && !strcmp(name,"_instance") ? (void *)4 : NULL;
}
static void static_value(void *field, void *out) {
    assert(field==(void *)4); runtime_static_calls++;
    *(void **)out=runtime_static_null ? NULL : (void *)sentinel;
}
static void test_static_runtime(void) {
    g_ic.domain_get_assemblies=static_assemblies;
    g_ic.assembly_get_image=static_image;
    g_ic.class_from_name=static_class;
    g_ic.class_get_parent=static_parent;
    g_ic.class_get_field_from_name=static_field;
    g_ic.field_static_get_value=static_value;
    assert(warp_cmd_static("SoundManager::_instance",26)==WARP_CMD_RES_OK);
    assert(runtime_static_calls==1 && warp_slot_get(26)==(void *)sentinel);
    runtime_static_null=1;
    assert(warp_cmd_static("SoundManager::_instance",26)==WARP_CMD_RES_FAIL);
    assert(runtime_static_calls==2);
    puts("PASS static singleton: inherited field uses runtime API, no guessed offsets, null fails");
}

__attribute__((noinline)) static unsigned long long target_int(void *self, void *mi)
{
    __asm__ volatile("nop; nop; nop; nop; nop; nop; nop; nop" ::: "memory");
    return (uintptr_t)self ^ (uintptr_t)mi ^ sentinel;
}
__attribute__((noinline)) static float target_float(void *self, void *mi)
{
    __asm__ volatile("nop; nop; nop; nop; nop; nop; nop; nop" ::: "memory");
    return (float)((uintptr_t)self + (uintptr_t)mi) + 0.25f;
}
__attribute__((noinline)) static unsigned long long target_nine(void *self,
    void *a1, void *a2, void *a3, void *a4, void *a5, void *a6, void *a7,
    void *a8, void *a9, void *mi)
{
    __asm__ volatile("nop; nop; nop; nop; nop; nop; nop; nop" ::: "memory");
    return (uintptr_t)self + (uintptr_t)a1 + 2*(uintptr_t)a2 + 3*(uintptr_t)a3 +
        4*(uintptr_t)a4 + 5*(uintptr_t)a5 + 6*(uintptr_t)a6 + 7*(uintptr_t)a7 +
        8*(uintptr_t)a8 + 9*(uintptr_t)a9 + 10*(uintptr_t)mi;
}
static void *fake_string(const char *text)
{
    assert(!strcmp(text, "first"));
    InterlockedIncrement(&strings);
    SetEvent(entered);
    assert(WaitForSingleObject(resume_job, 10000) == WAIT_OBJECT_0);
    return (void *)sentinel;
}
static uintptr_t fake_new(void *obj, unsigned int pin)
{
    (void)pin;
    assert(obj == (void *)sentinel);
    return sentinel;
}
static void fake_free(uintptr_t handle)
{
    assert(handle == sentinel);
    InterlockedIncrement(&frees);
    /* Reentrant pump must not dispatch the command a second time or deadlock. */
    warp_pump_commands();
}
static DWORD WINAPI pump_thread(LPVOID ignored)
{
    int i;
    (void)ignored;
    for (i = 0; i < 10000; i++) warp_pump_commands();
    return 0;
}
static void wait_result(void)
{
    ULONGLONG deadline = GetTickCount64() + 10000;
    while (InterlockedCompareExchange(&s_cmd_busy, 0, 0)) {
        assert(GetTickCount64() < deadline);
        Sleep(1);
    }
    assert(g_hdr->cmd_result == 0);
}
static void test_signature(void)
{
    unsigned int sig;
    strcpy(g_warp_hooks[0].klass, "BattleObjectManager");
    strcpy(g_warp_hooks[0].method, "OnRoundStart");
    sig = warp_hook_signature();
    g_warp_hooks[0].flags |= WARP_HF_FIRED;
    g_warp_hooks[0].actions ^= WARP_ACT_EVENT;
    assert(warp_hook_signature() == sig);
    g_warp_hooks[0].argc = 1;
    assert(warp_hook_signature() != sig);
    g_warp_hooks[0].argc = 0;
    g_warp_hooks[0].actions = 0;
    puts("PASS signature ignores FIRED/live actions, detects entry ABI changes");
}
static void test_hooks(void)
{
    unsigned long long (*volatile fn)(void *, void *) = target_int;
    float (*volatile ff)(void *, void *) = target_float;
    typedef unsigned long long (*nine_fn)(void *,void *,void *,void *,void *,
        void *,void *,void *,void *,void *,void *);
    nine_fn volatile f9 = target_nine;
    void *original;
    MEMORY_BASIC_INFORMATION mb;
    int i;
    assert(warp_bind_hook(0, (void *)target_int, 0));
    original = g_slots[0].original;
    assert(fn((void *)7, (void *)13) == (7 ^ 13 ^ sentinel));
    assert(!warp_bind_hook(1, (void *)target_int, 0)); /* no double hook */
    for (i = 0; i < 20; i++) {
        warp_uninstall();
        assert(g_slots[0].original == original);
        assert(VirtualQuery(original, &mb, sizeof(mb)) && mb.State == MEM_COMMIT);
        assert(fn((void *)7, (void *)13) == (7 ^ 13 ^ sentinel));
        /* Simulate a thread already inside the detour when disable happened. */
        assert(((unsigned long long (*)(void *,void *))warp_pick_thunk(0, 0))
               ((void *)7,(void *)13) == (7 ^ 13 ^ sentinel));
        assert(warp_bind_hook(5, (void *)target_int, 0));
        assert(g_slots[0].original == original && g_slots[0].hook_index == 5);
        assert(fn((void *)7, (void *)13) == (7 ^ 13 ^ sentinel));
    }
    g_warp_hooks[1].ret_kind = WARP_RET_FLOAT;
    assert(warp_bind_hook(1, (void *)target_float, 0));
    assert(ff((void *)7,(void *)13) == 20.25f);
    assert(warp_bind_hook(2, (void *)target_nine, 9));
    assert(f9((void *)1,(void *)2,(void *)3,(void *)4,(void *)5,(void *)6,
              (void *)7,(void *)8,(void *)9,(void *)10,(void *)11) == 441);
    warp_uninstall();
    assert(((float (*)(void *,void *))warp_pick_thunk(1, 0))
           ((void *)7,(void *)13) == 20.25f);
    puts("PASS real MinHook: 20 reloads, stable trampoline, row migration, no double hook");
    puts("PASS return ABI: 64-bit integer/pointer, float, nine args and hidden MethodInfo");
}
static void test_commands(void)
{
    HANDLE threads[8];
    HANDLE old_thread, old_event;
    void *old_veh;
    int i;
    warp_work_stop(); /* safe before start */
    entered = CreateEventW(NULL, TRUE, FALSE, NULL);
    resume_job = CreateEventW(NULL, TRUE, FALSE, NULL);
    assert(entered && resume_job);
    g_ic.string_new = fake_string;
    g_ic.gchandle_new = fake_new;
    g_ic.gchandle_free = fake_free;
    warp_work_start();
    assert(s_work_thread && s_work_ev && s_work_cs_ready);
    strcpy(g_hdr->cmd_text, "first");
    g_hdr->cmd_type = WARP_CMD_PACK(WARP_CMD_STR, 0, 0, 0);
    g_hdr->cmd_seq = 1;
    for (i = 0; i < 8; i++) threads[i] = CreateThread(NULL, 0, pump_thread, NULL, 0, NULL);
    assert(WaitForMultipleObjects(8, threads, TRUE, 10000) == WAIT_OBJECT_0);
    for (i = 0; i < 8; i++) CloseHandle(threads[i]);
    assert(WaitForSingleObject(entered, 1000) == WAIT_OBJECT_0);
    assert(strings == 1 && g_hdr->cmd_ack == 1 && g_hdr->cmd_result == WARP_CMD_RES_BUSY);
    /* A second sequence while worker is running cannot overwrite its job/result. */
    g_hdr->cmd_seq = 2;
    warp_pump_commands();
    assert(g_hdr->cmd_ack == 1 && strings == 1);
    old_thread = s_work_thread; old_event = s_work_ev; old_veh = s_veh;
    warp_work_stop(); /* times out because fake_string is deliberately blocked */
    assert(s_work_thread == old_thread && s_work_ev == old_event && s_veh == old_veh);
    assert(s_work_cs_ready && WaitForSingleObject(s_work_thread, 0) == WAIT_TIMEOUT);
    SetEvent(resume_job);
    wait_result();
    warp_work_stop();
    assert(!s_work_thread && !s_work_ev && !s_veh && !s_work_cs_ready);
    warp_work_stop(); /* idempotent */
    g_hdr->cmd_type = WARP_CMD_PACK(WARP_CMD_RELEASE,0,0,0);
    warp_pump_commands();
    /* RELEASE runs on the pump: it clears the object, but deliberately leaves
     * GC cleanup to a later worker put (never free a GC handle on game thread). */
    assert(frees == 0 && !s_cmd_busy && g_hdr->cmd_ack == 2);
    assert(warp_slot_get(0) == NULL);
    warp_pump_commands();
    assert(frees == 0);
    warp_slot_put(0, (void *)sentinel, 1);
    assert(frees == 1 && g_gc_handles[0] == sentinel);
    warp_slot_put(0, NULL, 1);
    assert(frees == 2 && g_gc_handles[0] == 0);
    CloseHandle(entered); CloseHandle(resume_job);
    puts("PASS commands: 8 concurrent pumps, exactly once, BUSY before ack, reentrant release");
    puts("PASS worker: stop-before-start, blocked-stop retains resources, repeated stop safe");
}
static int invoke_calls, ctor_calls, direct_calls, expect_null_ref;
static unsigned char string_object[40], constructed_object[32], boxed_int[24];
static void *call_method[1], *ctor_method[1];
static void *abi_method(void *klass, const char *name, int argc) {
    assert(klass == (void *)2 && argc == 5);
    if (!strcmp(name, ".ctor")) return ctor_method;
    assert(!strcmp(name, "LoadBank"));
    return call_method;
}
static void *abi_object_new(void *klass) {
    assert(klass == (void *)2);
    return constructed_object;
}
static void *abi_runtime_invoke(void *method, void *obj, void **params, void **exc) {
    assert(method == call_method || method == ctor_method);
    assert(params[0] == (expect_null_ref ? NULL : string_object));
    assert(params[1] && *(int *)params[1] == 0);
    assert(params[2] && *(int *)params[2] == 1);
    assert(params[3] && *(float *)params[3] == 1.25f);
    assert(params[4] == (char *)g_hdr + WARP_CMD_BUF_OFFSET + 16);
    *(int *)params[4] = 1234; /* out-buffer remains writable */
    assert(exc && !*exc);
    if (method == ctor_method) {
        assert(obj == constructed_object);
        ctor_calls++;
    } else {
        assert(obj == (void *)sentinel);
        invoke_calls++;
    }
    *(int *)(boxed_int + 16) = 73;
    return boxed_int;
}
static void *abi_direct(void *self, void *text, void *samples, void *nonblock, void *mi) {
    assert(self == (void *)sentinel && text == string_object);
    /* Existing direct ABI loads pointer-sized storage for integer arguments;
     * only low 32 bits are part of these bool/int values. */
    assert((uint32_t)(uintptr_t)samples == 0);
    assert((uint32_t)(uintptr_t)nonblock == 1);
    assert(mi == call_method);
    direct_calls++;
    return (void *)73;
}
static void test_invoke_abi(void) {
    WARP_IC saved = g_ic;
    char kinds[6] = {WARP_CMD_ARG_P, WARP_CMD_ARG_I, WARP_CMD_ARG_I,
                     WARP_CMD_ARG_F, WARP_CMD_ARG_M};
    void *params[6] = {0}, *pval[6] = {0};
    int ival[6] = {0};
    float fval[6] = {0};
    long long bits = 0;
    float xf = 0;
    void *ref = NULL;
    memset(&g_ic, 0, sizeof(g_ic));
    g_ic.domain_get_assemblies = static_assemblies;
    g_ic.assembly_get_image = static_image;
    g_ic.class_from_name = static_class;
    g_ic.class_get_method_from_name = abi_method;
    g_ic.object_new = abi_object_new;
    g_ic.runtime_invoke = abi_runtime_invoke;
    call_method[0] = (void *)abi_direct;
    warp_slot_put(24, string_object, 0);
    warp_slot_put(25, (void *)sentinel, 0);
    g_hdr->vars[0] = 24;
    g_hdr->vars[1] = 0;
    g_hdr->vars[2] = 1;
    fval[0] = 1.25f;
    memcpy(&g_hdr->vars[3], &fval[0], 4);
    g_hdr->vars[4] = 16;
    assert(warp_cmd_call(5, 25, WARP_CMD_RET_INT32, -1,
                        "SoundManager::LoadBank#piifm~i") == WARP_CMD_RES_OK);
    assert(invoke_calls == 1 && g_hdr->vars[6] == 73);
    assert(*(int *)(map_bytes + WARP_CMD_BUF_OFFSET + 16) == 1234);
    /* Null references are objects too: NULL, not an address containing NULL. */
    expect_null_ref = 1;
    warp_slot_put(24, NULL, 0);
    assert(warp_cmd_call(5, 25, WARP_CMD_RET_INT32, -1,
                        "SoundManager::LoadBank#piifm~i") == WARP_CMD_RES_OK);
    assert(invoke_calls == 2);
    expect_null_ref = 0;
    warp_slot_put(24, string_object, 0);
    strcpy(g_hdr->cmd_text, "SoundManager#piifm");
    assert(warp_cmd_make(5, 27, g_hdr->cmd_text) == WARP_CMD_RES_OK);
    assert(ctor_calls == 1 && warp_slot_get(27) == constructed_object);
    /* Check the unchanged direct packing, then execute the real direct bridge. */
    assert(warp_cmd_build_params(3, kinds, params, ival, fval, pval) == 0);
    assert(params[0] == &pval[0] && *(void **)params[0] == string_object);
    assert(params[1] == &ival[1] && params[2] == &ival[2]);
    assert(warp_direct_call(call_method, (void *)sentinel, params, 3,
                           WARP_CMD_RET_INT32, &bits, &xf, &ref) == 0);
    assert(direct_calls == 1 && bits == 73 && invoke_calls == 2);
    g_ic = saved;
    puts("PASS invoke ABI: string object, null reference, bool/int/float addresses, out buffer, boxed return");
    puts("PASS ctor runtime_invoke ABI and actual direct-call packing compatibility");
}

int main(void)
{
    setvbuf(stdout, NULL, _IONBF, 0);
    g_hdr = (WARP_HEADER *)map_bytes;
    g_warp_hooks = (WARP_HOOK *)(map_bytes + WARP_HOOK_OFFSET);
    assert(warp_mh_ensure());
    test_signature();
    test_hooks();
    test_commands();
    test_static_runtime();
    test_invoke_abi();
    puts("ALL native regressions passed");
    return 0;
}