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

/* v8：命中时按配置覆盖某个形参（改游戏自己要传进去的值）。
 * 取值只在共享内存的对象槽里看一眼，没有就直接返回 —— 不分配、不构造。 */
#define WARP_RW(k, v)                                                   \
    do {                                                                \
        void *rw_ = warp_rewrite_value(warp_n_, (k));                         \
        if (rw_) v = rw_;                                               \
    } while (0)

#define WARP_THUNK_DEF(N, n, DECL, EVT, CALL, RW)                           \
    static void __fastcall warp_thunk##N##_##n DECL                     \
    {                                                                   \
        WARP_HOOK *h_ = warp_hook_at(n);                                \
        const int warp_n_ = (n);                                        \
        int act = warp_on_event(n, self, N, WARP_EVT6 EVT);             \
        unsigned long long ret_ = 0;                                    \
        RW                                                              \
        if (!(act & 0x1) && g_slots[n].installed) {                     \
            if (h_ && h_->ret_kind == WARP_RET_FLOAT) {                 \
                float f_ = ((float (__fastcall *)DECL)g_slots[n].original) CALL; \
                __builtin_memcpy(&ret_, &f_, 4);                        \
            } else {                                                    \
                /* 一律按 64 位整数接住 RAX：int/bool/指针的返回值全从     \
                 * 这里走；VOID 方法的 RAX 没人读，写回去也无害。         \
                 * 不接住的话，下面的 warp_on_event_post 调用会把         \
                 * 它覆盖掉——真机实证：IsNodeCleared 永远返回假，        \
                 * 游戏把已通关的主线判成 1-11 未解锁（采光本上锁）。 */  \
                ret_ = (unsigned long long)((long long (__fastcall *)DECL)g_slots[n].original) CALL; \
            }                                                           \
            warp_on_event_post(n, h_, self, N, WARP_EVT6 EVT, (int)ret_); \
        }                                                               \
        if (act & 0x2) warp_fire(n);                                    \
        /* 离开前无条件写回：int/bool/指针在 RAX（movq 保住 64 位指针），  \
         * float 在 XMM0。BLOCK 路径没调 original，写 0 = 「拦截未成功」。 */ \
        if (h_ && h_->ret_kind == WARP_RET_FLOAT) {                     \
            __asm__ volatile("movd %0, %%xmm0" :: "r"(ret_) : "xmm0");  \
        } else {                                                        \
            __asm__ volatile("movq %0, %%rax" :: "r"(ret_) : "rax");    \
        }                                                               \
    }

/* 4~6 个参数是给 `GetTakeAttackDmgMultiplier(unit, action, coin, attacker,
 * isCritical, info)` 这类方法留的：出手者（attacker）在第 4 个参数上，
 * 只有 a1..a3 的话「谁打的我」永远读不到。7~9 是铁路通关记录的九参构造。 */
#define WARP_THUNK_0(n) WARP_THUNK_DEF(0, n, (void *self, void *mi), \
    (NULL, NULL, NULL, NULL, NULL, NULL), (self, mi), (void)warp_n_;)
#define WARP_THUNK_1(n) WARP_THUNK_DEF(1, n, (void *self, void *a1, void *mi), \
    (a1, NULL, NULL, NULL, NULL, NULL), (self, a1, mi), \
    WARP_RW(1, a1);)
#define WARP_THUNK_2(n) WARP_THUNK_DEF(2, n, (void *self, void *a1, void *a2, void *mi), \
    (a1, a2, NULL, NULL, NULL, NULL), (self, a1, a2, mi), \
    WARP_RW(1, a1); WARP_RW(2, a2);)
#define WARP_THUNK_3(n) WARP_THUNK_DEF(3, n, (void *self, void *a1, void *a2, void *a3, void *mi), \
    (a1, a2, a3, NULL, NULL, NULL), (self, a1, a2, a3, mi), \
    WARP_RW(1, a1); WARP_RW(2, a2); WARP_RW(3, a3);)
