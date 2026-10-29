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
 * v0.8 起 thunk 形状是 (self, a1..aN, mi)：把 MethodInfo* 也完整转发给原
 * 函数。il2cpp 方法真实签名的最后一个隐藏参数就是 MethodInfo*，老形状把它
 * 丢掉，六参以内是走运没崩（那些方法体不读 mi）；铁路 9 参构造的栈参数一
 * 多就不敢赌了，索性全部完整转发。
 *
 * 返回值按钩子声明的 ret_kind 取：int 返回在 RAX、float 返回在 XMM0，都按
 * 位模式带回 post 阶段直出事件格。BLOCK 的钩子拦下原函数，没有返回值可发。
 * 执行顺序仍是「先问要不要拦 → 按需调原函数 → 事件（POST 类）→ 再做动作」。*/
/* 把括号包住的六个参数摊开成逗号列表：EVT 作为整体传参时不会被内层逗号
 * 撕成多个宏参数。 */
#define WARP_EVT6(p1, p2, p3, p4, p5, p6) p1, p2, p3, p4, p5, p6

#define WARP_THUNK_DEF(N, n, DECL, EVT, CALL)                           \
    static void __fastcall warp_thunk##N##_##n DECL                     \
    {                                                                   \
        WARP_HOOK *h_ = warp_hook_at(n);                                \
        int act = warp_on_event(n, self, N, WARP_EVT6 EVT);             \
        int ret_ = 0;                                                   \
        if (!(act & 0x1) && g_slots[n].installed) {                     \
            if (h_ && h_->ret_kind == WARP_RET_FLOAT) {                 \
                float f_ = ((float (__fastcall *)DECL)g_slots[n].original) CALL; \
                __builtin_memcpy(&ret_, &f_, 4);                        \
            } else if (h_ && h_->ret_kind == WARP_RET_INT32) {          \
                ret_ = (int)((long long (__fastcall *)DECL)g_slots[n].original) CALL; \
            } else {                                                    \
                ((void (__fastcall *)DECL)g_slots[n].original) CALL;    \
            }                                                           \
            warp_on_event_post(n, h_, self, N, WARP_EVT6 EVT, ret_);    \
        }                                                               \
        if (act & 0x2) warp_fire(n);                                    \
        /* 声明了返回值类型的钩子，必须在离开前把值放回约定的寄存器：        \
         * int 在 RAX、float 在 XMM0。写在函数最后一步，后面没有代码再       \
         * 碰这两个寄存器。VOID 钩子不写 —— RAX/XMM0 原样透传 original      \
         * 留下的值，正是 void 签名一直能工作（没崩）的原因。 */             \
        if (h_ && h_->ret_kind == WARP_RET_INT32) {                     \
            __asm__ volatile("movl %0, %%eax" :: "r"(ret_) : "eax");    \
        } else if (h_ && h_->ret_kind == WARP_RET_FLOAT) {              \
            __asm__ volatile("movd %0, %%xmm0" :: "r"(ret_) : "xmm0");  \
        }                                                               \
    }

/* 4~6 个参数是给 `GetTakeAttackDmgMultiplier(unit, action, coin, attacker,
 * isCritical, info)` 这类方法留的：出手者（attacker）在第 4 个参数上，
 * 只有 a1..a3 的话「谁打的我」永远读不到。7~9 是铁路通关记录的九参构造。 */
#define WARP_THUNK_0(n) WARP_THUNK_DEF(0, n, (void *self, void *mi), \
    (NULL, NULL, NULL, NULL, NULL, NULL), (self, mi))
#define WARP_THUNK_1(n) WARP_THUNK_DEF(1, n, (void *self, void *a1, void *mi), \
    (a1, NULL, NULL, NULL, NULL, NULL), (self, a1, mi))
#define WARP_THUNK_2(n) WARP_THUNK_DEF(2, n, (void *self, void *a1, void *a2, void *mi), \
    (a1, a2, NULL, NULL, NULL, NULL), (self, a1, a2, mi))
#define WARP_THUNK_3(n) WARP_THUNK_DEF(3, n, (void *self, void *a1, void *a2, void *a3, void *mi), \
    (a1, a2, a3, NULL, NULL, NULL), (self, a1, a2, a3, mi))
#define WARP_THUNK_4(n) WARP_THUNK_DEF(4, n, (void *self, void *a1, void *a2, void *a3, void *a4, void *mi), \
    (a1, a2, a3, a4, NULL, NULL), (self, a1, a2, a3, a4, mi))
