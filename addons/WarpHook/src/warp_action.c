/* warp_action.c —— 钩子命中后的行为：挑台词、执行动作
 *
 * 由 warp_host.c 拆分而来（原第 639-834 行）。
 */
#include "warp_internal.h"

/* ------------------------------------------------------------------ */
/* 行为执行                                                            */
/* ------------------------------------------------------------------ */

/* 从第 base 句开始挑一句非空文案。
 *
 * 多个插件共用一块宿主映射时，各自的文案在池子里是连续的一段，
 * 段与段之间留一个空槽做分隔（写配置的 Python 侧就是这么排的）。
 * 所以这里从 base 往后扫，遇到空槽就认为本段结束 —— 不能全池乱挑，
 * 否则 AutoBoom 的爆炸提示会挑到抽卡台词。 */
const char *warp_pick_text(int base)
{
    int used = 0;

    if (!g_texts)
        return NULL;
    /* base 越界说明写配置的一方把文案段排到了池子外面。这时候宁可没有台词，
     * 也不能回落到 0 —— 否则 AutoBoom 会挑到 NoGacha 的抽卡台词。 */
    if (base < 0 || base >= WARP_MAX_TEXTS)
        return NULL;
    while (base < WARP_MAX_TEXTS && used < WARP_MAX_TEXTS) {
        if (!g_texts[base * WARP_TEXT_SIZE])
            break;
        used++;
        base++;
    }
    if (!used)
        return NULL;

    base -= used;
    return g_texts + (base + (int)(warp_rand() % (unsigned)used)) * WARP_TEXT_SIZE;
}

void warp_fire(int hook_index)
{
    WARP_HOOK *h;
    const char *text;

    if (!g_warp_hooks || hook_index < 0 || hook_index >= WARP_MAX_HOOKS)
        return;
    h = &g_warp_hooks[hook_index];

    text = warp_pick_text(h->text_base);
    warp_log("fire actions", (int)h->actions);

    /* 弹窗与面板都只能主线程做，而这里本来就在钩子回调里，安全 */
    if (h->actions & WARP_ACT_POPUP) {
        if (warp_show_popup(text))
            InterlockedIncrement((LONG *)&g_hdr->fired);
    }
    if (h->actions & WARP_ACT_PANEL) {
        /* 自建 UI 由后续版本提供；暂退化为原版弹窗 */
        if (warp_show_popup(text))
            InterlockedIncrement((LONG *)&g_hdr->fired);
    }
    if (h->actions & WARP_ACT_KILL) {
        HANDLE t = CreateThread(NULL, 0, warp_kill_thread,
                                (LPVOID)(ULONG_PTR)(h->hold_ms > 0 ? h->hold_ms : 0),
                                0, NULL);
        if (t) {
            CloseHandle(t);
            InterlockedIncrement((LONG *)&g_hdr->fired);
        }
    }
}

/* 对参数对象调一个 0 参 getter，拿它的整数值（失败返回 0）。
 *
 * 用途：插件要按「参数对象的属性」而不是「参数本身」做判断时用，例如抽卡
 * 插件要区分「付费单抽」，就得先读 GachaPayment.GachaType。这个调用发生在
 * 游戏主线程的钩子回调里，与 Unity 的线程约束相容。 */
int warp_probe_int(const char *klass_name, const char *method_name, void *obj)
{
    void *klass, *method, *exc = NULL, *result;

    if (!obj || !g_domain || !g_ic.runtime_invoke)
        return 0;
    klass = warp_find_class(g_domain, klass_name);
    if (!klass)
        return 0;
    method = warp_find_method(klass, method_name, 0);
    if (!method)
        return 0;
    result = g_ic.runtime_invoke(method, obj, NULL, &exc);
    if (exc || !result)
        return 0;
    /* il2cpp 的 boxed int：对象头 16 字节之后才是值 */
    return *(int *)((char *)result + 16);
}

/* 通用事件分发：由各参数个数的 detour 调用。
 *
 * 返回值是位掩码：bit0 = 拦掉原函数（WARP_HF_BLOCK 且没被参数门放行），
 * bit1 = 本次要执行动作。拆成"先判定再执行"，是为了让 detour 能按参数
 * 决定放行 —— NoGacha 的「付费单抽不拦」就是靠 guard_index/guard_value。 */