#define WARP_THUNK_4(n) WARP_THUNK_DEF(4, n, (void *self, void *a1, void *a2, void *a3, void *a4, void *mi), \
    (a1, a2, a3, a4, NULL, NULL), (self, a1, a2, a3, a4, mi), \
    WARP_RW(1, a1); WARP_RW(2, a2); WARP_RW(3, a3); WARP_RW(4, a4);)
#define WARP_THUNK_5(n) WARP_THUNK_DEF(5, n, (void *self, void *a1, void *a2, void *a3, void *a4, void *a5, void *mi), \
    (a1, a2, a3, a4, a5, NULL), (self, a1, a2, a3, a4, a5, mi), \
    WARP_RW(1, a1); WARP_RW(2, a2); WARP_RW(3, a3); WARP_RW(4, a4); WARP_RW(5, a5);)
#define WARP_THUNK_6(n) WARP_THUNK_DEF(6, n, (void *self, void *a1, void *a2, void *a3, void *a4, void *a5, void *a6, void *mi), \
    (a1, a2, a3, a4, a5, a6), (self, a1, a2, a3, a4, a5, a6, mi), \
    WARP_RW(1, a1); WARP_RW(2, a2); WARP_RW(3, a3); WARP_RW(4, a4); WARP_RW(5, a5); WARP_RW(6, a6);)
#define WARP_THUNK_7(n) WARP_THUNK_DEF(7, n, (void *self, void *a1, void *a2, void *a3, void *a4, void *a5, void *a6, void *a7, void *mi), \
    (a1, a2, a3, a4, a5, a6), (self, a1, a2, a3, a4, a5, a6, a7, mi), \
    WARP_RW(1, a1); WARP_RW(2, a2); WARP_RW(3, a3); WARP_RW(4, a4); WARP_RW(5, a5); WARP_RW(6, a6); WARP_RW(7, a7);)
#define WARP_THUNK_8(n) WARP_THUNK_DEF(8, n, (void *self, void *a1, void *a2, void *a3, void *a4, void *a5, void *a6, void *a7, void *a8, void *mi), \
    (a1, a2, a3, a4, a5, a6), (self, a1, a2, a3, a4, a5, a6, a7, a8, mi), \
    WARP_RW(1, a1); WARP_RW(2, a2); WARP_RW(3, a3); WARP_RW(4, a4); WARP_RW(5, a5); WARP_RW(6, a6); WARP_RW(7, a7); WARP_RW(8, a8);)
#define WARP_THUNK_9(n) WARP_THUNK_DEF(9, n, (void *self, void *a1, void *a2, void *a3, void *a4, void *a5, void *a6, void *a7, void *a8, void *a9, void *mi), \
    (a1, a2, a3, a4, a5, a6), (self, a1, a2, a3, a4, a5, a6, a7, a8, a9, mi), \
    WARP_RW(1, a1); WARP_RW(2, a2); WARP_RW(3, a3); WARP_RW(4, a4); WARP_RW(5, a5); WARP_RW(6, a6); WARP_RW(7, a7); WARP_RW(8, a8); WARP_RW(9, a9);)

WARP_THUNK_0(0)  WARP_THUNK_0(1)  WARP_THUNK_0(2)  WARP_THUNK_0(3)
WARP_THUNK_0(4)  WARP_THUNK_0(5)  WARP_THUNK_0(6)  WARP_THUNK_0(7)
WARP_THUNK_0(8)  WARP_THUNK_0(9)  WARP_THUNK_0(10) WARP_THUNK_0(11)
WARP_THUNK_0(12) WARP_THUNK_0(13) WARP_THUNK_0(14) WARP_THUNK_0(15)
WARP_THUNK_0(16)  WARP_THUNK_0(17)  WARP_THUNK_0(18)  WARP_THUNK_0(19)
WARP_THUNK_0(20)  WARP_THUNK_0(21)  WARP_THUNK_0(22)  WARP_THUNK_0(23)
WARP_THUNK_0(24)  WARP_THUNK_0(25)  WARP_THUNK_0(26)  WARP_THUNK_0(27)
WARP_THUNK_0(28)  WARP_THUNK_0(29)  WARP_THUNK_0(30)  WARP_THUNK_0(31)