#define WARP_THUNK_5(n) WARP_THUNK_DEF(5, n, (void *self, void *a1, void *a2, void *a3, void *a4, void *a5, void *mi), \
    (a1, a2, a3, a4, a5, NULL), (self, a1, a2, a3, a4, a5, mi))
#define WARP_THUNK_6(n) WARP_THUNK_DEF(6, n, (void *self, void *a1, void *a2, void *a3, void *a4, void *a5, void *a6, void *mi), \
    (a1, a2, a3, a4, a5, a6), (self, a1, a2, a3, a4, a5, a6, mi))
#define WARP_THUNK_7(n) WARP_THUNK_DEF(7, n, (void *self, void *a1, void *a2, void *a3, void *a4, void *a5, void *a6, void *a7, void *mi), \
    (a1, a2, a3, a4, a5, a6), (self, a1, a2, a3, a4, a5, a6, a7, mi))
#define WARP_THUNK_8(n) WARP_THUNK_DEF(8, n, (void *self, void *a1, void *a2, void *a3, void *a4, void *a5, void *a6, void *a7, void *a8, void *mi), \
    (a1, a2, a3, a4, a5, a6), (self, a1, a2, a3, a4, a5, a6, a7, a8, mi))
#define WARP_THUNK_9(n) WARP_THUNK_DEF(9, n, (void *self, void *a1, void *a2, void *a3, void *a4, void *a5, void *a6, void *a7, void *a8, void *a9, void *mi), \
    (a1, a2, a3, a4, a5, a6), (self, a1, a2, a3, a4, a5, a6, a7, a8, a9, mi))

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

WARP_THUNK_4(0) WARP_THUNK_4(1) WARP_THUNK_4(2) WARP_THUNK_4(3)
WARP_THUNK_4(4) WARP_THUNK_4(5) WARP_THUNK_4(6) WARP_THUNK_4(7)
WARP_THUNK_4(8) WARP_THUNK_4(9) WARP_THUNK_4(10) WARP_THUNK_4(11)
WARP_THUNK_4(12) WARP_THUNK_4(13) WARP_THUNK_4(14) WARP_THUNK_4(15)

WARP_THUNK_5(0) WARP_THUNK_5(1) WARP_THUNK_5(2) WARP_THUNK_5(3)
WARP_THUNK_5(4) WARP_THUNK_5(5) WARP_THUNK_5(6) WARP_THUNK_5(7)
WARP_THUNK_5(8) WARP_THUNK_5(9) WARP_THUNK_5(10) WARP_THUNK_5(11)
WARP_THUNK_5(12) WARP_THUNK_5(13) WARP_THUNK_5(14) WARP_THUNK_5(15)

WARP_THUNK_6(0) WARP_THUNK_6(1) WARP_THUNK_6(2) WARP_THUNK_6(3)
WARP_THUNK_6(4) WARP_THUNK_6(5) WARP_THUNK_6(6) WARP_THUNK_6(7)
WARP_THUNK_6(8) WARP_THUNK_6(9) WARP_THUNK_6(10) WARP_THUNK_6(11)
WARP_THUNK_6(12) WARP_THUNK_6(13) WARP_THUNK_6(14) WARP_THUNK_6(15)

WARP_THUNK_7(0) WARP_THUNK_7(1) WARP_THUNK_7(2) WARP_THUNK_7(3)
WARP_THUNK_7(4) WARP_THUNK_7(5) WARP_THUNK_7(6) WARP_THUNK_7(7)
WARP_THUNK_7(8) WARP_THUNK_7(9) WARP_THUNK_7(10) WARP_THUNK_7(11)
WARP_THUNK_7(12) WARP_THUNK_7(13) WARP_THUNK_7(14) WARP_THUNK_7(15)

WARP_THUNK_8(0) WARP_THUNK_8(1) WARP_THUNK_8(2) WARP_THUNK_8(3)
WARP_THUNK_8(4) WARP_THUNK_8(5) WARP_THUNK_8(6) WARP_THUNK_8(7)
WARP_THUNK_8(8) WARP_THUNK_8(9) WARP_THUNK_8(10) WARP_THUNK_8(11)
WARP_THUNK_8(12) WARP_THUNK_8(13) WARP_THUNK_8(14) WARP_THUNK_8(15)

WARP_THUNK_9(0) WARP_THUNK_9(1) WARP_THUNK_9(2) WARP_THUNK_9(3)
WARP_THUNK_9(4) WARP_THUNK_9(5) WARP_THUNK_9(6) WARP_THUNK_9(7)
WARP_THUNK_9(8) WARP_THUNK_9(9) WARP_THUNK_9(10) WARP_THUNK_9(11)
WARP_THUNK_9(12) WARP_THUNK_9(13) WARP_THUNK_9(14) WARP_THUNK_9(15)

