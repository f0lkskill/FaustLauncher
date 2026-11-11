/* warp_hook.c —— 钩子装配与卸载
 *
 * 由 warp_host.c 拆分而来（原第 835-940 行）。
 */
#include "warp_internal.h"

/* ------------------------------------------------------------------ */
/* 分发链：一个游戏入口 → N 个订阅者                                     */
/* ------------------------------------------------------------------ */

/* MinHook 对同一个入口只能挂一次钩。以前第二条配置绑到同一方法时直接被拒
 * （warp_bind_hook 返回 0，日志里只有一句 "hook: bind failed"），多个插件
 * 想挂同一个函数时只有先到的那个真正生效（真机 2026-11-03 反馈）。
 *
 * 现在 thunk 自己就是总管：入口只装一次 detour，命中时按这条分发链把所有
 * 订阅者依次问一遍 —— 各跑各的参数门、探针、读链、事件、动作。参数改写
 * 按链序后写覆盖先写；block 取或（任一订阅者要拦就拦）；返回值按链上第一
 * 个声明了 ret_kind 的订阅者解释，所有订阅者都看得见同一个返回值。 */
int g_link_next[WARP_MAX_HOOKS];

int warp_slot_row_first(int slot)
{
    if (slot < 0 || slot >= WARP_MAX_HOOKS)
        return -1;
    return (int)g_slots[slot].hook_index;
}

int warp_slot_row_next(int slot, int row)
{
    if (slot < 0 || slot >= WARP_MAX_HOOKS || row < 0 || row >= WARP_MAX_HOOKS)
        return -1;
    return g_link_next[row];
}

/* 每个钩子要有独立的 thunk，否则无法知道自己是谁。
 *
 * v0.8 起 thunk 形状是 (self, a1..aN, mi)：把 MethodInfo* 也完整转发给原
 * 函数。il2cpp 方法真实签名的最后一个隐藏参数就是 MethodInfo*，老形状把它
 * 丢掉，六参以内是走运没崩（那些方法体不读 mi）；铁路 9 参构造的栈参数一
 * 多就不敢赌了，索性全部完整转发。
 *
 * 返回值按链上声明的 ret_kind 取：int 返回在 RAX、float 返回在 XMM0，都按
 * 位模式带回 post 阶段直出事件格。BLOCK 的钩子拦下原函数，没有返回值可发。
 * 执行顺序仍是「先问要不要拦 → 按需调原函数 → 事件（POST 类）→ 再做动作」。*/
/* 把括号包住的六个参数摊开成逗号列表：EVT 作为整体传参时不会被内层逗号
 * 撕成多个宏参数。 */
#define WARP_EVT6(p1, p2, p3, p4, p5, p6) p1, p2, p3, p4, p5, p6

/* v8：命中时按配置覆盖某个形参（改游戏自己要传进去的值）。
 * 取值只在共享内存的对象槽里看一眼，没有就跳过 —— 不分配、不构造。
 * 分发链上每个订阅者都轮一遍，后面的覆盖前面的。 */
#define WARP_RW(k, v)                                                   \
    do {                                                                \
        int rw_i_;                                                      \
        for (rw_i_ = warp_slot_row_first(slot_n_); rw_i_ >= 0;          \
             rw_i_ = warp_slot_row_next(slot_n_, rw_i_)) {              \
            void *rw_ = warp_rewrite_value(rw_i_, (k));                 \
            if (rw_) v = rw_;                                           \
        }                                                               \
    } while (0)

/* 按整数参数值做条件改写：argN_old != 0 且参数当前值相等时改成 argN_new。
 * 目前只给 6 参构造用（HttpEnterStageBattleCommand..ctor 的 sub/node/stage）。 */