/* 沿着一条读取链取值。返回 1 表示读到了，0 表示中途碰到空指针。
 *
 * 空指针在 il2cpp 里很常见（对象还没初始化、目标已销毁），所以这里一律
 * 静默返回 0，让上层保留上一次的值 —— 抛出或打印都会把游戏卡住。 */
static int warp_read_chain(const WARP_READ *r, void *self, int argc,
                           void *a1, void *a2, void *a3, int *out)
{
    void *p;
    int i;

    if (!r || !out)
        return 0;

    switch (r->arg) {
    case 0:  p = self; break;
    case 1:  p = a1;   break;
    case 2:  p = a2;   break;
    case 3:  p = a3;   break;
    default: return 0;
    }
    if (!p)
        return 0;

    for (i = 0; i < r->nsteps && i < WARP_READ_STEPS; i++) {
        p = (char *)p + r->off[i];
        if (r->deref[i]) {
            p = *(void **)p;
            if (!p)
                return 0;
        }
    }

    switch (r->kind) {
    case WARP_READ_FLOAT: {
        float f = *(float *)p;
        int bits;
        memcpy(&bits, &f, sizeof(bits));
        *out = bits;
        break;
    }
    case WARP_READ_BOOL:
        *out = (*(unsigned char *)p) ? 1 : 0;
        break;
    default:
        *out = *(int *)p;
        break;
    }
    return 1;
}

/* 把钩子声明的读链全跑一遍，结果写进 out[4]（事件的 a/b/c/d）。 */
static void warp_apply_reads(WARP_HOOK *h, void *self, int argc,
                             void *a1, void *a2, void *a3, int *out)
{
    const WARP_READ *table;
    int i;

    if (!h || !g_hdr || h->read_count <= 0)
        return;
    if (h->read_base < 0 || h->read_base >= WARP_READ_MAX)
        return;

    table = (const WARP_READ *)((char *)g_hdr + WARP_READ_OFFSET);
    for (i = 0; i < h->read_count && i < WARP_READ_MAX; i++) {
        const WARP_READ *r = &table[h->read_base + i];
        int slot = r->out;
        if (h->read_base + i >= WARP_READ_MAX)
            break;
        if (slot < 0 || slot > 3)
            continue;
        warp_read_chain(r, self, argc, a1, a2, a3, &out[slot]);
    }
}

/* 把这次命中装进环形队列。head 只增不减，槽位取模；写之前先保证不越过
 * tail 一圈，越了就把 tail 往前推（丢最旧的，dropped++）。
 * 全程只用 Interlocked，读侧（Python）只读 head 与槽内容，不会撕裂。 */
static void warp_emit_event(int hook_index, WARP_HOOK *h, void *self,
                            int argc, void *a1, void *a2, void *a3)
{
    int *ctrl;
    WARP_EVENT *slot;
    LONG head, tail;
    int index;
    int out[4];

    if (!g_hdr)
        return;

    ctrl = (int *)((char *)g_hdr + WARP_EV_CTRL_OFFSET);
    head = InterlockedIncrement((LONG *)&ctrl[0]) - 1;
    tail = ctrl[1];
    if (head - tail >= WARP_EVENT_COUNT)
        ctrl[1] = head - WARP_EVENT_COUNT + 1;

    index = (int)(head % WARP_EVENT_COUNT);
    slot = (WARP_EVENT *)((char *)g_hdr + WARP_EVENTS_OFFSET) + index;
    slot->id = h->event_id ? h->event_id : hook_index;
    slot->hook = hook_index;
    slot->tick = (int)GetTickCount();
    /* 默认放原始参数，配了读链就被读出来的值覆盖 —— 成就那类消费者要的是
     * 「伤害多少、剩多少血」，不是「第 2 个参数是个指针」。 */
    out[0] = argc > 0 ? (int)(intptr_t)a1 : 0;
    out[1] = argc > 1 ? (int)(intptr_t)a2 : 0;
    out[2] = argc > 2 ? (int)(intptr_t)a3 : 0;
    out[3] = g_hdr->vars[0];
    warp_apply_reads(h, self, argc, a1, a2, a3, out);
    slot->a = out[0];
    slot->b = out[1];
    slot->c = out[2];
    slot->d = out[3];
}

