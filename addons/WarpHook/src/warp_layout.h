/* warp_layout.h —— 共享内存布局的唯一真相。
 *
 * 这里的每个数字都必须和 Python 侧 warphook/layout.py 保持一致，
 * 改任何一项都要同时改那边，否则两边看到的内存不是同一张图。
 */
#pragma once
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <stddef.h>
#include <stdint.h>

/* =====================================================================
 * warp_host.dll —— WarpHook 的宿主 DLL（唯一需要 C 的部分）
 *
 * 设计目标
 *   依赖 WarpHook 的插件不再各自维护一份 C 源码：注入、等待游戏、解析
 *   il2cpp 混淆导出名、装配 MinHook、按规则触发行为，全部由这里完成。
 *   插件只需要往共享内存里写一份「钩子表 + 文案池 + 规则」。
 *
 * 线程模型（这条是硬约束，早期版本就栽在这）
 *   控制线程只碰 Win32 与共享内存，**绝不**在自己的线程里调 il2cpp。
 *   真正需要 il2cpp 的事情分成两类：
 *     · 只读元数据查询（找类、找方法）→ 就绪门闩通过后可以在控制线程做
 *     · 创建对象 / 弹窗 → 只能在游戏主线程，也就是钩子回调里做
 *   门闩要一路等到「域指针非空 + 程序集数组成形 + 稳定窗过去」，
 *   因为 GetModuleHandleW("GameAssembly.dll") 只代表 DLL 被映射，
 *   那时候 il2cpp 运行时往往还没初始化完，碰一下就整个进程崩掉。
 *
 * 共享内存布局（Python 侧 warphook/host.py 必须一致）
 *   0     WARP_HEADER      432 字节（状态头 + 命令槽 + 弹窗文本）
 *   432   WARP_HOOK[32]   32 × 288 = 9216
 *   9648  texts[256]     256 × 128 = 32768
 *   42416 exports[15]     15 × 64  = 960
 *   43376 ev_ctrl          16 字节（head/tail/dropped/pad）
 *   43392 events[2048] 2048 × 60  = 122880
 *   166272 reads[128]    128 × 48  = 6144
 *   172416 objects[32]   32 × 8   = 256
 *   172672 (结束)
 * ===================================================================== */

#include <windows.h>
#include <stdint.h>
#include <stddef.h>
#include "MinHook.h"

#define WARP_MAGIC        0x54534857u      /* "WHST" */
/* 数值转字符串（构建戳用）：warp_log("proto v" WARP_STR(WARP_VERSION)) */
#define WARP_STR_(x)      #x
#define WARP_STR(x)       WARP_STR_(x)
#define WARP_VERSION      6                /* v6：读取链新增 Dictionary 容器步
                                            * （deref=6/7）与字典计数 kind=9；
                                            * v5：尾部追加 buff 关注哈希表段（BUF 行）。
                                            * v4：钩子表 16→32（成就 25 条 + NoGacha 2 条
                                            * 已经装不下 16 槽，_layout 截断是静默的，
                                            * 真机上 NoGacha 的钩子整条消失） */

#define WARP_MAX_HOOKS    32
#define WARP_MAX_TEXTS    256
#define WARP_TEXT_LEN     128
#define WARP_KLASS_LEN    48
#define WARP_METHOD_LEN   48
#define WARP_LOG_LEN      48
#define WARP_EXPORT_COUNT 15
#define WARP_NAME_MAX     64

#define WARP_POLL_MS      250
#define WARP_GA_TIMEOUT_MS 180000
#define WARP_MIN_ASSEMBLIES 8
#define WARP_SETTLE_MS    1500
#define WARP_HB_STALE_MS  10000
#define WARP_VAR_COUNT    8      /* 钩子之间共享的整数槽个数（WARP_HEADER.vars） */
#define WARP_CMD_TEXT_LEN 256   /* 命令里的弹窗正文长度 */

/* 命令类型。cmd_type 是一个打包字：低 8 位命令号，8-11 位参数个数，
 * 12-15 位返回值形状，16-23 位对象槽号（MAKE/STR 的落槽、CALL 的 this、
 * RELEASE 的目标）。解析用 WARP_CMD_* 宏，打包用 WARP_CMD_PACK。 */
