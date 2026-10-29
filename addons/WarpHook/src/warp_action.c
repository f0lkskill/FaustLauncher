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
/* 对象槽区的起点。槽里存的是 void*，读侧可以按地址直接读。
 * 放在共享内存最后一段，所以基址就是 g_hdr 加固定偏移。
 * （warp_cmd.c 的对象构造也用同一张槽表，所以不再是 static。） */
void **warp_objects(void)
{
    if (!g_hdr)
        return NULL;
    return (void **)((char *)g_hdr + WARP_OBJECTS_OFFSET);
}

/* 读之前先问系统这段内存能不能读。
 *
 * 插件把偏移写错一个字节就会崩游戏 —— 真实发生过：把场景状态（0~15 的枚举）
 * 当成对象指针去解引用，游戏在注入的瞬间退出。读取链是插件写的东西，不能
 * 假设它一定对；宁可这一次读不到，也不能让宿主跟着一起死。 */
static int warp_can_read(const void *p, int size)
{
    MEMORY_BASIC_INFORMATION mbi;
    const char *cur;
    const char *end;

    if (!p || size <= 0)
        return 0;
    cur = (const char *)p;
    end = cur + size;
    while (cur < end) {
        SIZE_T span;
        if (!VirtualQuery(cur, &mbi, sizeof(mbi)))
            return 0;
        if (mbi.State != MEM_COMMIT)
            return 0;
        if (mbi.Protect & (PAGE_GUARD | PAGE_NOACCESS))
            return 0;
        if (!(mbi.Protect & (PAGE_READONLY | PAGE_READWRITE | PAGE_WRITECOPY |
                             PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE |
                             PAGE_EXECUTE_WRITECOPY)))
            return 0;
        span = (SIZE_T)((const char *)mbi.BaseAddress + mbi.RegionSize - cur);
        if (!span)
            return 0;
        cur += span;
    }
    return 1;
}

/* 值类型容器的一步：取第 off[i] 个 4 字节元素，值直接当位模式留在 p。
 *
 * 老链路遍历 List<int> 求铁路通关回合总和；引用类型步（2/3）读的是 8 字节
 * 指针，对 int 元素会把两个 int 拼成一个地址——必错。值类型元素的 stride
 * 是元素本身大小（这里只支持 4 字节），从 items + 0x20 起。 */
static int warp_step_value_element(int step, void **pp, int idx, int count)
{
    char *items;
    char *elem;

    if (step == WARP_STEP_LIST_VAL) {
        if (!warp_can_read(*pp, 0x20))
            return 0;
        items = *(char **)((char *)*pp + 0x10);   /* List<T>._items */
        count = *(int *)((char *)*pp + 0x18);     /* List<T>._size  */
    } else {
        items = (char *)*pp;
        count = *(int *)((char *)*pp + 0x18);     /* Array.max_length */
    }
    if (!items || idx < 0 || idx >= count)
        return 0;
    elem = items + 0x20 + idx * 4;
    if (!warp_can_read(elem, 4))
        return 0;
    *pp = (void *)(uintptr_t)*(int *)elem;
    return 1;
}

/* 落点是 List<4B 值类型>：把所有元素加起来（铁路通关回合总和）。
 * 元素个数做个 64K 的上限防呆——偏移写错时 count 可能是个大数，别真去读。 */
static int warp_sum_list_i32(const void *list, int *out)
{
    char *items;
    int count, i;
    int total = 0;

    if (!warp_can_read(list, 0x20))
        return 0;
    items = *(char **)((const char *)list + 0x10);
    count = *(int *)((const char *)list + 0x18);
    if (!items || count < 0 || count > 0x10000)
        return 0;
    if (count > 0 && !warp_can_read(items + 0x20, count * 4))
        return 0;
    for (i = 0; i < count; i++) {
        int v;
        memcpy(&v, items + 0x20 + i * 4, sizeof(v));
        total += v;
    }
    *out = total;
    return 1;
}

/* 落点是 List/Array：只取元素个数（读不到就当 0 个）。 */
static int warp_count_list(const void *p, int *out)
{
    int count;

    if (!warp_can_read(p, 0x20))
        return 0;
    count = *(const int *)((const char *)p + 0x18);
    *out = count > 0 ? count : 0;
    return 1;
}

/* 落点是 il2cpp string*：抽出数字字符拼成 int（UI 文本实际就是「86」这种）。
 * il2cpp string：+0x10 长度，+0x14 起是 UTF-16 字符。取前 9 位数字防溢出，
 * 与 Python 侧 _apply_railway_ui_text 的 digits 提取同一套规矩。 */