#define WARP_SEL_0(n) warp_thunk0_##n
#define WARP_SEL_1(n) warp_thunk1_##n
#define WARP_SEL_2(n) warp_thunk2_##n
#define WARP_SEL_3(n) warp_thunk3_##n
#define WARP_SEL_4(n) warp_thunk4_##n
#define WARP_SEL_5(n) warp_thunk5_##n
#define WARP_SEL_6(n) warp_thunk6_##n
#define WARP_SEL_7(n) warp_thunk7_##n
#define WARP_SEL_8(n) warp_thunk8_##n
#define WARP_SEL_9(n) warp_thunk9_##n

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
void *const g_thunks4[WARP_MAX_HOOKS] = {
    WARP_SEL_4(0), WARP_SEL_4(1), WARP_SEL_4(2), WARP_SEL_4(3),
    WARP_SEL_4(4), WARP_SEL_4(5), WARP_SEL_4(6), WARP_SEL_4(7),
    WARP_SEL_4(8), WARP_SEL_4(9), WARP_SEL_4(10), WARP_SEL_4(11),
    WARP_SEL_4(12), WARP_SEL_4(13), WARP_SEL_4(14), WARP_SEL_4(15),
};
void *const g_thunks5[WARP_MAX_HOOKS] = {
    WARP_SEL_5(0), WARP_SEL_5(1), WARP_SEL_5(2), WARP_SEL_5(3),
    WARP_SEL_5(4), WARP_SEL_5(5), WARP_SEL_5(6), WARP_SEL_5(7),
    WARP_SEL_5(8), WARP_SEL_5(9), WARP_SEL_5(10), WARP_SEL_5(11),
    WARP_SEL_5(12), WARP_SEL_5(13), WARP_SEL_5(14), WARP_SEL_5(15),
};
void *const g_thunks6[WARP_MAX_HOOKS] = {
    WARP_SEL_6(0), WARP_SEL_6(1), WARP_SEL_6(2), WARP_SEL_6(3),
    WARP_SEL_6(4), WARP_SEL_6(5), WARP_SEL_6(6), WARP_SEL_6(7),
    WARP_SEL_6(8), WARP_SEL_6(9), WARP_SEL_6(10), WARP_SEL_6(11),
    WARP_SEL_6(12), WARP_SEL_6(13), WARP_SEL_6(14), WARP_SEL_6(15),
};
void *const g_thunks7[WARP_MAX_HOOKS] = {
    WARP_SEL_7(0), WARP_SEL_7(1), WARP_SEL_7(2), WARP_SEL_7(3),
    WARP_SEL_7(4), WARP_SEL_7(5), WARP_SEL_7(6), WARP_SEL_7(7),
    WARP_SEL_7(8), WARP_SEL_7(9), WARP_SEL_7(10), WARP_SEL_7(11),
    WARP_SEL_7(12), WARP_SEL_7(13), WARP_SEL_7(14), WARP_SEL_7(15),
};
void *const g_thunks8[WARP_MAX_HOOKS] = {
    WARP_SEL_8(0), WARP_SEL_8(1), WARP_SEL_8(2), WARP_SEL_8(3),
    WARP_SEL_8(4), WARP_SEL_8(5), WARP_SEL_8(6), WARP_SEL_8(7),
    WARP_SEL_8(8), WARP_SEL_8(9), WARP_SEL_8(10), WARP_SEL_8(11),
    WARP_SEL_8(12), WARP_SEL_8(13), WARP_SEL_8(14), WARP_SEL_8(15),
};
void *const g_thunks9[WARP_MAX_HOOKS] = {
    WARP_SEL_9(0), WARP_SEL_9(1), WARP_SEL_9(2), WARP_SEL_9(3),
    WARP_SEL_9(4), WARP_SEL_9(5), WARP_SEL_9(6), WARP_SEL_9(7),
    WARP_SEL_9(8), WARP_SEL_9(9), WARP_SEL_9(10), WARP_SEL_9(11),
    WARP_SEL_9(12), WARP_SEL_9(13), WARP_SEL_9(14), WARP_SEL_9(15),
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
    case 4: return g_thunks4[index];
    case 5: return g_thunks5[index];
    case 6: return g_thunks6[index];
    case 7: return g_thunks7[index];
    case 8: return g_thunks8[index];
    case 9: return g_thunks9[index];
    default: return NULL;
    }
}