#define WARP_CMD_NONE     0
#define WARP_CMD_POPUP    1     /* 在游戏里弹原版系统弹窗 */
#define WARP_CMD_KILL     2     /* 结束游戏进程 */
#define WARP_CMD_MAKE     3     /* 构造对象：object_new (+ .ctor) → 对象槽 */
#define WARP_CMD_CALL     4     /* 调方法：runtime_invoke，槽内对象当 this（无槽=静态） */
#define WARP_CMD_STR      5     /* 造字符串：il2cpp_string_new(cmd_text) → 对象槽 */
#define WARP_CMD_RELEASE  6     /* 解掉槽上 GC 句柄并清槽 */

#define WARP_CMD_CODE(t)    ((t) & 0xFF)
#define WARP_CMD_ARGC(t)    (((t) >> 8) & 0xF)
#define WARP_CMD_RETKIND(t) (((t) >> 12) & 0xF)
#define WARP_CMD_SLOT(t)    (((t) >> 16) & 0xFF)
#define WARP_CMD_PACK(code, argc, retkind, slot) \
    (((code) & 0xFF) | (((argc) & 0xF) << 8) | (((retkind) & 0xF) << 12) | \
     (((slot) & 0xFF) << 16))

/* CALL 的返回值形状（box 解包 / 引用落槽） */
#define WARP_CMD_RET_INT32 0    /* box 返回，值在 +0x10，位模式写 vars[6] */
#define WARP_CMD_RET_FLOAT 1    /* box 返回 float，位模式写 vars[6] */
#define WARP_CMD_RET_REF   2    /* 引用返回，落对象槽 vars[7]（挂 GC 句柄） */

/* 命令参数类型（cmd_text 的 "#..." 后缀，一位一参）：参数值都在 vars[0..5] */
#define WARP_CMD_ARG_I 'i'      /* int32：vars 值就是参数 */
#define WARP_CMD_ARG_F 'f'      /* float：vars 值按位解释 */
#define WARP_CMD_ARG_P 'p'      /* 引用：vars 值就是对象指针（槽引用已在 py 侧解好） */

/* 命令结果码 */
#define WARP_CMD_RES_OK        0
#define WARP_CMD_RES_FAIL      1   /* 一般失败（对象构造返回空之类） */
#define WARP_CMD_RES_UNKNOWN   2   /* 未知命令 */
#define WARP_CMD_RES_EXCEPTION 3   /* 方法调用抛了异常 */
#define WARP_CMD_RES_NO_CLASS  4
#define WARP_CMD_RES_NO_METHOD 5
#define WARP_CMD_RES_BAD_SLOT  6   /* 槽号越界 */
#define WARP_CMD_RES_BAD_ARGC  7   /* 参数个数超出 vars 容量（>6） */

#define WARP_HEADER_SIZE  432   /* 160 状态头 + 命令槽 4*4 + 256 字节文本 */
#define WARP_HOOK_OFFSET  WARP_HEADER_SIZE
#define WARP_HOOK_SIZE    288
#define WARP_TEXTS_OFFSET (WARP_HOOK_OFFSET + WARP_MAX_HOOKS * WARP_HOOK_SIZE)
#define WARP_TEXT_SIZE    WARP_TEXT_LEN
#define WARP_EXPORTS_OFFSET (WARP_TEXTS_OFFSET + WARP_MAX_TEXTS * WARP_TEXT_SIZE)
#define WARP_EVENT_COUNT  2048  /* 环形队列容量，满了丢最旧的（丢的时候 ctrl[2] 自增） */
#define WARP_EVENT_SIZE   60
#define WARP_EV_CTRL_OFFSET (WARP_EXPORTS_OFFSET + WARP_EXPORT_COUNT * WARP_NAME_MAX)
#define WARP_EV_CTRL_SIZE 16    /* head / tail / dropped / pad */
#define WARP_EVENTS_OFFSET (WARP_EV_CTRL_OFFSET + WARP_EV_CTRL_SIZE)
#define WARP_READ_MAX     128   /* 全进程共用的读取链条数（damage 一条钩子就要 11 条） */
#define WARP_READ_SIZE    48
#define WARP_READ_STEPS   4     /* 一条链最多走几跳 */