static int warp_text_number(const void *str, int *out)
{
    int len, i;
    long long value = 0;
    int digits = 0;

    if (!warp_can_read(str, 0x14))
        return 0;
    len = *(const int *)((const char *)str + 0x10);
    if (len <= 0 || len > 4096)
        return 0;
    if (!warp_can_read((const char *)str + 0x14, len * 2))
        return 0;
    for (i = 0; i < len && digits < 9; i++) {
        unsigned short ch;
        memcpy(&ch, (const char *)str + 0x14 + i * 2, sizeof(ch));
        if (ch >= '0' && ch <= '9') {
            value = value * 10 + (ch - '0');
            digits++;
        }
    }
    if (!digits)
        return 0;
    *out = (int)value;
    return 1;
}

/* 沿着一条读取链取值。返回 1 表示读到了，0 表示中途碰到空指针。
 *
 * 空指针在 il2cpp 里很常见（对象还没初始化、目标已销毁），所以这里一律
 * 静默返回 0，让上层保留上一次的值 —— 抛出或打印都会把游戏卡住。 */
static int warp_read_chain(const WARP_READ *r, void *self, int argc,
                           void *a1, void *a2, void *a3,
                           void *a4, void *a5, void *a6, int *out)
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
    case 4:  p = a4;   break;
    case 5:  p = a5;   break;
    case 6:  p = a6;   break;
    default: {
        /* 0x100 + n = 从第 n 个对象槽出发。槽里的指针是「上一次某个钩子命中时
         * 缓下来的」，此刻对象可能已经换了甚至销毁了 —— 后面每一步都会先问
         * warp_can_read，读到坏地址就当这次没读到。 */
        int slot;
        void **objs;

        if (r->arg < WARP_OBJ_ARG_BASE)
            return 0;
        slot = r->arg - WARP_OBJ_ARG_BASE;
        if (slot < 0 || slot >= WARP_OBJECT_COUNT)
            return 0;
        objs = warp_objects();
        p = objs ? objs[slot] : NULL;
        break;
    }
    }
    if (!p)
        return 0;

    if (r->nsteps <= 0) {
        /* 0 跳 = 这个参数本身就是值/容器，不是指针。
         *
         * 关卡状态查询那类钩子的签名是 (self, int main, int sub, int node)，
         * 三个参数都是值类型，直接躺在寄存器/栈上，没有任何偏移可跟。老链路
         * 为它们单独写了 thunk；这里用「空链」表达同一件事：不往前走，就把
         * 参数当结果。聚合类 kind（求和/计数/文本）的落点是容器本身，参数
         * 直接就是 List* / string*，同样零跳可达。 */
        if (r->kind == WARP_READ_SUM_LIST)
            return warp_sum_list_i32(p, out);
        if (r->kind == WARP_READ_COUNT_LIST)
            return warp_count_list(p, out);
        if (r->kind == WARP_READ_TEXT_NUM)
            return warp_text_number(p, out);
        *out = (int)(size_t)p;
        return 1;
    }

    for (i = 0; i < r->nsteps && i < WARP_READ_STEPS; i++) {
        int step = r->deref[i];

        if (step == WARP_STEP_LIST_VAL || step == WARP_STEP_ARRAY_VAL) {
            /* 值类型容器一步：取第 off[i] 个 4 字节元素，值本身留在 p。
             * 后面如果还有步骤，就把这个值当普通整数继续加偏移。 */
            if (!warp_step_value_element(step, &p, r->off[i], 0))
                return 0;
            continue;
        }

        if (step == WARP_STEP_LIST || step == WARP_STEP_ARRAY) {
            /* 容器一步：把 p 当成容器，取第 off[i] 个元素。元素按引用类型处理
             * （成就关心的单位/模型都是 class）；4 字节值类型元素走 4/5。 */
            void *arr;
            int count, idx = r->off[i];

            if (!warp_can_read(p, 0x20))
                return 0;
            if (step == WARP_STEP_LIST) {
                arr = *(void **)((char *)p + 0x10);      /* List<T>._items */
                count = *(int *)((char *)p + 0x18);      /* List<T>._size  */
            } else {
                arr = p;
                count = *(int *)((char *)p + 0x18);      /* Array.max_length */
            }
            if (!arr || idx < 0 || idx >= count)
                return 0;
            if (!warp_can_read((char *)arr + 0x20 + idx * (int)sizeof(void *),
                               (int)sizeof(void *)))
                return 0;
            p = *(void **)((char *)arr + 0x20 + idx * (int)sizeof(void *));
            if (!p)
                return 0;
            continue;
        }

        p = (char *)p + r->off[i];
        if (step) {
            if (!warp_can_read(p, (int)sizeof(void *)))
                return 0;
            p = *(void **)p;
            if (!p)
                return 0;
        }
    }

    /* 聚合类 kind 在链的**中途**就决定了：落点是容器本身而不是容器里的元素，
     * 所以只要零跳或普通步走到 List*，剩下的就是求和/计数，不再走落点解释。 */
    if (r->kind == WARP_READ_SUM_LIST || r->kind == WARP_READ_COUNT_LIST ||
        r->kind == WARP_READ_TEXT_NUM) {
        if (r->kind == WARP_READ_SUM_LIST)
            return warp_sum_list_i32(p, out);
        if (r->kind == WARP_READ_COUNT_LIST)
            return warp_count_list(p, out);
        return warp_text_number(p, out);
    }

    if (!warp_can_read(p, 16))
        return 0;

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
    case WARP_READ_OBSCURED: {
        /* ObscuredInt { int key; int hidden; int fake; } → 值 = hidden ^ key */
        int key = 0, hidden = 0;
        memcpy(&key, p, sizeof(key));
        memcpy(&hidden, (char *)p + 4, sizeof(hidden));
        *out = hidden ^ key;
        break;
    }
    default:
        *out = *(int *)p;
        break;
    }
    return 1;
}