WARP_THUNK_1(0)  WARP_THUNK_1(1)  WARP_THUNK_1(2)  WARP_THUNK_1(3)
WARP_THUNK_1(4)  WARP_THUNK_1(5)  WARP_THUNK_1(6)  WARP_THUNK_1(7)
WARP_THUNK_1(8)  WARP_THUNK_1(9)  WARP_THUNK_1(10) WARP_THUNK_1(11)
WARP_THUNK_1(12) WARP_THUNK_1(13) WARP_THUNK_1(14) WARP_THUNK_1(15)
WARP_THUNK_1(16)  WARP_THUNK_1(17)  WARP_THUNK_1(18)  WARP_THUNK_1(19)
WARP_THUNK_1(20)  WARP_THUNK_1(21)  WARP_THUNK_1(22)  WARP_THUNK_1(23)
WARP_THUNK_1(24)  WARP_THUNK_1(25)  WARP_THUNK_1(26)  WARP_THUNK_1(27)
WARP_THUNK_1(28)  WARP_THUNK_1(29)  WARP_THUNK_1(30)  WARP_THUNK_1(31)

WARP_THUNK_2(0)  WARP_THUNK_2(1)  WARP_THUNK_2(2)  WARP_THUNK_2(3)
WARP_THUNK_2(4)  WARP_THUNK_2(5)  WARP_THUNK_2(6)  WARP_THUNK_2(7)
WARP_THUNK_2(8)  WARP_THUNK_2(9)  WARP_THUNK_2(10) WARP_THUNK_2(11)
WARP_THUNK_2(12) WARP_THUNK_2(13) WARP_THUNK_2(14) WARP_THUNK_2(15)
WARP_THUNK_2(16)  WARP_THUNK_2(17)  WARP_THUNK_2(18)  WARP_THUNK_2(19)
WARP_THUNK_2(20)  WARP_THUNK_2(21)  WARP_THUNK_2(22)  WARP_THUNK_2(23)
WARP_THUNK_2(24)  WARP_THUNK_2(25)  WARP_THUNK_2(26)  WARP_THUNK_2(27)
WARP_THUNK_2(28)  WARP_THUNK_2(29)  WARP_THUNK_2(30)  WARP_THUNK_2(31)

WARP_THUNK_3(0)  WARP_THUNK_3(1)  WARP_THUNK_3(2)  WARP_THUNK_3(3)
WARP_THUNK_3(4)  WARP_THUNK_3(5)  WARP_THUNK_3(6)  WARP_THUNK_3(7)
WARP_THUNK_3(8)  WARP_THUNK_3(9)  WARP_THUNK_3(10) WARP_THUNK_3(11)
WARP_THUNK_3(12) WARP_THUNK_3(13) WARP_THUNK_3(14) WARP_THUNK_3(15)
WARP_THUNK_3(16)  WARP_THUNK_3(17)  WARP_THUNK_3(18)  WARP_THUNK_3(19)
WARP_THUNK_3(20)  WARP_THUNK_3(21)  WARP_THUNK_3(22)  WARP_THUNK_3(23)
WARP_THUNK_3(24)  WARP_THUNK_3(25)  WARP_THUNK_3(26)  WARP_THUNK_3(27)
WARP_THUNK_3(28)  WARP_THUNK_3(29)  WARP_THUNK_3(30)  WARP_THUNK_3(31)

WARP_THUNK_4(0) WARP_THUNK_4(1) WARP_THUNK_4(2) WARP_THUNK_4(3)
WARP_THUNK_4(4) WARP_THUNK_4(5) WARP_THUNK_4(6) WARP_THUNK_4(7)
WARP_THUNK_4(8) WARP_THUNK_4(9) WARP_THUNK_4(10) WARP_THUNK_4(11)
WARP_THUNK_4(12) WARP_THUNK_4(13) WARP_THUNK_4(14) WARP_THUNK_4(15)
WARP_THUNK_4(16)  WARP_THUNK_4(17)  WARP_THUNK_4(18)  WARP_THUNK_4(19)
WARP_THUNK_4(20)  WARP_THUNK_4(21)  WARP_THUNK_4(22)  WARP_THUNK_4(23)
WARP_THUNK_4(24)  WARP_THUNK_4(25)  WARP_THUNK_4(26)  WARP_THUNK_4(27)
WARP_THUNK_4(28)  WARP_THUNK_4(29)  WARP_THUNK_4(30)  WARP_THUNK_4(31)