/* 读取链每一步的动作。deref[i] 存的既是「要不要解引用」也是「这一步做什么」：
 * 0 加偏移；1 加偏移后解引用；2/3 把当前指针当容器取引用元素；
 * 4/5 同样取第 off[i] 个元素，但元素本身是 4 字节值类型（List<int> 之类）——
 * 元素值不追指针，直接当位模式带回来交给最后一步的 kind 解释。
 * 6/7 把当前指针当 il2cpp Dictionary<*,*>：跳过被 Remove 留下的空坑
 * （entry.hashCode < 0），取第 k 个「活跃」entry 的 value。entry 的尺寸和
 * value 字段偏移随 TKey/TValue 形状变化，配置方从 dump.cs 算好打包进
 * off[i]（见 WARP_DICT_PACK）；7 表示 value 是 4B 值类型（int→int 字典），
 * 读出来的是值不是指针，后续步骤把它当普通整数继续加偏移。
 * off[i] 带 bit31 时这条链是「遍历」链：一次命中对每个活跃 value 各发一个
 * 事件（warp_apply_reads 负责循环），而不是只取第 k 个。 */
#define WARP_STEP_PLAIN 0
#define WARP_STEP_DEREF 1
#define WARP_STEP_LIST  2   /* List<T>  : items(+0x10) / size(+0x18) */
#define WARP_STEP_ARRAY 3   /* Array<T> : length(+0x18) / 元素从 +0x20 起 */
#define WARP_STEP_LIST_VAL  4   /* List<值类型>，元素 stride 4 */
#define WARP_STEP_ARRAY_VAL 5   /* Array<值类型>，元素 stride 4 */
#define WARP_STEP_DICT_VALUE   6 /* Dictionary：取第 k 个活跃 entry 的 value 引用 */
#define WARP_STEP_DICT_VALUE32 7 /* 同 6，但 value 是 4B 值类型（读值不留指针） */

/* Dictionary 步的 off[i] 打包（warp_dict_nth_value 解包）：
 *   bit0-7   value_off —— value 字段在 entry 内的偏移，0 → 默认 16
 *   bit8-15  stride    —— entry 尺寸，0 → 默认 24（x64 下 int→引用 / 引用→引用）
 *   bit16-30 下标 k    —— 随机访问取第 k 个活跃 entry；遍历链由运行时填
 *   bit31    ITER 标记 —— 遍历链（一次命中发 N 个事件） */
#define WARP_DICT_PACK(value_off, stride, k, iter) \
    (((value_off) & 0xFF) | (((stride) & 0xFF) << 8) | \
     (((k) & 0x7FFF) << 16) | ((iter) ? 0x80000000u : 0u))
#define WARP_DICT_VALUE_OFF(packed) ((packed) & 0xFF)
#define WARP_DICT_STRIDE(packed)    (((packed) >> 8) & 0xFF)
#define WARP_DICT_INDEX(packed)     (((packed) >> 16) & 0x7FFF)
#define WARP_DICT_ITER(packed)      (((packed) >> 31) & 1u)

/* 遍历链一次命中的事件轮数上限：真用例是全场单位（≤10），给到 256 已经
 * 覆盖任何合理的字典；偏移写错时 count 可能是天文数字，别真去灌事件环。 */
#define WARP_ITER_MAX 256
#define WARP_READ_OFFSET  (WARP_EVENTS_OFFSET + WARP_EVENT_COUNT * WARP_EVENT_SIZE)

/* 对象槽：钩子命中时把某个参数的指针留在这儿，读侧（Python 或另一条读链）
 * 稍后再按需读。用途是老链路里那批 `cache_self` / `cache_arg1` 读法 ——
 * 「先记住对象在哪儿，回头再摸」跟「这一次调用里就把值读出来」是两件事。
 * 槽里只有指针，不加引用计数：对象可能在两次读取之间就被释放了，所以读的
 * 时候一律走 warp_can_read 校验，读到坏地址就当这次没读到。 */
#define WARP_OBJECT_COUNT 32
#define WARP_OBJECT_SIZE  8     /* 一个 void* */
#define WARP_OBJECTS_OFFSET (WARP_READ_OFFSET + WARP_READ_MAX * WARP_READ_SIZE)
#define WARP_OBJ_ARG_BASE 0x100 /* 读链的 arg 写 0x100+n = 从第 n 个对象槽出发 */

