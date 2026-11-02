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
        const int warp_n_ = (int)g_slots[n].hook_index;                 \
        WARP_HOOK *h_ = warp_n_ >= 0 ? warp_hook_at(warp_n_) : NULL;                                \
        int act = h_ ? warp_on_event(warp_n_, self, N, WARP_EVT6 EVT) : 0;             \
        unsigned long long ret_ = 0;                                    \
        RW                                                              \
        if (!(act & 0x1) && g_slots[n].original) {                     \
            if ((h_ ? h_->ret_kind : g_slots[n].ret_kind) == WARP_RET_FLOAT) {                 \
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
            warp_on_event_post(warp_n_, h_, self, N, WARP_EVT6 EVT, (int)ret_); \
        }                                                               \
        if (act & 0x2) warp_fire(warp_n_);                                    \
        /* 离开前无条件写回：int/bool/指针在 RAX（movq 保住 64 位指针），  \
         * float 在 XMM0。BLOCK 路径没调 original，写 0 = 「拦截未成功」。 */ \
        if ((h_ ? h_->ret_kind : g_slots[n].ret_kind) == WARP_RET_FLOAT) {                     \
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

/* thunk 表（argc 0..9 × WARP_MAX_HOOKS 槽）体积大且机械，交给脚本生成。 */
#include "warp_thunks.inc"

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