/* 把钩子声明的读链全跑一遍，结果写进 out[4]（事件的 a/b/c/d）。 */
static void warp_apply_reads(WARP_HOOK *h, void *self, int argc,
                             void *a1, void *a2, void *a3,
                             void *a4, void *a5, void *a6, int *out)
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
        if (slot < 0 || slot >= WARP_EVENT_SLOTS)
            continue;
        warp_read_chain(r, self, argc, a1, a2, a3, a4, a5, a6, &out[slot]);
    }
}

/* 把这次命中装进环形队列。head 只增不减，槽位取模；写之前先保证不越过
 * tail 一圈，越了就把 tail 往前推（丢最旧的，dropped++）。
 * 全程只用 Interlocked，读侧（Python）只读 head 与槽内容，不会撕裂。
 * ret 是原函数返回值的位模式（ret_kind==VOID 时无意义）。 */
static void warp_emit_event(int hook_index, WARP_HOOK *h, void *self,
                            int argc, void *a1, void *a2, void *a3,
                            void *a4, void *a5, void *a6, int ret)
{
    int *ctrl;
    WARP_EVENT *slot;
    LONG head, tail;
    int index;
    int out[WARP_EVENT_SLOTS];
    int i;

    if (!g_hdr)
        return;

    /* 默认放原始参数，配了读链就被读出来的值覆盖 —— 成就那类消费者要的是
     * 「伤害多少、剩多少血」，不是「第 2 个参数是个指针」。 */
    out[0] = argc > 0 ? (int)(intptr_t)a1 : 0;
    out[1] = argc > 1 ? (int)(intptr_t)a2 : 0;
    out[2] = argc > 2 ? (int)(intptr_t)a3 : 0;
    out[3] = argc > 3 ? (int)(intptr_t)a4 : g_hdr->vars[0];
    for (i = 4; i < WARP_EVENT_SLOTS; i++)
        out[i] = 0;
    /* 返回值直出：读返回值这类钩子的主值就在寄存器里，直写一格比配读链省事。
     * ret_slot 与读链写同一格时读链会覆盖它 —— 配置侧别这么写。 */
    if (h->ret_kind != WARP_RET_VOID && h->ret_slot >= 0 &&
        h->ret_slot < WARP_EVENT_SLOTS)
        out[h->ret_slot] = ret;
    /* 先落对象槽，再跑读链：同一条钩子既想「记住这个对象」又想「顺手读两个值」
     * 的时候，读链可以直接写 arg=0x100+槽号 走刚缓存下来的指针。 */
    if (h->cache_arg >= 0 && h->cache_slot >= 0 && h->cache_slot < WARP_OBJECT_COUNT) {
        void **objs = warp_objects();
        void *cached = NULL;

        switch (h->cache_arg) {
        case 0:  cached = self; break;
        case 1:  cached = a1;   break;
        case 2:  cached = a2;   break;
        case 3:  cached = a3;   break;
        case 4:  cached = a4;   break;
        case 5:  cached = a5;   break;
        case 6:  cached = a6;   break;
        default: break;
        }
        if (objs && cached)
            warp_slot_put(h->cache_slot, cached, 0);
    }

    warp_apply_reads(h, self, argc, a1, a2, a3, a4, a5, a6, out);

    /* 值没变就不入队。必须先跑完读链才知道变没变，所以这段在自增 head 之前：
     * 先占槽位再判断的话，被吞掉的那条会在环形队列里留个空洞。
     * 只对「开了去重位又确实配了读链」的钩子生效 —— 没配读链时 out[] 装的是
     * 参数指针，每次都不一样，去重等于没做。 */
    if ((h->flags & WARP_HF_DEDUPE) && h->read_count > 0) {
        int same = g_last_valid[hook_index];

        for (i = 0; i < WARP_EVENT_SLOTS; i++) {
            if (g_last_vals[hook_index][i] != out[i]) {
                same = 0;
                break;
            }
        }
        if (same)
            return;
        for (i = 0; i < WARP_EVENT_SLOTS; i++)
            g_last_vals[hook_index][i] = out[i];
        g_last_valid[hook_index] = 1;
    }

    ctrl = (int *)((char *)g_hdr + WARP_EV_CTRL_OFFSET);
    head = InterlockedIncrement((LONG *)&ctrl[0]) - 1;
    tail = ctrl[1];
    if (head - tail >= WARP_EVENT_COUNT) {
        /* 读侧跟不上，最旧的那批要被覆盖掉 —— 交给 Python 一个准确的数字，
         * 它才知道「我漏了 37 条事件」，而不是默默丢。 */
        int drop = head - tail - WARP_EVENT_COUNT + 1;
        ctrl[1] = head - WARP_EVENT_COUNT + 1;
        InterlockedAdd((LONG *)&ctrl[2], drop);
    }

    index = (int)(head % WARP_EVENT_COUNT);
    slot = (WARP_EVENT *)((char *)g_hdr + WARP_EVENTS_OFFSET) + index;
    slot->id = h->event_id ? h->event_id : hook_index;
    slot->hook = hook_index;
    slot->tick = (int)GetTickCount();
    slot->a = out[0];
    slot->b = out[1];
    slot->c = out[2];
    slot->d = out[3];
    slot->e = out[4];
    slot->f = out[5];
    slot->g = out[6];
    slot->h = out[7];
    slot->i = out[8];
    slot->j = out[9];
    slot->k = out[10];
    slot->l = out[11];
}