/* buff 关注哈希表（v5）：Python 把成就规则里出现的 buff 名 FNV-1a 64 之后
 * 写在这里，0 是哨兵（FNV-1a 64 的结果不会是 0）。C 侧 buff_mask 读法
 * 遍历单位 buff 链、对每个 buff 名算同一个哈希、按表置位 —— 事件里带
 * 一张位掩码，Python 端按名单展开。表空（首字节 0）时读法直接放弃，
 * 没成就用 buff 的插件零开销。 */
#define WARP_BUFF_WATCH_COUNT 32
#define WARP_BUFF_WATCH_SIZE  8 /* fnv1a64 */
#define WARP_BUFF_WATCH_OFFSET (WARP_OBJECTS_OFFSET + WARP_OBJECT_COUNT * WARP_OBJECT_SIZE)
#define WARP_MAP_BYTES    (WARP_BUFF_WATCH_OFFSET + WARP_BUFF_WATCH_COUNT * WARP_BUFF_WATCH_SIZE)

/* 读出来的值怎么解释 */
#define WARP_READ_INT     0     /* int32 */
#define WARP_READ_FLOAT   1     /* float，按位取回来由 py 还原 */
#define WARP_READ_BOOL    2     /* 只取低 8 位当 0/1 */
#define WARP_READ_PTR     3     /* 指针，只给地址不追 */
#define WARP_READ_OBSCURED 4    /* ObscuredInt：value = hidden ^ key（血量/理智那种混淆 int） */
#define WARP_READ_SUM_LIST  5   /* 落点是 List<4B 值类型>：把所有元素求和（铁路通关回合） */
#define WARP_READ_COUNT_LIST 6  /* 落点是 List/Array：只取元素个数 */
#define WARP_READ_TEXT_NUM  7   /* 落点是 il2cpp string*：抽出 ASCII 数字串拼成 int（UI 显示文本） */
#define WARP_READ_BUFF_MASK 8   /* 落点是战斗单位：遍历 buff 链对每个 buff 名算 fnv1a64，
                                 * 命中关注表（WARP_BUFF_WATCH_OFFSET）就置位 —— out=位掩码。
                                 * off[0..3] = 单位buff详情/列表/模型数据/静态id 四个字段偏移。 */
#define WARP_READ_COUNT_DICT 9  /* 落点是 il2cpp Dictionary<*,*>：活跃 entry 数 =
                                 * count(+0x20) - freeCount(+0x28)。il2cpp 字段序是
                                 * count/freeList/freeCount/version（+0x2C 是 version，
                                 * 与 .NET reference source 不同，真机实测纠正）。
                                 * 注意 List/Array 的计数（kind=6）读的是 +0x18。 */

/* 原函数返回值怎么取（thunk 调原函数后按这个类型拿返回值） */
#define WARP_RET_VOID  0        /* 不关心返回值（原 thunk 的行为） */
#define WARP_RET_INT32 1        /* 返回值在 RAX 低 32 位（int 返回的方法） */
#define WARP_RET_FLOAT 2        /* 返回值在 XMM0（float 返回的方法），按位模式带回 */

/* 事件在原函数调用之前还是之后发 */
#define WARP_WHEN_PRE  0        /* 默认：命中瞬间就发（原 thunk 的行为） */
#define WARP_WHEN_POST 1        /* 原函数返回后再发：构造函数要把字段填完才读得到 */

/* 状态 */
#define WARP_ST_IDLE       0   /* 等游戏 */
#define WARP_ST_LOADING    1   /* 游戏在起，il2cpp 还没就绪 */
#define WARP_ST_HOOKING    2   /* 正在装配钩子 */
#define WARP_ST_HOOKED     3   /* 已挂钩 */
#define WARP_ST_ERROR      4

/* 错误码 */
#define WARP_ERR_OK        0
#define WARP_ERR_NO_CONFIG 1
#define WARP_ERR_GA_TIMEOUT 2
#define WARP_ERR_NO_IL2CPP 3
#define WARP_ERR_NO_TARGET 4
#define WARP_ERR_MH_INIT   5
#define WARP_ERR_MH_CREATE 6
#define WARP_ERR_MH_ENABLE 7
#define WARP_ERR_NO_POPUP  8

/* 动作位 */
#define WARP_ACT_POPUP  0x01
#define WARP_ACT_PANEL  0x02
#define WARP_ACT_KILL   0x04
#define WARP_ACT_EVENT  0x08   /* 把这次命中装进事件队列给 py 读 */