int warp_on_event(int hook_index, void *self, int argc,
                  void *a1, void *a2, void *a3)
{
    warp_pump_commands();
    WARP_HOOK *h;
    ULONGLONG now;
    LONG hits;
    int act = 0;

    if (!g_hdr || !g_warp_hooks)
        return 0;
    if (hook_index < 0 || hook_index >= WARP_MAX_HOOKS)
        return 0;

    h = &g_warp_hooks[hook_index];

    hits = InterlockedIncrement(&g_hit_count[hook_index]);
    InterlockedIncrement((LONG *)&g_hdr->evt_count);
    g_hdr->last_event = hook_index;
    h->reserved[0] = hits;

    /* 探针：先把参数对象的属性读进 vars[]，供下面的参数门使用 */
    if (h->probe_class[0] && h->probe_method[0] && argc > h->probe_index &&
        h->probe_slot >= 0 && h->probe_slot < WARP_VAR_COUNT) {
        void *obj = NULL;
        switch (h->probe_index) {
        case 0: obj = a1; break;
        case 1: obj = a2; break;
        case 2: obj = a3; break;
        default: obj = NULL; break;
        }
        g_hdr->vars[h->probe_slot] =
            warp_probe_int(h->probe_class, h->probe_method, obj);
    }

    /* 参数门：命中的值等于 guard_value 就彻底放行（不拦、不弹、不计数动作）。
     * guard_var >= 0 时比较 vars[] 里的探针结果，否则比较第 guard_index 个参数。 */
    {
        int has_value = 0;
        int watch = 0;

        if (h->guard_var >= 0 && h->guard_var < WARP_VAR_COUNT) {
            watch = g_hdr->vars[h->guard_var];
            has_value = 1;
        } else if (h->guard_index >= 0 && argc > h->guard_index) {
            switch (h->guard_index) {
            case 0: watch = (int)(intptr_t)a1; break;
            case 1: watch = (int)(intptr_t)a2; break;
            case 2: watch = (int)(intptr_t)a3; break;
            default: watch = 0; break;
            }
            has_value = 1;
        }
        if (has_value && watch == h->guard_value)
            return 0;
    }

    if (h->flags & WARP_HF_BLOCK) {
        act |= 0x1;
        /* reserved[1] 记「真的拦下来了多少次」：参数门放行的那次不计，
         * 插件在 Python 里靠它判断「这一单被我拦了，该说点什么」。 */
        InterlockedIncrement((LONG *)&h->reserved[1]);
    }

    /* 事件优先于行为：只要钩子声明了 ACT_EVENT 就入队，哪怕它同时什么都不做。
     * 成就、统计这类消费者要的就是「发生过什么」，不该和弹窗/拦截抢语义。 */
    if (h->actions & WARP_ACT_EVENT)
        warp_emit_event(hook_index, h, self, argc, a1, a2, a3);

    /* 没有行为位的纯旁观钩子（NoGacha 的 OpenGachaAlarmUI）只用来看参数与发事件，
     * 不弹窗、不刷新去重窗，免得把同一次操作里紧跟的拦截钩子挤掉。 */
    if ((h->actions & WARP_ACT_BEHAVIOR) == 0)
        return act;

    if (!g_hdr->enabled)
        return act;

    now = GetTickCount64();

    /* 只触发一次的钩子：已经打过了就不再进 */
    if ((h->flags & WARP_HF_ONCE) && (h->flags & WARP_HF_FIRED))
        return act;

    /* 触发前延迟：引擎就绪后 delay_ms 之内不动作（AutoBoom 的「初始化完成后再等几秒」） */
    if (h->delay_ms > 0 && g_hdr->boot_at &&
        now - g_hdr->boot_at < (ULONGLONG)h->delay_ms)
        return act;

    /* 同一回合多个钩子同时命中时只认第一个 */
    if (g_hdr->dedupe_ms > 0 && g_last_fire[hook_index] &&
        now - g_last_fire[hook_index] < (ULONGLONG)g_hdr->dedupe_ms)
        return act;
    g_last_fire[hook_index] = now;

    if (h->every > 1 && (hits % h->every) != 0)
        return act;
    if (h->chance > 0 && h->chance < 100) {
        if ((int)(warp_rand() % 100u) >= h->chance)
            return act;
    }

    if (h->flags & WARP_HF_ONCE)
        h->flags |= WARP_HF_FIRED;

    return act | 0x2;
}