WARP_THUNK_5(0) WARP_THUNK_5(1) WARP_THUNK_5(2) WARP_THUNK_5(3)
WARP_THUNK_5(4) WARP_THUNK_5(5) WARP_THUNK_5(6) WARP_THUNK_5(7)
WARP_THUNK_5(8) WARP_THUNK_5(9) WARP_THUNK_5(10) WARP_THUNK_5(11)
WARP_THUNK_5(12) WARP_THUNK_5(13) WARP_THUNK_5(14) WARP_THUNK_5(15)
WARP_THUNK_5(16)  WARP_THUNK_5(17)  WARP_THUNK_5(18)  WARP_THUNK_5(19)
WARP_THUNK_5(20)  WARP_THUNK_5(21)  WARP_THUNK_5(22)  WARP_THUNK_5(23)
WARP_THUNK_5(24)  WARP_THUNK_5(25)  WARP_THUNK_5(26)  WARP_THUNK_5(27)
WARP_THUNK_5(28)  WARP_THUNK_5(29)  WARP_THUNK_5(30)  WARP_THUNK_5(31)

WARP_THUNK_6(0) WARP_THUNK_6(1) WARP_THUNK_6(2) WARP_THUNK_6(3)
WARP_THUNK_6(4) WARP_THUNK_6(5) WARP_THUNK_6(6) WARP_THUNK_6(7)
WARP_THUNK_6(8) WARP_THUNK_6(9) WARP_THUNK_6(10) WARP_THUNK_6(11)
WARP_THUNK_6(12) WARP_THUNK_6(13) WARP_THUNK_6(14) WARP_THUNK_6(15)
WARP_THUNK_6(16)  WARP_THUNK_6(17)  WARP_THUNK_6(18)  WARP_THUNK_6(19)
WARP_THUNK_6(20)  WARP_THUNK_6(21)  WARP_THUNK_6(22)  WARP_THUNK_6(23)
WARP_THUNK_6(24)  WARP_THUNK_6(25)  WARP_THUNK_6(26)  WARP_THUNK_6(27)
WARP_THUNK_6(28)  WARP_THUNK_6(29)  WARP_THUNK_6(30)  WARP_THUNK_6(31)

WARP_THUNK_7(0) WARP_THUNK_7(1) WARP_THUNK_7(2) WARP_THUNK_7(3)
WARP_THUNK_7(4) WARP_THUNK_7(5) WARP_THUNK_7(6) WARP_THUNK_7(7)
WARP_THUNK_7(8) WARP_THUNK_7(9) WARP_THUNK_7(10) WARP_THUNK_7(11)
WARP_THUNK_7(12) WARP_THUNK_7(13) WARP_THUNK_7(14) WARP_THUNK_7(15)
WARP_THUNK_7(16)  WARP_THUNK_7(17)  WARP_THUNK_7(18)  WARP_THUNK_7(19)
WARP_THUNK_7(20)  WARP_THUNK_7(21)  WARP_THUNK_7(22)  WARP_THUNK_7(23)
WARP_THUNK_7(24)  WARP_THUNK_7(25)  WARP_THUNK_7(26)  WARP_THUNK_7(27)
WARP_THUNK_7(28)  WARP_THUNK_7(29)  WARP_THUNK_7(30)  WARP_THUNK_7(31)