/* 这次命中该在原函数返回之后才发事件吗？
 * 显式配了 WARP_WHEN_POST，或者关心返回值（ret_kind != VOID）——前者是
 * 构造函数要把字段填完才读得到，后者的值只存在于寄存器里。 */
int warp_emits_post(const WARP_HOOK *h)
{
    return h && (h->when == WARP_WHEN_POST || h->ret_kind != WARP_RET_VOID);
}

int warp_on_event(int hook_index, void *self, int argc,
                  void *a1, void *a2, void *a3,
                  void *a4, void *a5, void *a6)
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
    h->hits = hits;

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
        /* blocked 记「真的拦下来了多少次」：参数门放行的那次不计，
         * 插件在 Python 里靠它判断「这一单被我拦了，该说点什么」。 */
        InterlockedIncrement((LONG *)&h->blocked);
    }

    /* 事件优先于行为：只要钩子声明了 ACT_EVENT 就入队，哪怕它同时什么都不做。
     * 成就、统计这类消费者要的就是「发生过什么」，不该和弹窗/拦截抢语义。
     * 返回值类钩子在原函数之后才发（warp_on_event_post），这里只发 PRE 的。 */
    if ((h->actions & WARP_ACT_EVENT) && !warp_emits_post(h))
        warp_emit_event(hook_index, h, self, argc, a1, a2, a3, a4, a5, a6, 0);

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

/* 原函数返回之后的那一半：只服务「要在调用后发事件」的钩子。
 *
 * 由 thunk 在调完 original 之后调用，参数是 thunk 自己保住的形参（C 语义
 * 保证调用别人之后这些变量还活着）。ret 是原函数返回值的位模式——
 * ret_kind==FLOAT 时 thunk 已把 XMM0 的位模式拷进 int。 */
void warp_on_event_post(int hook_index, WARP_HOOK *h, void *self, int argc,
                        void *a1, void *a2, void *a3,
                        void *a4, void *a5, void *a6, int ret)
{
    if (!h || !g_hdr)
        return;
    if (hook_index < 0 || hook_index >= WARP_MAX_HOOKS)
        return;
    if (!(h->actions & WARP_ACT_EVENT) || !warp_emits_post(h))
        return;
    warp_emit_event(hook_index, h, self, argc, a1, a2, a3, a4, a5, a6, ret);
}