/* 一个钩子要么只发事件、要么顺便触发行为，两种位互不干扰 */
#define WARP_ACT_BEHAVIOR (WARP_ACT_POPUP | WARP_ACT_PANEL | WARP_ACT_KILL)

/* 钩子标志 */
#define WARP_HF_BLOCK   0x01
#define WARP_HF_ONCE    0x02   /* 只触发一次 */
#define WARP_HF_DEDUPE  0x04   /* 读链读出来的值没变就不投递事件 */
#define WARP_HF_FIRED   0x0100 /* 运行时标记：已经触发过 */

typedef struct _WARP_HEADER {
    unsigned int magic;            /* 0   */
    int  version;                  /* 4   */
    int  enabled;                  /* 8   */
    int  hooked;                   /* 12  */
    int  status;                   /* 16  */
    int  last_error;               /* 20  */
    int  heartbeat;                /* 24  启动器每 2s 写一次 tick */
    int  standalone;               /* 28  1 = 启动器已断开，用内存快照继续跑 */
    int  evt_count;                /* 32  钩子命中总次数 */
    int  hook_installed;           /* 36  */
    int  hook_total;               /* 40  */
    int  panel_step;               /* 44  UI 构建卡在第几步（0 = 正常） */
    int  last_event;               /* 48  最近命中的钩子下标 */
    int  fired;                    /* 52  触发过多少次行为 */
    int  ga_found;                 /* 56  1=DLL 已映射 2=域在加载 3=完全就绪 */
    int  popup_ok;                 /* 60  原版弹窗方法是否解析成功 */
    unsigned long long boot_at;    /* 64  引擎就绪时刻 GetTickCount64，delay_ms 从这儿算 */
    int  dedupe_ms;                /* 72  同回合多钩子的去重窗口 */
    int  reserved0;                /* 76  */
    char log_tail[WARP_LOG_LEN];   /* 80  */
    int  vars[8];                  /* 128 钩子间共享的整数槽：探针结果、计数 */
    /* ---- 命令槽：让 py 能主动命令游戏做事，而不只是挂钩子等它自己触发 ---- */
    int  cmd_seq;                  /* 160  py 每次下命令自增；-1 表示还没用过 */
    int  cmd_ack;                  /* 164  DLL 执行完把 seq 抄回来 */
    int  cmd_type;                 /* 168  1=弹窗 2=杀进程 */
    int  cmd_result;               /* 172  上次执行的结果码（0=成功） */
    char cmd_text[WARP_CMD_TEXT_LEN]; /* 176 弹窗正文 */
} WARP_HEADER;                     /* 432 */

typedef struct _WARP_HOOK {
    char klass[WARP_KLASS_LEN];    /* 0   类名 */
    char method[WARP_METHOD_LEN];  /* 48  方法名 */
    int  argc;                     /* 96  参数个数 */
    int  event_id;                 /* 100 事件号，同号共用一个去重窗口 */
    int  every;                    /* 104 每 N 次触发一次（0/1 = 每次） */
    int  chance;                   /* 108 触发概率 0-100 */
    int  actions;                  /* 112 WARP_ACT_* 位掩码 */
    int  flags;                    /* 116 WARP_HF_* */
    int  hold_ms;                  /* 120 panel 停留毫秒 */
    int  delay_ms;                 /* 124 引擎就绪后再等多久 */
    int  guard_index;              /* 128 参数门：看第几个参数（<0 关闭） */
    int  guard_value;              /* 132 该参数等于它时放行（不拦、不弹） */
    char probe_class[WARP_KLASS_LEN];   /* 136 探针对象类名（空 = 不探针） */
    char probe_method[WARP_METHOD_LEN]; /* 184 探针 getter（0 参） */
    int  probe_index;              /* 232 拿第几个参数当对象（默认 0） */
    int  probe_slot;               /* 236 结果写进 vars[几] */
    int  guard_var;                /* 240 参数门改成比较 vars[几]（>=0 生效） */
    int  text_base;                /* 244 文案从第几句开始挑（多插件分段用） */
    int  read_base;                /* 248 第一条读取链在全局表里的下标 */
    int  read_count;               /* 252 用了几条 */
    int  cache_arg;                /* 256 命中时把第几个参数存进对象槽（<0 关闭） */
    int  cache_slot;               /* 260 存进哪个槽（0..WARP_OBJECT_COUNT-1） */
    int  hits;                     /* 264 运行时：命中数 */
    int  blocked;                  /* 268 运行时：拦下数 */
    int  when;                     /* 272 WARP_WHEN_*：事件在原函数前(0)还是后(1)发 */
    int  ret_kind;                 /* 276 WARP_RET_*：原函数返回值类型（0=不关心） */
    int  ret_slot;                 /* 280 返回值直出的事件格（<0 不直出；与读链别写同一格） */
    int  pad;                      /* 284 对齐保留 */
} WARP_HOOK;                       /* 288 */