WARP_THUNK_8(0) WARP_THUNK_8(1) WARP_THUNK_8(2) WARP_THUNK_8(3)
WARP_THUNK_8(4) WARP_THUNK_8(5) WARP_THUNK_8(6) WARP_THUNK_8(7)
WARP_THUNK_8(8) WARP_THUNK_8(9) WARP_THUNK_8(10) WARP_THUNK_8(11)
WARP_THUNK_8(12) WARP_THUNK_8(13) WARP_THUNK_8(14) WARP_THUNK_8(15)
WARP_THUNK_8(16)  WARP_THUNK_8(17)  WARP_THUNK_8(18)  WARP_THUNK_8(19)
WARP_THUNK_8(20)  WARP_THUNK_8(21)  WARP_THUNK_8(22)  WARP_THUNK_8(23)
WARP_THUNK_8(24)  WARP_THUNK_8(25)  WARP_THUNK_8(26)  WARP_THUNK_8(27)
WARP_THUNK_8(28)  WARP_THUNK_8(29)  WARP_THUNK_8(30)  WARP_THUNK_8(31)

WARP_THUNK_9(0) WARP_THUNK_9(1) WARP_THUNK_9(2) WARP_THUNK_9(3)
WARP_THUNK_9(4) WARP_THUNK_9(5) WARP_THUNK_9(6) WARP_THUNK_9(7)
WARP_THUNK_9(8) WARP_THUNK_9(9) WARP_THUNK_9(10) WARP_THUNK_9(11)
WARP_THUNK_9(12) WARP_THUNK_9(13) WARP_THUNK_9(14) WARP_THUNK_9(15)
WARP_THUNK_9(16)  WARP_THUNK_9(17)  WARP_THUNK_9(18)  WARP_THUNK_9(19)
WARP_THUNK_9(20)  WARP_THUNK_9(21)  WARP_THUNK_9(22)  WARP_THUNK_9(23)
WARP_THUNK_9(24)  WARP_THUNK_9(25)  WARP_THUNK_9(26)  WARP_THUNK_9(27)
WARP_THUNK_9(28)  WARP_THUNK_9(29)  WARP_THUNK_9(30)  WARP_THUNK_9(31)

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
    WARP_SEL_0(16), WARP_SEL_0(17), WARP_SEL_0(18), WARP_SEL_0(19),
    WARP_SEL_0(20), WARP_SEL_0(21), WARP_SEL_0(22), WARP_SEL_0(23),
    WARP_SEL_0(24), WARP_SEL_0(25), WARP_SEL_0(26), WARP_SEL_0(27),
    WARP_SEL_0(28), WARP_SEL_0(29), WARP_SEL_0(30), WARP_SEL_0(31),
};
void *const g_thunks1[WARP_MAX_HOOKS] = {
    WARP_SEL_1(0), WARP_SEL_1(1), WARP_SEL_1(2), WARP_SEL_1(3),
    WARP_SEL_1(4), WARP_SEL_1(5), WARP_SEL_1(6), WARP_SEL_1(7),
    WARP_SEL_1(8), WARP_SEL_1(9), WARP_SEL_1(10), WARP_SEL_1(11),
    WARP_SEL_1(12), WARP_SEL_1(13), WARP_SEL_1(14), WARP_SEL_1(15),
    WARP_SEL_1(16), WARP_SEL_1(17), WARP_SEL_1(18), WARP_SEL_1(19),
    WARP_SEL_1(20), WARP_SEL_1(21), WARP_SEL_1(22), WARP_SEL_1(23),
    WARP_SEL_1(24), WARP_SEL_1(25), WARP_SEL_1(26), WARP_SEL_1(27),
    WARP_SEL_1(28), WARP_SEL_1(29), WARP_SEL_1(30), WARP_SEL_1(31),
};
void *const g_thunks2[WARP_MAX_HOOKS] = {
    WARP_SEL_2(0), WARP_SEL_2(1), WARP_SEL_2(2), WARP_SEL_2(3),
    WARP_SEL_2(4), WARP_SEL_2(5), WARP_SEL_2(6), WARP_SEL_2(7),
    WARP_SEL_2(8), WARP_SEL_2(9), WARP_SEL_2(10), WARP_SEL_2(11),
    WARP_SEL_2(12), WARP_SEL_2(13), WARP_SEL_2(14), WARP_SEL_2(15),
    WARP_SEL_2(16), WARP_SEL_2(17), WARP_SEL_2(18), WARP_SEL_2(19),
    WARP_SEL_2(20), WARP_SEL_2(21), WARP_SEL_2(22), WARP_SEL_2(23),
    WARP_SEL_2(24), WARP_SEL_2(25), WARP_SEL_2(26), WARP_SEL_2(27),
    WARP_SEL_2(28), WARP_SEL_2(29), WARP_SEL_2(30), WARP_SEL_2(31),
};
void *const g_thunks3[WARP_MAX_HOOKS] = {
    WARP_SEL_3(0), WARP_SEL_3(1), WARP_SEL_3(2), WARP_SEL_3(3),
    WARP_SEL_3(4), WARP_SEL_3(5), WARP_SEL_3(6), WARP_SEL_3(7),
    WARP_SEL_3(8), WARP_SEL_3(9), WARP_SEL_3(10), WARP_SEL_3(11),
    WARP_SEL_3(12), WARP_SEL_3(13), WARP_SEL_3(14), WARP_SEL_3(15),
    WARP_SEL_3(16), WARP_SEL_3(17), WARP_SEL_3(18), WARP_SEL_3(19),
    WARP_SEL_3(20), WARP_SEL_3(21), WARP_SEL_3(22), WARP_SEL_3(23),
    WARP_SEL_3(24), WARP_SEL_3(25), WARP_SEL_3(26), WARP_SEL_3(27),
    WARP_SEL_3(28), WARP_SEL_3(29), WARP_SEL_3(30), WARP_SEL_3(31),
};
void *const g_thunks4[WARP_MAX_HOOKS] = {
    WARP_SEL_4(0), WARP_SEL_4(1), WARP_SEL_4(2), WARP_SEL_4(3),
    WARP_SEL_4(4), WARP_SEL_4(5), WARP_SEL_4(6), WARP_SEL_4(7),
    WARP_SEL_4(8), WARP_SEL_4(9), WARP_SEL_4(10), WARP_SEL_4(11),
    WARP_SEL_4(12), WARP_SEL_4(13), WARP_SEL_4(14), WARP_SEL_4(15),
    WARP_SEL_4(16), WARP_SEL_4(17), WARP_SEL_4(18), WARP_SEL_4(19),
    WARP_SEL_4(20), WARP_SEL_4(21), WARP_SEL_4(22), WARP_SEL_4(23),
    WARP_SEL_4(24), WARP_SEL_4(25), WARP_SEL_4(26), WARP_SEL_4(27),
    WARP_SEL_4(28), WARP_SEL_4(29), WARP_SEL_4(30), WARP_SEL_4(31),
};
void *const g_thunks5[WARP_MAX_HOOKS] = {
    WARP_SEL_5(0), WARP_SEL_5(1), WARP_SEL_5(2), WARP_SEL_5(3),
    WARP_SEL_5(4), WARP_SEL_5(5), WARP_SEL_5(6), WARP_SEL_5(7),
    WARP_SEL_5(8), WARP_SEL_5(9), WARP_SEL_5(10), WARP_SEL_5(11),
    WARP_SEL_5(12), WARP_SEL_5(13), WARP_SEL_5(14), WARP_SEL_5(15),
    WARP_SEL_5(16), WARP_SEL_5(17), WARP_SEL_5(18), WARP_SEL_5(19),
    WARP_SEL_5(20), WARP_SEL_5(21), WARP_SEL_5(22), WARP_SEL_5(23),
    WARP_SEL_5(24), WARP_SEL_5(25), WARP_SEL_5(26), WARP_SEL_5(27),
    WARP_SEL_5(28), WARP_SEL_5(29), WARP_SEL_5(30), WARP_SEL_5(31),
};
void *const g_thunks6[WARP_MAX_HOOKS] = {
    WARP_SEL_6(0), WARP_SEL_6(1), WARP_SEL_6(2), WARP_SEL_6(3),
    WARP_SEL_6(4), WARP_SEL_6(5), WARP_SEL_6(6), WARP_SEL_6(7),
    WARP_SEL_6(8), WARP_SEL_6(9), WARP_SEL_6(10), WARP_SEL_6(11),
    WARP_SEL_6(12), WARP_SEL_6(13), WARP_SEL_6(14), WARP_SEL_6(15),
    WARP_SEL_6(16), WARP_SEL_6(17), WARP_SEL_6(18), WARP_SEL_6(19),
    WARP_SEL_6(20), WARP_SEL_6(21), WARP_SEL_6(22), WARP_SEL_6(23),
    WARP_SEL_6(24), WARP_SEL_6(25), WARP_SEL_6(26), WARP_SEL_6(27),
    WARP_SEL_6(28), WARP_SEL_6(29), WARP_SEL_6(30), WARP_SEL_6(31),
};
void *const g_thunks7[WARP_MAX_HOOKS] = {
    WARP_SEL_7(0), WARP_SEL_7(1), WARP_SEL_7(2), WARP_SEL_7(3),
    WARP_SEL_7(4), WARP_SEL_7(5), WARP_SEL_7(6), WARP_SEL_7(7),
    WARP_SEL_7(8), WARP_SEL_7(9), WARP_SEL_7(10), WARP_SEL_7(11),
    WARP_SEL_7(12), WARP_SEL_7(13), WARP_SEL_7(14), WARP_SEL_7(15),
    WARP_SEL_7(16), WARP_SEL_7(17), WARP_SEL_7(18), WARP_SEL_7(19),
    WARP_SEL_7(20), WARP_SEL_7(21), WARP_SEL_7(22), WARP_SEL_7(23),
    WARP_SEL_7(24), WARP_SEL_7(25), WARP_SEL_7(26), WARP_SEL_7(27),
    WARP_SEL_7(28), WARP_SEL_7(29), WARP_SEL_7(30), WARP_SEL_7(31),
};
void *const g_thunks8[WARP_MAX_HOOKS] = {
    WARP_SEL_8(0), WARP_SEL_8(1), WARP_SEL_8(2), WARP_SEL_8(3),
    WARP_SEL_8(4), WARP_SEL_8(5), WARP_SEL_8(6), WARP_SEL_8(7),
    WARP_SEL_8(8), WARP_SEL_8(9), WARP_SEL_8(10), WARP_SEL_8(11),
    WARP_SEL_8(12), WARP_SEL_8(13), WARP_SEL_8(14), WARP_SEL_8(15),
    WARP_SEL_8(16), WARP_SEL_8(17), WARP_SEL_8(18), WARP_SEL_8(19),
    WARP_SEL_8(20), WARP_SEL_8(21), WARP_SEL_8(22), WARP_SEL_8(23),
    WARP_SEL_8(24), WARP_SEL_8(25), WARP_SEL_8(26), WARP_SEL_8(27),
    WARP_SEL_8(28), WARP_SEL_8(29), WARP_SEL_8(30), WARP_SEL_8(31),
};
void *const g_thunks9[WARP_MAX_HOOKS] = {
    WARP_SEL_9(0), WARP_SEL_9(1), WARP_SEL_9(2), WARP_SEL_9(3),
    WARP_SEL_9(4), WARP_SEL_9(5), WARP_SEL_9(6), WARP_SEL_9(7),
    WARP_SEL_9(8), WARP_SEL_9(9), WARP_SEL_9(10), WARP_SEL_9(11),
    WARP_SEL_9(12), WARP_SEL_9(13), WARP_SEL_9(14), WARP_SEL_9(15),
    WARP_SEL_9(16), WARP_SEL_9(17), WARP_SEL_9(18), WARP_SEL_9(19),
    WARP_SEL_9(20), WARP_SEL_9(21), WARP_SEL_9(22), WARP_SEL_9(23),
    WARP_SEL_9(24), WARP_SEL_9(25), WARP_SEL_9(26), WARP_SEL_9(27),
    WARP_SEL_9(28), WARP_SEL_9(29), WARP_SEL_9(30), WARP_SEL_9(31),
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