#define WARP_ARG_REWRITE(a, v)                                          \
    do {                                                                \
        int ar_;                                                        \
        for (ar_ = warp_slot_row_first(slot_n_); ar_ >= 0;              \
             ar_ = warp_slot_row_next(slot_n_, ar_)) {                  \
            WARP_HOOK *h_ = warp_hook_at(ar_);                          \
            if (h_ && h_->arg##a##_old &&                              \
                (int)(intptr_t)(v) == h_->arg##a##_old)                \
                v = (void *)(intptr_t)h_->arg##a##_new;                 \
        }                                                               \
    } while (0)

#define WARP_THUNK_DEF(N, n, DECL, EVT, CALL, RW)                           \
    static void __fastcall warp_thunk##N##_##n DECL                     \
    {                                                                   \
        unsigned char fire_[WARP_MAX_HOOKS];                            \
        int nfire_ = 0;                                                 \
        int blocked_ = 0;                                               \
        int want_float_ = (g_slots[n].ret_kind == WARP_RET_FLOAT);      \
        unsigned long long ret_ = 0;                                    \
        const int slot_n_ = (n);                                        \
        int r_;                                                         \
        /* 第一遍：问遍所有订阅者，收 block / 动作 / 返回 ABI。 */        \
        for (r_ = warp_slot_row_first(n); r_ >= 0;                      \
             r_ = warp_slot_row_next(n, r_)) {                          \
            WARP_HOOK *h_ = warp_hook_at(r_);                           \
            int act_;                                                   \
            if (!h_)                                                    \
                continue;                                               \
            act_ = warp_on_event(r_, self, N, WARP_EVT6 EVT);           \
            if (act_ & 0x1) {                                           \
                blocked_ = 1;                                           \
                /* v15：拦截时写回配置的常量（默认 0 = 旧行为）。链上     \
                 * 多个订阅者按顺序覆盖，最后说话的那个说了算。 */        \
                ret_ = (unsigned long long)(long long)h_->ret_const;     \
            }                                                           \
            if (act_ & 0x2)                                             \
                fire_[nfire_++] = (unsigned char)r_;                    \
            if (h_->ret_kind == WARP_RET_FLOAT)                         \
                want_float_ = 1;                                        \
        }                                                               \
        RW                                                              \
        if (!blocked_ && g_slots[n].original) {                         \
            if (want_float_) {                                          \
                float f_ = ((float (__fastcall *)DECL)g_slots[n].original) CALL; \
                __builtin_memcpy(&ret_, &f_, 4);                        \
            } else {                                                    \
                /* 一律按 64 位整数接住 RAX：int/bool/指针的返回值全从       \
                 * 这里走；VOID 方法的 RAX 没人读，写回去也无害。           \
                 * 不接住的话，下面的 warp_on_event_post 调用会把           \
                 * 它覆盖掉——真机实证：IsNodeCleared 永远返回假，          \
                 * 游戏把已通关的主线判成 1-11 未解锁（采光本上锁）。 */    \
                ret_ = (unsigned long long)((long long (__fastcall *)DECL)g_slots[n].original) CALL; \
            }                                                           \
            for (r_ = warp_slot_row_first(n); r_ >= 0;                  \
                 r_ = warp_slot_row_next(n, r_)) {                      \
                WARP_HOOK *h_ = warp_hook_at(r_);                       \
                if (h_)                                                 \
                    warp_on_event_post(r_, h_, self, N, WARP_EVT6 EVT, (int)ret_); \
            }                                                           \
            for (r_ = warp_slot_row_first(n); r_ >= 0;                  \
                 r_ = warp_slot_row_next(n, r_)) {                      \
                WARP_HOOK *h_ = warp_hook_at(r_);                       \
                if (h_ && self && h_->write_self_off >= 0 &&            \
                    (h_->guard_self_off < 0 ||                          \
                     *(int *)((char *)self + h_->guard_self_off) ==     \
                     h_->guard_self_value))                             \
                    *(int *)((char *)self + h_->write_self_off) =       \
                        h_->write_self_value;                           \
            }                                                           \
        }                                                               \
        for (r_ = 0; r_ < nfire_; r_++)                                 \
            warp_fire((int)fire_[r_]);                                  \
        /* 离开前无条件写回：int/bool/指针在 RAX（movq 保住 64 位指针）， \
         * float 在 XMM0。BLOCK 路径没调 original，写回的是钩子配的          \
         * ret_const（默认 0）；VOID 方法的写回没人读，无害。 */          \
        if (want_float_) {                                              \
            __asm__ volatile("movd %0, %%xmm0" :: "r"(ret_) : "xmm0");  \
        } else {                                                        \
            __asm__ volatile("movq %0, %%rax" :: "r"(ret_) : "rax");    \
        }                                                               \
    }

/* 4~6 个参数是给 `GetTakeAttackDmgMultiplier(unit, action, coin, attacker,
 * isCritical, info)` 这类方法留的：出手者（attacker）在第 4 个参数上，
 * 只有 a1..a3 的话「谁打的我」永远读不到。7~9 是铁路通关记录的九参构造。 */
#define WARP_THUNK_0(n) WARP_THUNK_DEF(0, n, (void *self, void *mi), \
    (NULL, NULL, NULL, NULL, NULL, NULL), (self, mi), (void)slot_n_;)
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
    WARP_RW(1, a1); WARP_RW(2, a2); WARP_RW(3, a3); WARP_RW(4, a4); WARP_RW(5, a5); WARP_RW(6, a6); \
    WARP_ARG_REWRITE(2, a2); WARP_ARG_REWRITE(3, a3); WARP_ARG_REWRITE(4, a4);)
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