/* 一条读取链：从某个参数出发，按偏移跳 nsteps 次，把落点当成一个值读出来。
 *
 * il2cpp 里的「取字段」只有两种动作：把当前指针加上偏移（内嵌 struct），
 * 或者先解引用再算（class 引用）。所以每一步带一个 deref 位就够了，
 * 不需要知道字段类型 —— 类型只影响最后一步怎么解释（kind）。
 *
 * 钩子把 read_base / read_count 写在自己的钩子槽里，链条本体按下标共用这张全局表。 */
typedef struct _WARP_READ {
    int arg;               /* 0  从第几个参数出发（0 = self，1..3 = 第 1..3 个参数） */
    int nsteps;            /* 4  走几跳（0 = 直接用参数本身） */
    int kind;              /* 8  WARP_READ_* */
    int out;               /* 12 写进事件的哪一格（0=a 1=b 2=c 3=d） */
    int off[WARP_READ_STEPS];    /* 16 每跳的偏移 */
    int deref[WARP_READ_STEPS];  /* 32 每跳是否先解引用 */
} WARP_READ;                /* 48 */

/* 环形队列里的一个事件：py 侧按 events() 批量读走，读完推进 tail。
 *
 * 十二格值（a..l）是给成就那类消费者留的：一条读法往往要「实例号 + 模板号 +
 * 血量 + 上限 + 理智 + 速度」六七个数，伤害钩子更是一次要发行动五件套加
 * 血量五件套 —— 八格就得拆两条钩子再在 Python 里配对，不如一次给够。 */
typedef struct _WARP_EVENT {
    int id;     /* 0  事件号（hook.event_id，0 时用钩子下标） */
    int hook;   /* 4  哪个钩子产生的 */
    int tick;   /* 8  GetTickCount 低 32 位 */
    int a;      /* 12 第 1 格：默认是第 1 个参数，配了读链就是读出来的值 */
    int b;      /* 16 第 2 格 */
    int c;      /* 20 第 3 格 */
    int d;      /* 24 第 4 格：默认 vars[0] 的快照，省一次读 */
    int e;      /* 28 第 5 格 */
    int f;      /* 32 第 6 格 */
    int g;      /* 36 第 7 格 */
    int h;      /* 40 第 8 格 */
    int i;      /* 44 第 9 格 */
    int j;      /* 48 第 10 格 */
    int k;      /* 52 第 11 格 */
    int l;      /* 56 第 12 格 */
} WARP_EVENT;   /* 60 */

#define WARP_EVENT_SLOTS  12  /* 读链的 out 能写到 0..11 */

/* ------------------------------------------------------------------ */
/* il2cpp 接口表（顺序必须和 il2cpp-api-names.txt / Python 侧一致）     */
/* ------------------------------------------------------------------ */

typedef void *(*fn_domain_get)(void);
typedef void **(*fn_domain_get_assemblies)(void *domain, size_t *count);
typedef void *(*fn_assembly_get_image)(void *assembly);
typedef void *(*fn_class_from_name)(void *image, const char *ns, const char *name);
typedef void *(*fn_class_get_method_from_name)(void *klass, const char *name, int argc);
typedef void *(*fn_string_new)(const char *utf8);
typedef void *(*fn_runtime_invoke)(void *method, void *obj, void **params, void **exc);
typedef void *(*fn_thread_attach)(void *domain);
typedef void *(*fn_object_new)(void *klass);
typedef void *(*fn_class_get_type)(void *klass);
typedef void *(*fn_type_get_object)(void *type);
typedef void *(*fn_array_new)(void *klass, size_t length);
typedef void *(*fn_class_get_parent)(void *klass);
typedef unsigned int (*fn_gchandle_new)(void *obj, unsigned int strong);
typedef void (*fn_gchandle_free)(unsigned int handle);

