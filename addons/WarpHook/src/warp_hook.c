/* warp_hook.c —— 钩子装配与卸载
 *
 * 由 warp_host.c 拆分而来（原第 835-940 行）。
 */
#include "warp_internal.h"

/* ------------------------------------------------------------------ */
/* 钩子装配                                                            */
/* ------------------------------------------------------------------ */

/* 每个钩子要有独立的 thunk，否则无法知道自己是谁。
 *
 * thunk 的顺序是「先问要不要拦 → 按需调原函数 → 再做动作」：
 * 弹窗必须在原函数之后（比如抽卡拦截要先确认真的没抽出去再告知），
 * 而拦截判定必须在原函数之前，否则拦不住。 */
#define WARP_THUNK_0(n) \
    static void __fastcall warp_thunk0_##n(void *self) { \
        int act = warp_on_event(n, self, 0, NULL, NULL, NULL); \
        if (g_slots[n].installed && !(act & 0x1)) { \
            ((void (__fastcall *)(void *))g_slots[n].original)(self); \
        } \
        if (act & 0x2) warp_fire(n); \
    }
#define WARP_THUNK_1(n) \
    static void __fastcall warp_thunk1_##n(void *self, void *a1) { \
        int act = warp_on_event(n, self, 1, a1, NULL, NULL); \
        if (g_slots[n].installed && !(act & 0x1)) { \
            ((void (__fastcall *)(void *, void *))g_slots[n].original)(self, a1); \
        } \
        if (act & 0x2) warp_fire(n); \
    }
#define WARP_THUNK_2(n) \
    static void __fastcall warp_thunk2_##n(void *self, void *a1, void *a2) { \
        int act = warp_on_event(n, self, 2, a1, a2, NULL); \
        if (g_slots[n].installed && !(act & 0x1)) { \
            ((void (__fastcall *)(void *, void *, void *))g_slots[n].original)(self, a1, a2); \
        } \
        if (act & 0x2) warp_fire(n); \
    }
#define WARP_THUNK_3(n) \
    static void __fastcall warp_thunk3_##n(void *self, void *a1, void *a2, void *a3) { \
        int act = warp_on_event(n, self, 3, a1, a2, a3); \
        if (g_slots[n].installed && !(act & 0x1)) { \
            ((void (__fastcall *)(void *, void *, void *, void *))g_slots[n].original)(self, a1, a2, a3); \
        } \
        if (act & 0x2) warp_fire(n); \
    }

WARP_THUNK_0(0)  WARP_THUNK_0(1)  WARP_THUNK_0(2)  WARP_THUNK_0(3)
WARP_THUNK_0(4)  WARP_THUNK_0(5)  WARP_THUNK_0(6)  WARP_THUNK_0(7)
WARP_THUNK_0(8)  WARP_THUNK_0(9)  WARP_THUNK_0(10) WARP_THUNK_0(11)
WARP_THUNK_0(12) WARP_THUNK_0(13) WARP_THUNK_0(14) WARP_THUNK_0(15)

WARP_THUNK_1(0)  WARP_THUNK_1(1)  WARP_THUNK_1(2)  WARP_THUNK_1(3)
WARP_THUNK_1(4)  WARP_THUNK_1(5)  WARP_THUNK_1(6)  WARP_THUNK_1(7)
WARP_THUNK_1(8)  WARP_THUNK_1(9)  WARP_THUNK_1(10) WARP_THUNK_1(11)
WARP_THUNK_1(12) WARP_THUNK_1(13) WARP_THUNK_1(14) WARP_THUNK_1(15)

WARP_THUNK_2(0)  WARP_THUNK_2(1)  WARP_THUNK_2(2)  WARP_THUNK_2(3)
WARP_THUNK_2(4)  WARP_THUNK_2(5)  WARP_THUNK_2(6)  WARP_THUNK_2(7)
WARP_THUNK_2(8)  WARP_THUNK_2(9)  WARP_THUNK_2(10) WARP_THUNK_2(11)
WARP_THUNK_2(12) WARP_THUNK_2(13) WARP_THUNK_2(14) WARP_THUNK_2(15)

WARP_THUNK_3(0)  WARP_THUNK_3(1)  WARP_THUNK_3(2)  WARP_THUNK_3(3)
WARP_THUNK_3(4)  WARP_THUNK_3(5)  WARP_THUNK_3(6)  WARP_THUNK_3(7)
WARP_THUNK_3(8)  WARP_THUNK_3(9)  WARP_THUNK_3(10) WARP_THUNK_3(11)
WARP_THUNK_3(12) WARP_THUNK_3(13) WARP_THUNK_3(14) WARP_THUNK_3(15)

#define WARP_SEL_0(n) warp_thunk0_##n
#define WARP_SEL_1(n) warp_thunk1_##n
#define WARP_SEL_2(n) warp_thunk2_##n
#define WARP_SEL_3(n) warp_thunk3_##n

void *const g_thunks0[WARP_MAX_HOOKS] = {
    WARP_SEL_0(0), WARP_SEL_0(1), WARP_SEL_0(2), WARP_SEL_0(3),
    WARP_SEL_0(4), WARP_SEL_0(5), WARP_SEL_0(6), WARP_SEL_0(7),
    WARP_SEL_0(8), WARP_SEL_0(9), WARP_SEL_0(10), WARP_SEL_0(11),
    WARP_SEL_0(12), WARP_SEL_0(13), WARP_SEL_0(14), WARP_SEL_0(15),
};
void *const g_thunks1[WARP_MAX_HOOKS] = {
    WARP_SEL_1(0), WARP_SEL_1(1), WARP_SEL_1(2), WARP_SEL_1(3),
    WARP_SEL_1(4), WARP_SEL_1(5), WARP_SEL_1(6), WARP_SEL_1(7),
    WARP_SEL_1(8), WARP_SEL_1(9), WARP_SEL_1(10), WARP_SEL_1(11),
    WARP_SEL_1(12), WARP_SEL_1(13), WARP_SEL_1(14), WARP_SEL_1(15),
};
void *const g_thunks2[WARP_MAX_HOOKS] = {
    WARP_SEL_2(0), WARP_SEL_2(1), WARP_SEL_2(2), WARP_SEL_2(3),
    WARP_SEL_2(4), WARP_SEL_2(5), WARP_SEL_2(6), WARP_SEL_2(7),
    WARP_SEL_2(8), WARP_SEL_2(9), WARP_SEL_2(10), WARP_SEL_2(11),
    WARP_SEL_2(12), WARP_SEL_2(13), WARP_SEL_2(14), WARP_SEL_2(15),
};
void *const g_thunks3[WARP_MAX_HOOKS] = {
    WARP_SEL_3(0), WARP_SEL_3(1), WARP_SEL_3(2), WARP_SEL_3(3),
    WARP_SEL_3(4), WARP_SEL_3(5), WARP_SEL_3(6), WARP_SEL_3(7),
    WARP_SEL_3(8), WARP_SEL_3(9), WARP_SEL_3(10), WARP_SEL_3(11),
    WARP_SEL_3(12), WARP_SEL_3(13), WARP_SEL_3(14), WARP_SEL_3(15),
};

void *warp_pick_thunk(int index, int argc)
{
    if (index < 0 || index >= WARP_MAX_HOOKS)
        return NULL;
    switch (argc) {
    case 0: return g_thunks0[index];
    case 1: return g_thunks1[index];
    case 2: return g_thunks2[index];
    case 3: return g_thunks3[index];
    default: return NULL;
    }
}


