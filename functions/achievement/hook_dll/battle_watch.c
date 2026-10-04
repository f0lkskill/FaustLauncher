/* battle_watch.c —— 战斗事件观测 DLL v2（成就用，**只读**）
 *
 * v1 的教训（实测 2026-09-23）：dump.cs 里给的 RVA 有不少是 **IL2CPP 尾调用桩**
 * （`33 D2 E9 rel32` = `xor edx,edx; jmp 真实实现`），钩在桩上只有在"调用方真的
 * 经过这个桩"时才触发；实测 BattleUnitModel::RefreshSpeed 是
 * `jmp BattleUnitModel::SetRandomSpeed`、BattleActionModelManager::OnRoundStart_Before
 * 是 `jmp BattleActionModelManager::Init`，而调用方直接调真实实现 —— 于是整场战斗
 * 一条事件都没有。所以 v2 改成：
 *
 *   1. **通用多钩子表**：要钩哪些地址、什么签名、prologue 是什么，全部由 Python 端
 *      写进共享内存（Python 端会先做"尾调用桩解引用"，把桩换成真实实现再下发）；
 *   2. **命中计数**（hook_hits[]）：Python 端轮询它就能报出"每个钩子被调了多少次"，
 *      装钩成功但 0 次调用 = 一眼看出钩错了地方（这正是 v1 缺失的可观测性）；
 *   3. 每个钩子按 kind 走对应签名的 detour，detour 里读完字段发语义事件
 *      （SPD / ACT / RND），不做任何判定（判定在 Python）。
 *
 * v3（2026-09-23）：SPD 事件补上 **整数速度** 字段。`_originSpeed`(0xCC) /
 * `_overwritedSpeed`(0xD0) 存的是「速度 ×1000」的定点数（小数部分是隐藏的同速排序值，
 * 游戏 `BattleUnitModel::GetIntegerOfPureOriginalSpeed` 就是 /1000），直接看原始值会得到
 * 14518 这种怪数。所以日志行同时给原始值与换算值：
 *     SPD tag=.. iid=.. oid=.. os=14518 osi=14 ow=-1 owi=-1 its=4
 * 其中 osi/owi = trunc(raw/1000)（负数 = 本回合还没掷速度，原样给 -1）；
 * its(0x184 `_thisTurnIntSpeedOnCmdPhase`) 本来就是整数，不缩放。
 * 协议/结构体没变（仍是 FBW2），Python 端两种字段都认（有 osi/owi 就优先用）。
 *
 * 设计骨架（共享内存配置 / 环形日志 / prologue 自检 / watcher 重试）沿用
 * test/damage_log.c，两者互不干扰，可以同时注入。
 *
 * v4（2026-09-23）：新增 **血量 / 理智** 观测（VAL 事件）。链路：
 *     BattleUnitModel._state(0x148) → CharacterState
 *     CharacterState._maxHp(0x11C) / _hp(0x148) / _mp(0x158)    ← 都是 ACTk ObscuredInt
 * `_mp` 就是界面上的理智(SP)（同类常量 _maxMp=45 / _minMp=-45 正好是它的上下限，
 * 负数理智 = 陷入恐慌）——「魔法少女的悲剧」靠它。
 * 读不出来一律发 BW_VITAL_UNREAD(-1000)，绝不像 0/-1 那样被误当成“真的负数理智”。
 * 为避免每枚硬币都刷屏，DLL 内按 (单位指针, hp, mp) 去重，只在上报值变化时发 VAL。
 * 因为多了 4 个偏移，结构体布局变了 → 魔数改为 FBW3，ring 偏移 1060 / 总大小 132132。
 *
 * v5（2026-09-24）：新增 **buff 观测**（BUF 事件）。链路（dump.cs 确认）：
 *     BattleUnitModel._buffDetail(0xE0) → BuffDetail._grantedBuffList(0x10) : List<BuffModel>
 *     List → items(0x10)/size(0x18) → BuffModel._buffData(0x68) → BuffStaticData.id(0x18) : string
 * buff 的 id 是**字符串**（如 HanafudaTwo / FutureEyeOnRodion，与 Lang/Bufs.json 的 id 一致）。
 * 配置里带一张 **关注 buff 表**（buff_watch_count + buff_watch_hashes[]，Python 写入名字的
 * FNV-1a 64 哈希）；DLL 只在命中关注表时发 `BUF ... m=<命中位掩码>`，没配规则时完全不算
 * （连 buff 链都不读），所以不加成就时零开销。
 * 因为多了 4 个偏移 + 末尾多了关注表 → 魔数改为 FBW4，ring 偏移 1076 / 总大小 132408。
 *
 * v6 / FBW5（2026-09-25）：多一个 off_skv_attacker_iid（表现层动画 tick 的身份）
 * → 多 4 字节，后面的字段与 ring 一起后移、总大小 132416。驱动按“动画 tick 带 iid”
 * 把判定对齐到具体行动（不再是一股脑延后），所以这是必需的一格；
 * 与旧 DLL 混用会被魔数拦住（报版本不符，不会静默错位）。
 *
 * ⚠️ 只读：所有读取都经 ReadProcessMemory(GetCurrentProcess()) 带边界校验，
 * 不写游戏内存、不调用游戏函数。
 */

#include <windows.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <stddef.h>
#include "MinHook.h"

#define BW_MAGIC        0x36574246u          /* "FBW6"（v1=FBW1…v5=FBW3+HP/理智，v5 加 buff 偏移与关注表，
                                              *  v6 加关卡结算统计 + 钩子槽 12→16）—— 布局变了就换一个值，
                                              *  这样"游戏里还挂着旧 DLL"时新驱动能直接判出版本不符。*/
#define BW_MAP_NAME     L"Local\\FaustLauncher_BattleWatch"
#define BW_POLL_MS      300
#define BW_GA_TIMEOUT_MS 60000
#define BW_LOG_RING_CAP 512
#define BW_LOG_LINE_MAX 255
#define BW_MAX_HOOKS    24     /* 钩子槽上限（候选已 20 个；满槽时排最后的 stage_progress 会被截断）*/
#define BW_NAME_LEN     40
#define BW_SPEED_SCALE  1000   /* 速度字段的定点比例：_CORRECTION_FOR_SPEED */
#define BW_VITAL_UNREAD (-1000)  /* HP/理智读不出来时的哨兵（HP 不可能为负、理智只有 ±45）*/
#define BW_VITAL_SLOTS  64       /* (单位指针, hp, mp, buff 掩码) 去重表大小 */
#define BW_SAMPLE_MS      250    /* 采样线程重读 hp/sp/buff 的间隔 */
#define BW_BUFF_WATCH_MAX 32     /* 关注 buff 上限（Python 端同值）*/
#define BW_BUFF_LIST_MAX  96     /* 单个单位最多看多少个 buff（防脏数据卡死）*/
#define BW_STAGE_SLOT_MAX 8      /* 结算统计最多看几个 slot（防脏数据卡死）*/
#define BW_STAGE_WATCH_MAX 32    /* 关注关卡上限（已通关列表的轮询上报用；位图按 32 位算）*/
#define BW_CLEAR_LIST_MAX  512   /* 已通关列表最多扫多少条（防脏数据卡死）*/
#define BW_NCL_SEEN_MAX    96    /* NCL 已上报去重表（按 章*1e6+小节*1e3+节点 打包）*/
#define BW_PROGRESS_MAX    32    /* 进度树遍历上限（章/每章小节/每节节点）*/

/* ACTk ObscuredInt 内部布局（dump.cs 实测） */
#define OBI_KEY    0
#define OBI_HIDDEN 4
#define OBI_FAKE   8
#define OBI_INITED 13

/* 钩子 kind（决定 detour 签名与事件内容） */
#define BWK_PLAIN          0   /* void (self, mi)                                  → 无事件 */
#define BWK_UNIT           1   /* void (self, mi)                                  → SPD */
#define BWK_UNIT_INT_BOOL  2   /* void (self, int value, bool checkMinMax, mi)      → SPD + value */
#define BWK_UNIT_GET_INT   3   /* int  (self, mi)                                  → SPD（按 iid+值去重）*/
#define BWK_ACTION_INT     4   /* void (self, int timing, mi)                      → ACT */
#define BWK_DAMAGE_ACTION  5   /* float(self, action, coin, attacker, bool, mi)     → ACT（attacker 身份 + action 技能）*/
#define BWK_SKV            6   /* void (self, mi)：表现层技能动画 → RND + iid（self->_attackerInstanceID）
                                *
                                * 为什么要带 iid：这游戏先算完整回合再播动画，结算阶段的事件全挤在
                                * 一瞬间 —— 光看“第几次动画结束”无法把判定对齐到“哪个行动”。
                                * 动画层 self 上的 _attackerInstanceID 就是“这手是谁在打”，
                                * Python 据此把挂起的判定按行动放行。读不到/越界就发 iid=-1，
                                * Python 退回“一次 tick 放一条”的老行为。 */
#define BWK_STAGE_STAT     7   /* void (self, externalData, format, mi)：关卡结算统计
                                *   self = StageStatisticPopupData（本条就是它自己的 .ctor）
                                *   → STG uid=<关卡uid> turn=<通关回合数> dead=<阵亡数> ex=<是否EX>
                                *
                                * 为什么要它：折射铁路（玩家口中的"一号线/二号线/六号线"）
                                * 的通关回合数**只在内存里**，Player.log 完全没有 —— 而
                                * "六号线 <100T 通关"这类成就必须拿到每关的清关回合数。
                                * 数据在 StageStatisticPopupSlotData._clearTurn（见 dump.cs）；
                                * 由于列表是构造函数里填的，thunk 必须**先调原函数再读**。*/
#define BWK_RAILWAY_TOTAL  8   /* int (self, mi)：折射铁路**整条线的最好回合数**
                                *   self = RailwayDungeonHistoryDataByCollection
                                *   → RWT line=<线路号> total=<总回合数>
                                *
                                * 为什么要它：进线路之前游戏会显示"你最好的回合数"，那就是
                                * self->_collectionId(0x10) + GetTotalClearTurn()。结算事件
                                * （BWK_STAGE_STAT）只能拿到单关回合，整条线的总回合只在这里。*/
#define BWK_CACHE_SELF     9   /* void (self, a1, mi)：**只把 self 指针缓存下来**，不发事件
                                *
                                * 用途：抓住 UserStageClearInfoData（挂钩它的 UpdateData ——
                                * 存档载入时必调），之后交给采样线程轮询它里面的"已通关关卡列表"。
                                * 为什么不用静态字段链：那条路要靠静态块基址解析，而现有 enkephalin
                                * 链的运行时重定位本来就是失败的，不能把成就压在它上面。
                                * 这也是"不打那关也能判定"的关键：存档一直在内存里，进游戏即可回溯。*/
#define BWK_CACHE_ARG1    11   /* void (self, a1, mi)：把**第一个参数**缓存下来，不发事件
                                *
                                * 用途：挂钩 UserStageNodeStateData::UpdateData(List<MainChapterStateFormat>)
                                * —— 登录时全量下发主线进度，a1 就是整棵 章→小节→节点 树的根。
                                * 采样线程遍历它即可**全量判定、不需要点开任何界面**。
                                * （IsNodeCleared 那类查询只在界面渲染时调，实测连第十章都没查过。）*/
#define BWK_RAILWAY_NODE  12   /* void (self, a1, mi)：折射铁路**每节点的通关回合数**
                                *   挂钩 RailwayDungeonFormerSaveData::.ctor(RailwayNodeDataFormat)
                                *   → 先调原构造函数（字段在里面填），再读
                                *     self[nodeId 0x10] / self[clearTurn 0x14]
                                *   → RWT node=<节点id> turn=<通关回合数>
                                *
                                * 为什么不用 GetTotalClearTurn：那个只在打开线路界面时被调，
                                * 实测玩家看过六号线依然 0 命中。这个是存档重建时逐个节点构造的，
                                * 不依赖界面。*/
#define BWK_RAILWAY_HIST  13   /* void (self, int cid, ..7 more.., mi)：铁路**历史记录**（最好回合）
                                *   挂钩 RailwayDungeonHistoryDataByCollection::.ctor
                                *   （签名已从 dump 确认 = 9 个参数，RVA 0x1A83860）
                                *   arg1 = 线路号(_collectionId)，arg4 = IList<int> clearTurns
                                *   → RWT line=<线路号> total=<各节点回合求和>
                                *
                                * 与 BWK_RAILWAY_NODE 的区别：那个是【本次行程】的存档（没打就是 0），
                                * 这个才是界面上显示的"你最好的回合数"，也就是成就该用的。*/
#define BWK_NODE_STATE    10   /* int (self, int main, int sub, int node, mi)：关卡通关状态查询
                                *   挂钩 UserStageNodeStateData::IsNodeCleared /
                                *   GetClearNodeState —— 关卡列表每次渲染都会问，
                                *   而且**章节号/节点号就是入参**，返回值 = 通没通。
                                *   → NCL main=<主线章> sub=<小节> node=<节点> cleared=<0|1>
                                *
                                * 为什么不用 UserStageClearInfoData：实测那个类当前 UI 根本不用，
                                * 三条挂点（含 UI 查询）全程 0 命中。这个是游戏自己在用的。*/

/* 错误码 */
#define BW_ERR_OK         0
#define BW_ERR_NO_CONFIG  1
#define BW_ERR_GA_TIMEOUT 2
#define BW_ERR_PROLOGUE   3
#define BW_ERR_MH_INIT    4
#define BW_ERR_MH_CREATE  5
#define BW_ERR_MH_ENABLE  6

typedef struct _BW_CONFIG {
    volatile LONG magic;
    volatile LONG observing;
    volatile LONG log;
    volatile LONG retry_requested;

    /* 钩子表（由 Python 端填；RVA=0 表示该槽不用） */
    volatile LONG hook_count;
    volatile LONG hook_rva[BW_MAX_HOOKS];
    volatile LONG hook_kind[BW_MAX_HOOKS];
    volatile LONG hook_hits[BW_MAX_HOOKS];          /* DLL 累加：命中计数 */
    unsigned char hook_prologue[BW_MAX_HOOKS][16];
    char          hook_name[BW_MAX_HOOKS][BW_NAME_LEN];

    /* 结构体字段偏移 */
    volatile LONG off_unit_instance_id;
    volatile LONG off_unit_origin_id;
    volatile LONG off_unit_origin_speed;
    volatile LONG off_unit_overwrited_speed;
    volatile LONG off_unit_int_speed_turn;
    /* CharacterState 链（HP / 理智）：unit[off_unit_state] → CharacterState* */
    volatile LONG off_unit_state;
    volatile LONG off_state_hp;
    volatile LONG off_state_max_hp;
    volatile LONG off_state_mp;
    /* buff 链：unit[off_unit_buff_detail] → BuffDetail[off_buff_detail_list]
     *            → List<BuffModel> → BuffModel[off_buff_model_data]
     *            → BuffStaticData[off_buff_static_id] : string */
    volatile LONG off_unit_buff_detail;
    volatile LONG off_buff_detail_list;
    volatile LONG off_buff_model_data;
    volatile LONG off_buff_static_id;
    volatile LONG off_action_skill;
    volatile LONG off_action_commander_id;
    volatile LONG off_action_actor_id;
    volatile LONG off_skill_data;
    volatile LONG off_skill_id;
    volatile LONG off_skill_tier;
    /* 表现层 BattleSkillViewBase::_attackerInstanceID（动画 tick 的身份，见 BWK_SKV）*/
    volatile LONG off_skv_attacker_iid;

    /* 状态回写 */
    volatile LONG gameassembly_found;
    volatile LONG verified;            /* 全部 prologue 通过 */
    volatile LONG installed;           /* 全部钩子装好 */
    volatile LONG last_error;
    volatile LONG event_count;
    volatile LONG round_seq;
    volatile LONG ring_offset;
    volatile LONG struct_size;
    char           last_log[128];
    volatile LONG log_head;
    char           log_ring[BW_LOG_RING_CAP][BW_LOG_LINE_MAX + 1];

    /* 关注 buff 表（放在结构体末尾：ring 偏移不变，只让总大小变）
     * Python 把成就用到的 buff 名做 FNV-1a 64 哈希后填进来；DLL 只在命中关注表时发 BUF。*/
    volatile LONG buff_watch_count;
    volatile unsigned long long buff_watch_hashes[BW_BUFF_WATCH_MAX];

    /* 关卡结算统计（BWK_STAGE_STAT）—— 同样放末尾：ring 偏移保持不变，只让总大小变。
     * 列表是 IL2CPP 的引用类型 List<T>：_items 在 +0x20、_size 在 +0x18（与 buff 链同）。*/
    volatile LONG off_stage_slot_list;   /* StageStatisticPopupData._slotDataList  (0x10) */
    volatile LONG off_slot_uid;          /* StageStatisticPopupSlotData._uid        (0x10) */
    volatile LONG off_slot_clear_turn;   /* StageStatisticPopupSlotData._clearTurn  (0x18) */
    volatile LONG off_slot_dead_count;   /* StageStatisticPopupSlotData._deadUnitCount (0x1C) */
    volatile LONG off_slot_ex_cleared;   /* StageStatisticPopupSlotData._exCleared  (0x20) */

    /* 折射铁路整条线的总回合（BWK_RAILWAY_TOTAL）—— 同样放末尾 */
    volatile LONG off_railway_collection_id;  /* RailwayDungeonHistoryDataByCollection._collectionId (0x10) */

    /* 存档：已通关关卡记录（BWK_CACHE_SELF 抓对象 → 采样线程轮询）——
     * 这条链让"以前打过的关"也能判定：存档在内存里一直存在，进游戏就能回溯。*/
    volatile LONG off_stage_clear_list;   /* UserStageClearInfoData._stageClearInfoList (0x18) */
    volatile LONG off_clear_info_list;    /* StageClearInfoList._list : List<StageClearInfo> (0x10) */
    volatile LONG off_clear_info_id;      /* StageClearInfo._id（关卡 id）(0x10) */
    volatile LONG stage_watch_count;      /* 关注关卡条数（Python 端填）*/
    volatile LONG stage_watch_ids[BW_STAGE_WATCH_MAX];
    volatile long long stage_clear_data;  /* 抓到的 UserStageClearInfoData*（DLL 自己写）*/
    volatile LONG stage_seen_mask;        /* 已上报过的关注槽位图（DLL 自己写，只报一次）*/
    volatile LONG stage_diag_done;        /* 一次性诊断是否已发（见 poll_stage_clears）*/

    /* NCL（关卡通关状态查询）去重表：打包值 章*1e6+小节*1e3+节点，只报没报过的 */
    volatile LONG ncl_seen[BW_NCL_SEEN_MAX];
    volatile LONG ncl_seen_count;

    /* 存档全量进度树（BWK_CACHE_ARG1 抓 UpdateData 的列表参数 → 采样线程遍历）
     * 章[id 0x10][小节 off_chapter_subs] → 小节[id 0x10][节点 off_sub_nodes]
     *   → 节点[off_node_id][off_node_clear_type ct][off_node_clear_number cn] */
    volatile long long stage_progress_list;
    volatile LONG off_chapter_subs;
    volatile LONG off_sub_nodes;
    volatile LONG off_node_id;
    volatile LONG off_node_clear_type;
    volatile LONG off_node_clear_number;
    /* 折射铁路每节点记录（BWK_RAILWAY_NODE 读 self 上的字段）*/
    volatile LONG off_railway_node_id;
    volatile LONG off_railway_node_turn;
} BW_CONFIG;

/* 布局自检：v6/FBW6 → 钩子槽 16，ring 偏移 1352，总大小 1352 + 512*256 + 4(+4对齐)
 *                     + 32*8 + 5*4(对齐后 24) = 132712。
 * Python 侧的 ctypes 结构体用同一份字段定义；注入后会比对 DLL 回写的
 * ring_offset/struct_size，不一致就报错，所以这里只卡对齐与总大小。*/
_Static_assert(offsetof(BW_CONFIG, log_ring) % 4 == 0, "log_ring 偏移未对齐");
_Static_assert(offsetof(BW_CONFIG, buff_watch_hashes) % 8 == 0, "关注表未对齐");
_Static_assert(sizeof(BW_CONFIG) == 133848, "BW_CONFIG 大小不一致（改了字段就同步改 Python）");

static BW_CONFIG *g_cfg = NULL;
static HANDLE      g_stop_event = NULL;
static HANDLE      g_watcher = NULL;
static HANDLE      g_sampler = NULL;
static BOOL        g_hooked = FALSE;

typedef void  (__fastcall *fn_plain)(void *self, const void *method);
typedef void  (__fastcall *fn_unit_int_bool)(void *self, int value, int check_min_max,
                                             const void *method);
typedef int   (__fastcall *fn_unit_get_int)(void *self, const void *method);
typedef void  (__fastcall *fn_action_int)(void *self, int timing, const void *method);
typedef float (__fastcall *fn_damage)(void *self, void *action, void *coin, void *attacker,
                                      int8_t is_critical, const void *method);
typedef void  (__fastcall *fn_stage_stat)(void *self, void *external_data, void *format,
                                          const void *method);
typedef void  (__fastcall *fn_plain_arg1)(void *self, void *a1, const void *method);
typedef int   (__fastcall *fn_unit_int3)(void *self, int a1, int a2, int a3,
                                         const void *method);

static void  *g_target[BW_MAX_HOOKS];
static void  *g_original[BW_MAX_HOOKS];
static LONG   g_kind[BW_MAX_HOOKS];
static BOOL   g_active[BW_MAX_HOOKS];

/* 去重缓存（只给 GET_INT 用，避免热路径上刷爆环形缓冲） */
#define BW_DEDUP_SLOTS 64
static struct {
    uintptr_t unit;
    int value;
} g_dedup[BW_DEDUP_SLOTS];
static int g_dedup_next = 0;

/* ------------------------------------------------------------------ */
/* 安全读取 / 事件输出                                                */
/* ------------------------------------------------------------------ */

static BOOL safe_read(void *addr, void *buf, SIZE_T n)
{
    SIZE_T rd = 0;
    if (!addr)
        return FALSE;
    return ReadProcessMemory(GetCurrentProcess(), addr, buf, n, &rd) && rd == n;
}

static BOOL read_i32(void *base, long off, int *out)
{
    if (off <= 0 || !base)
        return FALSE;
    return safe_read((char *)base + off, out, 4);
}

static uint64_t read_ptr(void *base, long off)
{
    uint64_t p = 0;
    if (off <= 0 || !base)
        return 0;
    if (!safe_read((char *)base + off, &p, 8))
        return 0;
    if (p < 0x10000000000ULL || (p & 7) != 0)
        return 0;
    return p;
}

/* 带成功标志的版本：读失败返回 FALSE（区分“真的是 0”与“没读到”）*/
static BOOL read_obscured_int_ex(void *addr, int *out, int *fake_out)
{
    int key = 0, hidden = 0, fake = 0;
    if (out) *out = 0;
    if (fake_out) *fake_out = 0;
    if (!addr)
        return FALSE;
    if (!safe_read((char *)addr + OBI_KEY, &key, 4))
        return FALSE;
    if (!safe_read((char *)addr + OBI_HIDDEN, &hidden, 4))
        return FALSE;
    safe_read((char *)addr + OBI_FAKE, &fake, 4);
    if (fake_out) *fake_out = fake;
    if (out) *out = hidden ^ key;
    return TRUE;
}

static int read_obscured_int(void *addr, int *fake_out)
{
    int out = 0;
    if (!read_obscured_int_ex(addr, &out, fake_out))
        return 0;
    return out;
}

static void log_line(const char *line, BOOL event)
{
    LONG slot;
    size_t n = strlen(line);
    if (!g_cfg)
        return;
    if (n > BW_LOG_LINE_MAX)
        n = BW_LOG_LINE_MAX;
    if (event)
        g_cfg->event_count++;
    {
        size_t m = n < 127 ? n : 127;
        memcpy((char *)g_cfg->last_log, line, m);
        ((char *)g_cfg->last_log)[m] = '\0';
    }
    slot = g_cfg->log_head & (BW_LOG_RING_CAP - 1);
    memcpy(g_cfg->log_ring[slot], line, n + 1);
    InterlockedIncrement(&g_cfg->log_head);
}

static void emit(const char *line, BOOL event)
{
    if (g_cfg && g_cfg->observing && g_cfg->log)
        log_line(line, event);
}

static void bump_hit(int index)
{
    if (g_cfg && index >= 0 && index < BW_MAX_HOOKS)
        InterlockedIncrement(&g_cfg->hook_hits[index]);
}

/* ------------------------------------------------------------------ */
/* 语义事件                                                            */
/* ------------------------------------------------------------------ */

/* 读单位三个速度字段 + 身份，发 SPD；tag 用于区分是哪个钩子触发的。
 *
 * os/ow 是「速度 ×1000」的定点数（见文件头 v3 说明），这里同时算出整数速度 osi/owi；
 * 小数部分是游戏里同速单位的隐藏排序值，不是精度误差，别丢。 */
static int speed_to_int(int raw)
{
    if (raw < 0)
        return -1;              /* -1 = 未初始化哨兵（GetIntegerOf*Speed 会算成 0，但 0 会误导排查）*/
    return raw / (int)BW_SPEED_SCALE;
}

static void emit_unit_speed(void *unit, const char *tag)
{
    int iid = -1, oid = -1, os = -1, ow = -1, its = -1;
    char line[240];
    int n;

    if (!unit || !g_cfg)
        return;
    read_i32(unit, g_cfg->off_unit_instance_id, &iid);
    read_i32(unit, g_cfg->off_unit_origin_id, &oid);
    read_i32(unit, g_cfg->off_unit_origin_speed, &os);
    read_i32(unit, g_cfg->off_unit_overwrited_speed, &ow);
    read_i32(unit, g_cfg->off_unit_int_speed_turn, &its);

    n = _snprintf(line, sizeof(line) - 1,
                  "SPD tag=%s iid=%d oid=%d os=%d osi=%d ow=%d owi=%d its=%d",
                  tag, iid, oid, os, speed_to_int(os), ow, speed_to_int(ow), its);
    if (n < 0) n = 0;
    if (n > (int)sizeof(line) - 1) n = (int)sizeof(line) - 1;
    line[n] = '\0';
    emit(line, TRUE);
}

/* ---- 血量 / 理智（VAL）------------------------------------------------------
 *
 * 链路：unit[off_unit_state] → CharacterState{ _maxHp, _hp, _mp }（三个 ObscuredInt）。
 * `_mp` 就是理智(SP)：±45，负数 = 恐慌（成就「魔法少女的悲剧」）。
 * 去重表按 (单位指针, hp, mp) 记忆，值没变就不发 —— 否则一次攻击的每枚硬币
 * 都会调受击钩子，一发就是几十行。
 */
typedef struct {
    uintptr_t unit;
    int hp;
    int mp;
    int iid;                     /* 采样线程用它判断指针有没有被复用 */
    int oid;
    int buff_count;              /* 上次看到的 buff 总数（列表大小；-1 = 链读不到）*/
    unsigned int buff_mask;
    DWORD diag_tick;             /* BUFDIAG 节流用 */
    BOOL used;
} BW_VITAL_ENTRY;

static BW_VITAL_ENTRY g_vital[BW_VITAL_SLOTS];
static BOOL g_cfg_logged = FALSE;   /* 配置回读只打一次 */

static void read_unit_vitals(void *unit, int *hp, int *mhp, int *mp)
{
    uint64_t state = 0;
    *hp = *mhp = *mp = BW_VITAL_UNREAD;
    if (!unit || !g_cfg)
        return;
    state = read_ptr(unit, g_cfg->off_unit_state);
    if (!state)
        return;
    read_obscured_int_ex((void *)(uintptr_t)(state + g_cfg->off_state_hp), hp, NULL);
    read_obscured_int_ex((void *)(uintptr_t)(state + g_cfg->off_state_max_hp), mhp, NULL);
    read_obscured_int_ex((void *)(uintptr_t)(state + g_cfg->off_state_mp), mp, NULL);
}

/* ---- buff（BUF）-------------------------------------------------------------
 *
 * 链路：unit[off_unit_buff_detail] → BuffDetail[off_buff_detail_list] : List<BuffModel>
 *       List.items(0x10) / List.size(0x18) → BuffModel[off_buff_model_data]
 *       → BuffStaticData[off_buff_static_id] : string（如 "HanafudaTwo"）
 *
 * il2cpp 容器布局（固定，不放配置）：
 *   List<T> : +0x10 items 指针, +0x18 size      （Array : +0x18 长度, +0x20 元素）
 *   string  : +0x10 长度(int32), +0x14 utf16 字符
 *
 * 只看配置里登记的**关注 buff**（Python 把名字 FNV-1a 64 后写进 buff_watch_hashes）：
 * 没登记任何关注表时提前返回，连链都不读 → 不加 buff 类成就时零开销。
 * 命中结果报成位掩码 m（第 i 位 = 命中关注表第 i 项），去重同 VAL（值（含掩码）变化才发）。
 */

static unsigned long long fnv1a64(const char *s, int len)
{
    unsigned long long h = 0xCBF29CE484222325ULL;   /* FNV-1a 64 offset basis */
    int i;
    for (i = 0; i < len; i++) {
        h ^= (unsigned char)s[i];
        h *= 0x100000001B3ULL;                       /* FNV-1a 64 prime */
    }
    return h;
}

/* 读 il2cpp string 到 buf（ASCII 取低字节；返回字符数，失败返回 0）*/
static int read_il2cpp_string(uint64_t str_ptr, char *buf, int max_len)
{
    int32_t len = 0;
    int i, take;
    if (!str_ptr || max_len <= 1)
        return 0;
    if (!safe_read((char *)(uintptr_t)(str_ptr + 0x10), &len, 4))
        return 0;
    if (len <= 0 || len > 256)
        return 0;
    take = len < (max_len - 1) ? len : (max_len - 1);
    for (i = 0; i < take; i++) {
        uint16_t ch = 0;
        if (!safe_read((char *)(uintptr_t)(str_ptr + 0x14 + 2 * i), &ch, 2))
            break;
        buf[i] = (char)(ch & 0xFF);
    }
    buf[i] = '\0';
    return i;
}

/* 读单位的关注 buff 命中掩码（没命中/没配关注表返回 0）
 *
 * ``out_count``：本次看到的 buff **总数**（列表大小）。链读不到时给 -1 ——
 * 有了它才能区分"身上没有我们关注的 buff"（`m=0 n=3`）和"整条链读不到"
 * （`m=0 n=-1`），排查时不用再猜。可以为 NULL。
 */
static unsigned int read_unit_buff_mask(void *unit, int *out_count,
                                           char *ids_out, int ids_len)
{
    uint64_t detail = 0, list = 0, items = 0, model = 0, data = 0, sid = 0;
    int32_t count = 0;
    unsigned int mask = 0;
    int i, j;
    char name[64];

    if (out_count)
        *out_count = -1;
    if (ids_out && ids_len > 0)
        ids_out[0] = '\0';
    if (!unit || !g_cfg)
        return 0;
    if (g_cfg->buff_watch_count <= 0)
        return 0;                                    /* 没成就用 buff → 不读 */
    detail = read_ptr(unit, g_cfg->off_unit_buff_detail);
    if (!detail)
        return 0;
    list = read_ptr((void *)(uintptr_t)detail, g_cfg->off_buff_detail_list);
    if (!list)
        return 0;
    if (!safe_read((char *)(uintptr_t)(list + 0x10), &items, 8))
        return 0;
    if (!safe_read((char *)(uintptr_t)(list + 0x18), &count, 4))
        return 0;
    if (out_count)
        *out_count = (count < 0 || count > BW_BUFF_LIST_MAX) ? -1 : (int)count;
    if (!items || count <= 0 || count > BW_BUFF_LIST_MAX)
        return 0;
    for (i = 0; i < count; i++) {
        uint64_t elem = 0;
        unsigned long long h;
        if (!safe_read((char *)(uintptr_t)(items + 0x20 + 8 * i), &elem, 8) || !elem)
            continue;
        model = elem;
        data = read_ptr((void *)(uintptr_t)model, g_cfg->off_buff_model_data);
        if (!data)
            continue;
        if (!safe_read((char *)(uintptr_t)(data + g_cfg->off_buff_static_id), &sid, 8) || !sid)
            continue;
        if (read_il2cpp_string(sid, name, (int)sizeof(name)) <= 0)
            continue;
        h = fnv1a64(name, (int)strlen(name));
        /* 诊断用：把前几个 buff 名带出去，方便和关注表对照（读不到就说明链/字段不对）*/
        if (ids_out && ids_len > 0 && strlen(ids_out) < (size_t)(ids_len - 48)) {
            if (ids_out[0])
                strncat(ids_out, "|", (size_t)ids_len - strlen(ids_out) - 1);
            strncat(ids_out, name, (size_t)ids_len - strlen(ids_out) - 1);
        }
        for (j = 0; j < g_cfg->buff_watch_count && j < BW_BUFF_WATCH_MAX; j++) {
            if (g_cfg->buff_watch_hashes[j] == h) {
                mask |= (1u << j);
                break;
            }
        }
    }
    return mask;
}

/* buff 链诊断（每个单位最多 20s 打一行）：链读不到 / 读到但一个都没命中关注表时，
 * 把 n、掩码和前几个 buff 名打出来 —— 这是"buff 检测一个都不生效"唯一能定案的办法。*/
static void maybe_emit_bufdiag(void *unit, int iid, int oid, int count, unsigned int mask,
                               const char *ids)
{
    uintptr_t key = (uintptr_t)unit;
    int slot = (int)((key >> 4) % BW_VITAL_SLOTS);
    int i;
    DWORD now = GetTickCount();
    char line[320];
    int n;

    if (count > 0 && mask != 0)
        return;                                   /* 正常命中 → 不用诊断 */
    for (i = 0; i < 4; i++) {
        int idx = (slot + i) % BW_VITAL_SLOTS;
        if (g_vital[idx].used && g_vital[idx].unit == key) {
            if (g_vital[idx].diag_tick && now - g_vital[idx].diag_tick < 20000)
                return;
            g_vital[idx].diag_tick = now;
            break;
        }
    }
    n = _snprintf(line, sizeof(line) - 1, "BUFDIAG iid=%d oid=%d n=%d m=%u ids=%s",
                  iid, oid, count, mask, ids && ids[0] ? ids : "(none)");
    if (n < 0) n = 0;
    if (n > (int)sizeof(line) - 1) n = (int)sizeof(line) - 1;
    line[n] = '\0';
    emit(line, TRUE);
}

static void emit_unit_buffs(void *unit, const char *tag)
{
    int iid = -1, oid = -1, count = -1;
    unsigned int mask;
    uintptr_t key;
    int slot, i, n;
    char line[200];
    char ids[160];

    if (!unit || !g_cfg || g_cfg->buff_watch_count <= 0)
        return;
    mask = read_unit_buff_mask(unit, &count, ids, (int)sizeof(ids));
    read_i32(unit, g_cfg->off_unit_instance_id, &iid);
    read_i32(unit, g_cfg->off_unit_origin_id, &oid);
    maybe_emit_bufdiag(unit, iid, oid, count, mask, ids);

    key = (uintptr_t)unit;
    slot = (int)((key >> 4) % BW_VITAL_SLOTS);
    for (i = 0; i < 8; i++) {
        int idx = (slot + i) % BW_VITAL_SLOTS;
        if (g_vital[idx].used && g_vital[idx].unit == key) {
            /* 掩码或总数有一个变了就发：只比掩码的话，mask 恒为 0 的单位
             * （链读不到 / 身上没有关注 buff）永远不会有输出，排查时两眼一抹黑。*/
            if (g_vital[idx].buff_mask == mask && g_vital[idx].buff_count == count)
                return;
            g_vital[idx].buff_mask = mask;
            g_vital[idx].buff_count = count;
            g_vital[idx].iid = iid;
            g_vital[idx].oid = oid;
            break;
        }
        if (!g_vital[idx].used) {
            g_vital[idx].used = TRUE;
            g_vital[idx].unit = key;
            g_vital[idx].buff_mask = mask;
            g_vital[idx].buff_count = count;
            g_vital[idx].iid = iid;
            g_vital[idx].oid = oid;
            break;
        }
    }
    n = _snprintf(line, sizeof(line) - 1, "BUF tag=%s iid=%d oid=%d m=%u n=%d",
                  tag, iid, oid, mask, count);
    if (n < 0) n = 0;
    if (n > (int)sizeof(line) - 1) n = (int)sizeof(line) - 1;
    line[n] = '\0';
    emit(line, TRUE);
}

static void emit_unit_vitals(void *unit, const char *tag)
{
    int iid = -1, oid = -1, hp = BW_VITAL_UNREAD, mhp = BW_VITAL_UNREAD, mp = BW_VITAL_UNREAD;
    uintptr_t key;
    int slot, i, n;
    char line[200];

    if (!unit || !g_cfg)
        return;
    read_i32(unit, g_cfg->off_unit_instance_id, &iid);
    read_i32(unit, g_cfg->off_unit_origin_id, &oid);
    read_unit_vitals(unit, &hp, &mhp, &mp);
    if (hp == BW_VITAL_UNREAD && mp == BW_VITAL_UNREAD)
        return;                       /* 完全没读到就不发，减小噪声 */

    key = (uintptr_t)unit;
    slot = (int)((key >> 4) % BW_VITAL_SLOTS);
    for (i = 0; i < 8; i++) {
        int idx = (slot + i) % BW_VITAL_SLOTS;
        if (g_vital[idx].used && g_vital[idx].unit == key) {
            if (g_vital[idx].hp == hp && g_vital[idx].mp == mp)
                return;               /* 值没变：不发 */
            g_vital[idx].hp = hp;
            g_vital[idx].mp = mp;
            g_vital[idx].iid = iid;
            g_vital[idx].oid = oid;
            break;
        }
        if (!g_vital[idx].used) {
            g_vital[idx].used = TRUE;
            g_vital[idx].unit = key;
            g_vital[idx].hp = hp;
            g_vital[idx].mp = mp;
            g_vital[idx].iid = iid;
            g_vital[idx].oid = oid;
            break;
        }
    }
    n = _snprintf(line, sizeof(line) - 1,
                  "VAL tag=%s iid=%d oid=%d hp=%d mhp=%d mp=%d",
                  tag, iid, oid, hp, mhp, mp);
    if (n < 0) n = 0;
    if (n > (int)sizeof(line) - 1) n = (int)sizeof(line) - 1;
    line[n] = '\0';
    emit(line, TRUE);
}

/* 读 action 的 actor/cmd/技能，发 ACT；fallback_actor_oid 用不到时传 -1 */
/* 轮询"已通关关卡列表"（采样线程调用）。
 *
 * 数据链：缓存的 UserStageClearInfoData* →[off_stage_clear_list] StageClearInfoList
 *         →[off_clear_info_list] List<StageClearInfo> → 每项 [off_clear_info_id] = 关卡 id
 *
 * 只在**命中关注表**时发 CLR，且每个关注槽**只报一次**（stage_seen_mask）——
 * 否则 250ms 一轮 × 几百条记录会把 512 行环形缓冲刷爆。
 * 这正是"不打那些关卡也能判定"的实现：存档里的旧记录一样会被报上来。
 */
/* 关注表命中判定：允许"十进制前缀"匹配（watch=1004 命中 1004、100401、1004012…）。
 * 关卡 id 的确切格式各模式不一（主线/迷宫/铁路都不同），用前缀能让 Python 端
 * 先写"章节-节"的粗粒度目标，实测后再收紧，不必先猜准完整 id。*/
static BOOL id_matches_watch(int id, int watch)
{
    int v = id;
    int i;
    if (watch <= 0 || id <= 0)
        return FALSE;
    for (i = 0; i < 4; i++) {
        if (v == watch)
            return TRUE;
        v /= 10;
        if (v < watch)
            return FALSE;
    }
    return FALSE;
}

static void poll_stage_clears(void)
{
    uint64_t data, list, items = 0;
    int32_t count = 0, i, j;
    int any_hit = 0;

    if (!g_cfg || g_cfg->stage_watch_count <= 0)
        return;
    if (g_cfg->off_stage_clear_list <= 0 || g_cfg->off_clear_info_list <= 0 ||
        g_cfg->off_clear_info_id <= 0)
        return;
    data = (uint64_t)g_cfg->stage_clear_data;
    if (!data)
        return;                                   /* 还没抓到对象（存档没载入过）*/
    list = read_ptr((void *)(uintptr_t)data, g_cfg->off_stage_clear_list);
    if (!list)
        return;
    list = read_ptr((void *)(uintptr_t)list, g_cfg->off_clear_info_list);
    if (!list)
        return;
    if (!safe_read((char *)(uintptr_t)(list + 0x10), &items, 8) || !items)
        return;
    if (!safe_read((char *)(uintptr_t)(list + 0x18), &count, 4))
        return;
    if (count <= 0 || count > BW_CLEAR_LIST_MAX)
        return;                                   /* 脏数据就不碰 */

    for (i = 0; i < count; i++) {
        uint64_t elem = 0;
        int32_t id = 0;
        if (!safe_read((char *)(uintptr_t)(items + 0x20 + 8 * i), &elem, 8) || !elem)
            continue;
        if (!read_i32((void *)(uintptr_t)elem, g_cfg->off_clear_info_id, &id))
            continue;
        for (j = 0; j < g_cfg->stage_watch_count && j < BW_STAGE_WATCH_MAX; j++) {
            char line[96];
            if (!id_matches_watch((int)id, (int)g_cfg->stage_watch_ids[j]))
                continue;
            if (g_cfg->stage_seen_mask & (1L << j))
                break;                            /* 这个槽已经报过了 */
            g_cfg->stage_seen_mask |= (1L << j);
            any_hit = 1;
            _snprintf(line, sizeof(line) - 1, "CLR stage=%d cleared=1", (int)id);
            line[sizeof(line) - 1] = '\0';
            emit(line, TRUE);
            break;
        }
    }

    /* 一次性诊断：关注表一个都没命中时，把扫到的前几个关卡 id 原样打出来
     * （CLRD ids=…）—— 这样一次就能确定真实 id 格式，不用反复猜前缀。*/
    if (!any_hit && !g_cfg->stage_diag_done) {
        char buf[160];
        int used;
        g_cfg->stage_diag_done = 1;
        used = _snprintf(buf, sizeof(buf) - 1, "CLRD n=%d ids=", (int)count);
        if (used < 0)
            used = 0;
        for (i = 0; i < count && i < 6 && used < (int)sizeof(buf) - 12; i++) {
            uint64_t elem = 0;
            int32_t id = 0;
            int wrote;
            if (!safe_read((char *)(uintptr_t)(items + 8 * i), &elem, 8) || !elem)
                continue;
            if (!read_i32((void *)(uintptr_t)elem, g_cfg->off_clear_info_id, &id))
                continue;
            wrote = _snprintf(buf + used, sizeof(buf) - 1 - (size_t)used, "%d|", (int)id);
            if (wrote > 0)
                used += wrote;
        }
        buf[sizeof(buf) - 1] = '\0';
        emit(buf, TRUE);
    }
}

/* 上报一个已通关节点（(章,小节,节点) 去重；与界面查询那条路共用去重表）。
 * ``idx`` = 本节点在本章内的序号（跨小节累加）—— 界面上的 "10-4" 说的是它，
 * 而不是 ``node_id``（那是关卡 id，10438 这种，跟"第几关"无关）。*/
static void emit_ncl(int main_id, int sub_id, int node_id, int ct, int cn,
                     int idx, int sub_idx)
{
    int packed;
    int i;
    char line[160];

    if (!g_cfg)
        return;
    packed = (main_id % 1000) * 1000000 + (sub_id % 1000) * 1000 + (node_id % 1000);
    for (i = 0; i < g_cfg->ncl_seen_count && i < BW_NCL_SEEN_MAX; i++) {
        if (g_cfg->ncl_seen[i] == packed)
            return;                                  /* 报过了 */
    }
    if (g_cfg->ncl_seen_count < BW_NCL_SEEN_MAX) {
        g_cfg->ncl_seen[g_cfg->ncl_seen_count] = packed;
        g_cfg->ncl_seen_count += 1;
    }
    _snprintf(line, sizeof(line) - 1,
              "NCL main=%d sub=%d node=%d cleared=1 ct=%d cn=%d idx=%d sidx=%d",
              main_id, sub_id, node_id, ct, cn, idx, sub_idx);
    line[sizeof(line) - 1] = '\0';
    emit(line, TRUE);
}

/* 遍历存档全量进度树（采样线程）。
 *
 * 数据链：BWK_CACHE_ARG1 抓到的 List<MainChapterStateFormat>
 *   章 [id 0x10][off_chapter_subs 小节列表]
 *     → 小节 [id 0x10][off_sub_nodes 节点列表]
 *       → 节点 [off_node_id][off_node_clear_type ct][off_node_clear_number cn]
 *
 * **这就是"不点任何界面也能判定"的正解**：这棵树登录时全量下发、一直躺在内存里；
 * 之前挂的 IsNodeCleared 只在界面渲染时调用，实测连第十章都没查过一次。
 */
static void poll_stage_progress(void)
{
    uint64_t root, ch_items = 0, sub_list, sub_items = 0, node_list, node_items = 0;
    int32_t n_ch = 0, n_sub = 0, n_node = 0, i, j, k;

    if (!g_cfg || !g_cfg->observing)
        return;
    root = (uint64_t)g_cfg->stage_progress_list;
    if (!root || g_cfg->off_chapter_subs <= 0 || g_cfg->off_sub_nodes <= 0 ||
        g_cfg->off_node_id <= 0)
        return;
    if (!safe_read((char *)(uintptr_t)(root + 0x10), &ch_items, 8) || !ch_items)
        return;
    if (!safe_read((char *)(uintptr_t)(root + 0x18), &n_ch, 4))
        return;
    if (n_ch <= 0 || n_ch > BW_PROGRESS_MAX)
        return;

    for (i = 0; i < n_ch; i++) {
        uint64_t chapter = 0;
        int32_t chapter_id = 0;
        int32_t node_index = 0;      /* 本章第几个节点（界面上的 "10-4" 的 4）*/
        if (!safe_read((char *)(uintptr_t)(ch_items + 0x20 + 8 * i), &chapter, 8) || !chapter)
            continue;
        (void)read_i32((void *)(uintptr_t)chapter, 0x10, &chapter_id);
        sub_list = read_ptr((void *)(uintptr_t)chapter, g_cfg->off_chapter_subs);
        if (!sub_list)
            continue;
        sub_items = 0;
        n_sub = 0;
        if (!safe_read((char *)(uintptr_t)(sub_list + 0x10), &sub_items, 8) || !sub_items)
            continue;
        if (!safe_read((char *)(uintptr_t)(sub_list + 0x18), &n_sub, 4))
            continue;
        if (n_sub <= 0 || n_sub > BW_PROGRESS_MAX)
            continue;

        for (j = 0; j < n_sub; j++) {
            uint64_t sub = 0;
            int32_t sub_id = 0;
            if (!safe_read((char *)(uintptr_t)(sub_items + 0x20 + 8 * j), &sub, 8) || !sub)
                continue;
            (void)read_i32((void *)(uintptr_t)sub, 0x10, &sub_id);
            node_list = read_ptr((void *)(uintptr_t)sub, g_cfg->off_sub_nodes);
            if (!node_list)
                continue;
            node_items = 0;
            n_node = 0;
            if (!safe_read((char *)(uintptr_t)(node_list + 0x10), &node_items, 8) || !node_items)
                continue;
            if (!safe_read((char *)(uintptr_t)(node_list + 0x18), &n_node, 4))
                continue;
            if (n_node <= 0 || n_node > 512)
                continue;

            for (k = 0; k < n_node; k++) {
                uint64_t node = 0;
                int32_t node_id = 0, ct = 0, cn = 0;
                if (!safe_read((char *)(uintptr_t)(node_items + 0x20 + 8 * k), &node, 8) || !node)
                    continue;
                if (!read_i32((void *)(uintptr_t)node, g_cfg->off_node_id, &node_id))
                    continue;
                node_index += 1;         /* 关卡 id 不等于"第几关"，序号才是界面上那个号 */
                if (g_cfg->off_node_clear_type > 0)
                    (void)read_i32((void *)(uintptr_t)node, g_cfg->off_node_clear_type, &ct);
                if (g_cfg->off_node_clear_number > 0)
                    (void)read_i32((void *)(uintptr_t)node, g_cfg->off_node_clear_number, &cn);
                if (ct <= 0 && cn <= 0)
                    continue;                        /* 没通关的不报 */
                /* 只报关注表里的章（**章号精确匹配，只看 chapter_id**）。
                 * 不能顺带做小节/节点的前缀匹配：关注 "10" 时 sub 104 / node 10401 也会命中，
                 * 实测就把第 1 章的几十个节点全刷出来了。*/
                if (g_cfg->stage_watch_count > 0) {
                    int watched = 0;
                    int wi;
                    for (wi = 0; wi < g_cfg->stage_watch_count && wi < BW_STAGE_WATCH_MAX; wi++) {
                        if ((int)chapter_id == (int)g_cfg->stage_watch_ids[wi]) {
                            watched = 1;
                            break;
                        }
                    }
                    if (!watched)
                        continue;
                }
                emit_ncl((int)chapter_id, (int)sub_id, (int)node_id, (int)ct, (int)cn,
                         (int)node_index, (int)(j + 1));
            }
        }
    }
}

/* 采样线程：把已经见过的单位每 BW_SAMPLE_MS 重读一次 hp / sp / buff。
 *
 * 为什么必须有它：我们只能在自己挂上的函数被调用时读值，而受击钩子
 * （GetTakeAttackDmgMultiplier）是在**算伤害的当下**进的 —— 那一刻 hp 还没扣、
 * buff 也还没上，所以"打到身上"造成的血量/理智/buff 变化要等下一个单位级钩子
 * （通常就是回合开始）才被看见，表现就是"血量/理智/buff 要等回合结束才结算"。
 * 这里按固定节奏重采样：值一变就发 VAL/BUF（去重表保证只在变化时发），
 * 驱动侧本来就是**即时判定**，于是全链路都变成实时的。
 *
 * 只读：safe_read 全程带边界校验；指针被复用（iid/oid 变了）就丢弃该槽位。
 */
static DWORD WINAPI sampler_thread(LPVOID unused)
{
    int i;
    (void)unused;
    for (;;) {
        if (WaitForSingleObject(g_stop_event, BW_SAMPLE_MS) == WAIT_OBJECT_0)
            break;
        if (!g_cfg || !g_cfg->observing || !g_cfg->installed)
            continue;
        poll_stage_clears();      /* 已通关关卡列表（存档回溯判定）*/
        poll_stage_progress();    /* 全量进度树（不点界面也能判定）*/
        for (i = 0; i < BW_VITAL_SLOTS; i++) {
            void *unit;
            int iid = -1, oid = -1;
            if (!g_vital[i].used)
                continue;
            unit = (void *)g_vital[i].unit;
            if (!read_i32(unit, g_cfg->off_unit_instance_id, &iid) ||
                !read_i32(unit, g_cfg->off_unit_origin_id, &oid)) {
                g_vital[i].used = FALSE;        /* 读不到 → 对象已经没了 */
                continue;
            }
            if (g_vital[i].iid > 0 && iid > 0 && g_vital[i].iid != iid) {
                g_vital[i].used = FALSE;        /* 指针被复用成别的单位 */
                continue;
            }
            if (g_vital[i].oid > 0 && oid > 0 && g_vital[i].oid != oid) {
                g_vital[i].used = FALSE;
                continue;
            }
            emit_unit_vitals(unit, "sampler");
            emit_unit_buffs(unit, "sampler");
        }
    }
    return 0;
}

static void emit_action_skill(void *action, int actor_oid_hint, const char *tag)
{
    int actor = -1, cmd = -1, fake = 0, skid = -1, tier = -1, tfake = 0;
    uint64_t skill = 0, sdata = 0;
    char line[240];
    int n;

    if (!action || !g_cfg)
        return;
    read_i32(action, g_cfg->off_action_actor_id, &actor);
    read_i32(action, g_cfg->off_action_commander_id, &cmd);
    skill = read_ptr(action, g_cfg->off_action_skill);
    if (skill)
        sdata = read_ptr((void *)(uintptr_t)skill, g_cfg->off_skill_data);
    if (sdata) {
        skid = read_obscured_int((void *)((char *)(uintptr_t)sdata + g_cfg->off_skill_id), &fake);
        tier = read_obscured_int((void *)((char *)(uintptr_t)sdata + g_cfg->off_skill_tier), &tfake);
    }

    n = _snprintf(line, sizeof(line) - 1,
                  "ACT tag=%s actor=%d cmd=%d skid=%d slot=%d tier=%d tf=%d aoid=%d",
                  tag, actor, cmd, skid, (skid >= 0 ? (skid % 100) : -1), tier, tfake,
                  actor_oid_hint);
    if (n < 0) n = 0;
    if (n > (int)sizeof(line) - 1) n = (int)sizeof(line) - 1;
    line[n] = '\0';
    emit(line, TRUE);
}

/* ------------------------------------------------------------------ */
/* detour 表                                                          */
/* ------------------------------------------------------------------ */

static void __fastcall hk_plain(void *self, const void *method)
{
    (void)self;
    (void)method;
}

/* kind 分派：为了简单，每个 kind 用独立的静态变量记录"当前是第几个钩子"不现实，
 * 所以用 12 个显式 thunk 走同一实现（见下）。 */
typedef void (__fastcall *detour_fn)(void);

#define DEF_UNIT_THUNK(N)                                                        \
    static void __fastcall hk_unit_##N(void *self, const void *method)           \
    {                                                                            \
        bump_hit(N);                                                             \
        ((fn_plain)g_original[N])(self, method);                                 \
        if (g_cfg && g_cfg->observing) {                                         \
            emit_unit_speed(self, (const char *)g_cfg->hook_name[N]);            \
            emit_unit_vitals(self, (const char *)g_cfg->hook_name[N]);           \
            emit_unit_buffs(self, (const char *)g_cfg->hook_name[N]);            \
        }                                                                        \
    }

#define DEF_UNIT_IB_THUNK(N)                                                     \
    static void __fastcall hk_unit_ib_##N(void *self, int value, int cm,         \
                                          const void *method)                    \
    {                                                                            \
        bump_hit(N);                                                             \
        ((fn_unit_int_bool)g_original[N])(self, value, cm, method);              \
        if (g_cfg && g_cfg->observing) {                                         \
            emit_unit_speed(self, (const char *)g_cfg->hook_name[N]);            \
            emit_unit_vitals(self, (const char *)g_cfg->hook_name[N]);           \
            emit_unit_buffs(self, (const char *)g_cfg->hook_name[N]);            \
        }                                                                        \
    }

#define DEF_UNIT_GI_THUNK(N)                                                     \
    static int __fastcall hk_unit_gi_##N(void *self, const void *method)         \
    {                                                                            \
        int result;                                                              \
        bump_hit(N);                                                             \
        result = ((fn_unit_get_int)g_original[N])(self, method);                 \
        if (g_cfg && g_cfg->observing && self) {                                 \
            int iid = -1, oid = -1;                                              \
            uintptr_t unit = (uintptr_t)self;                                    \
            int i;                                                               \
            read_i32(self, g_cfg->off_unit_instance_id, &iid);                   \
            read_i32(self, g_cfg->off_unit_origin_id, &oid);                     \
            for (i = 0; i < BW_DEDUP_SLOTS; i++) {                               \
                if (g_dedup[i].unit == unit && g_dedup[i].value == result)       \
                    return result;                                               \
            }                                                                    \
            g_dedup[g_dedup_next % BW_DEDUP_SLOTS].unit = unit;                  \
            g_dedup[g_dedup_next % BW_DEDUP_SLOTS].value = result;               \
            g_dedup_next++;                                                      \
            {                                                                    \
                char line[160];                                                  \
                _snprintf(line, sizeof(line) - 1,                                \
                          "SPD tag=%s iid=%d oid=%d eff=%d",                     \
                          (const char *)g_cfg->hook_name[N], iid, oid, result);  \
                line[sizeof(line) - 1] = '\0';                                   \
                emit(line, TRUE);                                                \
                emit_unit_vitals(self, (const char *)g_cfg->hook_name[N]);        \
                emit_unit_buffs(self, (const char *)g_cfg->hook_name[N]);         \
            }                                                                    \
        }                                                                        \
        return result;                                                           \
    }

#define DEF_ACTION_THUNK(N)                                                      \
    static void __fastcall hk_action_##N(void *self, int timing, const void *m)  \
    {                                                                            \
        bump_hit(N);                                                             \
        ((fn_action_int)g_original[N])(self, timing, m);                         \
        if (g_cfg && g_cfg->observing)                                           \
            emit_action_skill(self, -1, (const char *)g_cfg->hook_name[N]);      \
    }

#define DEF_DAMAGE_THUNK(N)                                                      \
    static float __fastcall hk_damage_##N(void *self, void *action, void *coin,  \
                                          void *attacker, int8_t crit,           \
                                          const void *method)                    \
    {                                                                            \
        float value = ((fn_damage)g_original[N])(self, action, coin, attacker,   \
                                                 crit, method);                  \
        int aoid = -1;                                                           \
        bump_hit(N);                                                             \
        if (g_cfg && g_cfg->observing) {                                         \
            if (attacker)                                                        \
                read_i32(attacker, g_cfg->off_unit_origin_id, &aoid);            \
            emit_action_skill(action, aoid, (const char *)g_cfg->hook_name[N]);  \
            emit_unit_vitals(self, (const char *)g_cfg->hook_name[N]);           \
            emit_unit_buffs(self, (const char *)g_cfg->hook_name[N]);            \
        }                                                                        \
        return value;                                                            \
    }

#define DEF_PLAIN_THUNK(N)                                                       \
    static void __fastcall hk_plain_##N(void *self, const void *method)          \
    {                                                                            \
        char line[96];                                                           \
        bump_hit(N);                                                             \
        ((fn_plain)g_original[N])(self, method);                                 \
        if (g_cfg && g_cfg->observing) {                                         \
            _snprintf(line, sizeof(line) - 1, "RND tag=%s",                      \
                      (const char *)g_cfg->hook_name[N]);                        \
            line[sizeof(line) - 1] = '\0';                                        \
            emit(line, TRUE);                                                    \
        }                                                                        \
    }

/* 表现层动画 tick：签名跟 plain 一样（void(self, mi)），额外读 self 上的
 * _attackerInstanceID，让事件带上“这手是谁在打”。读不到 / 值离谱就发 -1。*/
#define DEF_SKV_THUNK(N)                                                         \
    static void __fastcall hk_skv_##N(void *self, const void *method)            \
    {                                                                            \
        char line[96];                                                           \
        int iid = -1;                                                            \
        bump_hit(N);                                                             \
        ((fn_plain)g_original[N])(self, method);                                 \
        if (g_cfg && g_cfg->observing) {                                         \
            if (self && g_cfg->off_skv_attacker_iid > 0)                         \
                read_i32(self, g_cfg->off_skv_attacker_iid, &iid);               \
            if (iid < 0 || iid > 255)                                            \
                iid = -1;              /* 偏移不对 / 读失败 → 不下发髒值 */     \
            _snprintf(line, sizeof(line) - 1, "RND tag=%s iid=%d",               \
                      (const char *)g_cfg->hook_name[N], iid);                   \
            line[sizeof(line) - 1] = '\0';                                        \
            emit(line, TRUE);                                                    \
        }                                                                        \
    }

/* ---- 关卡结算统计（BWK_STAGE_STAT）------------------------------------------
 * 挂钩 StageStatisticPopupData..ctor(self, externalData, format, mi)。
 * **必须先调原构造函数**：_slotDataList 是构造函数里填的，先读只会读到空列表。
 * 列表布局沿用 buff 链那套：IL2CPP 引用类型 List<T> 的 _items 在 +0x20、_size 在 +0x18。
 * 每个 slot 读 _uid（判断是哪条线）/ _clearTurn（通关回合数）/ _deadUnitCount / _exCleared。
 */
static void emit_stage_stat(void *self, const void *method, void *a1, void *a2,
                            void *original)
{
    uint64_t list, items = 0, slot, uid_ptr;
    int32_t count = 0, i;
    char uid[64];
    char line[192];

    if (original)
        ((fn_stage_stat)original)(self, a1, a2, method);   /* 先让构造函数把数据填好 */
    if (!self || !g_cfg || !g_cfg->observing)
        return;
    if (g_cfg->off_stage_slot_list <= 0)
        return;
    list = read_ptr(self, g_cfg->off_stage_slot_list);
    if (!list)
        return;
    if (!safe_read((char *)(uintptr_t)(list + 0x20), &items, 8) || !items)
        return;
    if (!safe_read((char *)(uintptr_t)(list + 0x18), &count, 4))
        return;
    if (count <= 0)
        return;
    if (count > BW_STAGE_SLOT_MAX)
        count = BW_STAGE_SLOT_MAX;

    for (i = 0; i < count; i++) {
        int32_t turn = -1, dead = -1;
        unsigned char ex = 0;
        uid[0] = '\0';
        if (!safe_read((char *)(uintptr_t)(items + 8 * i), &slot, 8) || !slot)
            continue;
        if (g_cfg->off_slot_clear_turn > 0)
            read_i32((void *)(uintptr_t)slot, g_cfg->off_slot_clear_turn, &turn);
        if (g_cfg->off_slot_dead_count > 0)
            read_i32((void *)(uintptr_t)slot, g_cfg->off_slot_dead_count, &dead);
        if (g_cfg->off_slot_ex_cleared > 0)
            safe_read((char *)(uintptr_t)(slot + g_cfg->off_slot_ex_cleared), &ex, 1);
        if (g_cfg->off_slot_uid > 0) {
            uid_ptr = read_ptr((void *)(uintptr_t)slot, g_cfg->off_slot_uid);
            if (uid_ptr)
                read_il2cpp_string(uid_ptr, uid, (int)sizeof(uid));
        }
        if (!uid[0] && turn < 0)
            continue;                       /* 什么都没读到就别发脏事件 */
        _snprintf(line, sizeof(line) - 1, "STG uid=%s turn=%d dead=%d ex=%d",
                  uid[0] ? uid : "?", (int)turn, (int)dead, ex ? 1 : 0);
        line[sizeof(line) - 1] = '\0';
        emit(line, TRUE);
    }
}

#define DEF_STAGE_THUNK(N)                                                       \
    static void __fastcall hk_stage_##N(void *self, void *a1, void *a2,          \
                                        const void *method)                      \
    {                                                                            \
        bump_hit(N);                                                             \
        emit_stage_stat(self, method, a1, a2, g_original[N]);                    \
    }

/* ---- 折射铁路总回合（BWK_RAILWAY_TOTAL）-------------------------------------
 * 挂钩 RailwayDungeonHistoryDataByCollection::GetTotalClearTurn()（无参、返回 int）。
 * 先把原函数的结果拿到手（**不能吞掉返回值**，UI 还等着它显示），再把
 * 线路号 + 总回合发出来。*/
static int __fastcall call_and_emit_railway_total(void *self, const void *method,
                                                  void *original)
{
    int total = 0;
    int line = -1;
    char line_buf[96];

    if (original)
        total = ((fn_unit_get_int)original)(self, method);
    if (g_cfg && g_cfg->observing && self) {
        if (g_cfg->off_railway_collection_id > 0)
            read_i32(self, g_cfg->off_railway_collection_id, &line);
        _snprintf(line_buf, sizeof(line_buf) - 1, "RWT line=%d total=%d", line, total);
        line_buf[sizeof(line_buf) - 1] = '\0';
        emit(line_buf, TRUE);
    }
    return total;
}

#define DEF_RAILWAY_THUNK(N)                                                     \
    static int __fastcall hk_railway_##N(void *self, const void *method)         \
    {                                                                            \
        bump_hit(N);                                                             \
        return call_and_emit_railway_total(self, method, g_original[N]);          \
    }

/* ---- 抓存档对象（BWK_CACHE_SELF）-------------------------------------------
 * 只把 self 存进配置（给采样线程轮询用），不发事件；原函数照常调用。*/
#define DEF_CACHE_THUNK(N)                                                       \
    static void __fastcall hk_cache_##N(void *self, void *a1, const void *method) \
    {                                                                            \
        bump_hit(N);                                                             \
        if (self && g_cfg)                                                       \
            g_cfg->stage_clear_data = (long long)(uintptr_t)self;                \
        if (g_original[N])                                                       \
            ((fn_plain_arg1)g_original[N])(self, a1, method);                    \
    }

/* ---- 关卡通关状态查询（BWK_NODE_STATE）-------------------------------------
 * int (self, int main, int sub, int node, mi)；返回值 = 通没通（bool / CLEARNODE_STATE）。
 * 章节号与节点号是入参，所以不需要去解析存档结构 —— 游戏自己问什么我们就记什么。
 * 只报"已通关"的，且按 (章,小节,节点) 去重（NCL 会被 UI 反复调用）。*/
static int __fastcall call_and_emit_node_state(void *self, int a1, int a2, int a3,
                                               const void *method, void *original)
{
    int ret = 0;
    int packed;
    int i;

    if (original)
        ret = ((fn_unit_int3)original)(self, a1, a2, a3, method);
    (void)self;
    if (!g_cfg || !g_cfg->observing || ret == 0)
        return ret;                       /* 没通关就不报（成就只关心"通了"）*/
    packed = (a1 % 1000) * 1000000 + (a2 % 1000) * 1000 + (a3 % 1000);
    for (i = 0; i < g_cfg->ncl_seen_count && i < BW_NCL_SEEN_MAX; i++) {
        if (g_cfg->ncl_seen[i] == packed)
            return ret;                   /* 报过了 */
    }
    if (g_cfg->ncl_seen_count < BW_NCL_SEEN_MAX) {
        g_cfg->ncl_seen[g_cfg->ncl_seen_count] = packed;
        g_cfg->ncl_seen_count += 1;
    }
    {
        char line[112];
        _snprintf(line, sizeof(line) - 1, "NCL main=%d sub=%d node=%d cleared=1",
                  a1, a2, a3);
        line[sizeof(line) - 1] = '\0';
        emit(line, TRUE);
    }
    return ret;
}

#define DEF_NODE_THUNK(N)                                                        \
    static int __fastcall hk_node_##N(void *self, int a1, int a2, int a3,        \
                                      const void *method)                        \
    {                                                                            \
        bump_hit(N);                                                             \
        return call_and_emit_node_state(self, a1, a2, a3, method, g_original[N]);\
    }

/* ---- 抓第一个参数（BWK_CACHE_ARG1）-----------------------------------------
 * 用途：UpdateData(List<MainChapterStateFormat>) 的 a1 就是整棵主线进度树。*/
#define DEF_CACHEARG_THUNK(N)                                                    \
    static void __fastcall hk_cachearg_##N(void *self, void *a1, const void *method) \
    {                                                                            \
        bump_hit(N);                                                             \
        if (a1 && g_cfg)                                                         \
            g_cfg->stage_progress_list = (long long)(uintptr_t)a1;               \
        if (g_original[N])                                                       \
            ((fn_plain_arg1)g_original[N])(self, a1, method);                    \
    }

/* ---- 折射铁路每节点回合（BWK_RAILWAY_NODE）---------------------------------
 * 挂钩 RailwayDungeonFormerSaveData::.ctor：**必须先调原构造函数**（nodeId/clearTurn
 * 是里面填的），再把两个字段读出来发 RWT。Python 侧按节点 id 记录，可求和成整条线总回合。*/
static void call_and_emit_railway_node(void *self, void *a1, const void *method,
                                       void *original)
{
    int node_id = -1, turn = -1;
    char line[96];

    if (original)
        ((fn_plain_arg1)original)(self, a1, method);   /* 先让构造函数填好字段 */
    if (!self || !g_cfg || !g_cfg->observing)
        return;
    if (g_cfg->off_railway_node_id > 0)
        (void)read_i32(self, g_cfg->off_railway_node_id, &node_id);
    if (g_cfg->off_railway_node_turn > 0)
        (void)read_i32(self, g_cfg->off_railway_node_turn, &turn);
    if (node_id <= 0 || turn < 0)
        return;                                        /* 没读出来就别发脏值 */
    _snprintf(line, sizeof(line) - 1, "RWT node=%d turn=%d", node_id, turn);
    line[sizeof(line) - 1] = '\0';
    emit(line, TRUE);
}

#define DEF_RAILWAYNODE_THUNK(N)                                                 \
    static void __fastcall hk_railn_##N(void *self, void *a1, const void *method) \
    {                                                                            \
        bump_hit(N);                                                             \
        call_and_emit_railway_node(self, a1, method, g_original[N]);             \
    }

/* ---- 折射铁路历史记录（BWK_RAILWAY_HIST）-----------------------------------
 * 9 个参数的构造函数（签名已从 dump.cs 确认）。arg4 = IList<int> clearTurns
 * 就是各节点的通关回合 —— 直接求和不依赖任何字段偏移，最稳。*/
typedef void (__fastcall *fn_railway_hist)(void *self, int collection_id, void *unit_infos,
                                           void *statistics, void *clear_turns,
                                           void *ally_buffs, void *enemy_buffs,
                                           void *line6_duel_logs, void *line6_choice_logs,
                                           void *override_types, const void *method);

static void call_and_emit_railway_hist(
    void *self, int collection_id, void *unit_infos, void *statistics, void *clear_turns,
    void *ally_buffs, void *enemy_buffs, void *line6_duel_logs, void *line6_choice_logs,
    void *override_types, const void *method, void *original)
{
    uint64_t items = 0;
    int32_t count = 0, i, total = 0;
    char line[112];

    if (original)
        ((fn_railway_hist)original)(self, collection_id, unit_infos, statistics, clear_turns,
                                    ally_buffs, enemy_buffs, line6_duel_logs,
                                    line6_choice_logs, override_types, method);
    if (!g_cfg || !g_cfg->observing || !clear_turns)
        return;
    if (!safe_read((char *)(uintptr_t)((uint64_t)clear_turns + 0x10), &items, 8) || !items)
        return;
    if (!safe_read((char *)(uintptr_t)((uint64_t)clear_turns + 0x18), &count, 4))
        return;
    if (count <= 0 || count > 256)
        return;
    for (i = 0; i < count; i++) {
        int32_t v = 0;
        if (!safe_read((char *)(uintptr_t)(items + 0x20 + 4 * i), &v, 4))
            break;
        if (v > 0)
            total += v;
    }
    _snprintf(line, sizeof(line) - 1, "RWT line=%d total=%d nodes=%d",
              collection_id, total, (int)count);
    line[sizeof(line) - 1] = '\0';
    emit(line, TRUE);
}

#define DEF_RAILWAYHIST_THUNK(N)                                                 \
    static void __fastcall hk_railhist_##N(                                      \
        void *self, int a1, void *a2, void *a3, void *a4, void *a5, void *a6,    \
        void *a7, void *a8, void *a9, const void *method)                        \
    {                                                                            \
        bump_hit(N);                                                             \
        call_and_emit_railway_hist(self, a1, a2, a3, a4, a5, a6, a7, a8, a9,     \
                                   method, g_original[N]);                       \
    }

DEF_PLAIN_THUNK(0)  DEF_PLAIN_THUNK(1)  DEF_PLAIN_THUNK(2)  DEF_PLAIN_THUNK(3)
DEF_PLAIN_THUNK(4)  DEF_PLAIN_THUNK(5)  DEF_PLAIN_THUNK(6)  DEF_PLAIN_THUNK(7)
DEF_PLAIN_THUNK(8)  DEF_PLAIN_THUNK(9)  DEF_PLAIN_THUNK(10) DEF_PLAIN_THUNK(11)

DEF_SKV_THUNK(0)    DEF_SKV_THUNK(1)    DEF_SKV_THUNK(2)    DEF_SKV_THUNK(3)
DEF_SKV_THUNK(4)    DEF_SKV_THUNK(5)    DEF_SKV_THUNK(6)    DEF_SKV_THUNK(7)
DEF_SKV_THUNK(8)    DEF_SKV_THUNK(9)    DEF_SKV_THUNK(10)   DEF_SKV_THUNK(11)

DEF_UNIT_THUNK(0)    DEF_UNIT_THUNK(1)    DEF_UNIT_THUNK(2)    DEF_UNIT_THUNK(3)
DEF_UNIT_THUNK(4)    DEF_UNIT_THUNK(5)    DEF_UNIT_THUNK(6)    DEF_UNIT_THUNK(7)
DEF_UNIT_THUNK(8)    DEF_UNIT_THUNK(9)    DEF_UNIT_THUNK(10)   DEF_UNIT_THUNK(11)
DEF_UNIT_IB_THUNK(0) DEF_UNIT_IB_THUNK(1) DEF_UNIT_IB_THUNK(2) DEF_UNIT_IB_THUNK(3)
DEF_UNIT_IB_THUNK(4) DEF_UNIT_IB_THUNK(5) DEF_UNIT_IB_THUNK(6) DEF_UNIT_IB_THUNK(7)
DEF_UNIT_IB_THUNK(8) DEF_UNIT_IB_THUNK(9) DEF_UNIT_IB_THUNK(10) DEF_UNIT_IB_THUNK(11)
DEF_UNIT_GI_THUNK(0) DEF_UNIT_GI_THUNK(1) DEF_UNIT_GI_THUNK(2) DEF_UNIT_GI_THUNK(3)
DEF_UNIT_GI_THUNK(4) DEF_UNIT_GI_THUNK(5) DEF_UNIT_GI_THUNK(6) DEF_UNIT_GI_THUNK(7)
DEF_UNIT_GI_THUNK(8) DEF_UNIT_GI_THUNK(9) DEF_UNIT_GI_THUNK(10) DEF_UNIT_GI_THUNK(11)
DEF_ACTION_THUNK(0)  DEF_ACTION_THUNK(1)  DEF_ACTION_THUNK(2)  DEF_ACTION_THUNK(3)
DEF_ACTION_THUNK(4)  DEF_ACTION_THUNK(5)  DEF_ACTION_THUNK(6)  DEF_ACTION_THUNK(7)
DEF_ACTION_THUNK(8)  DEF_ACTION_THUNK(9)  DEF_ACTION_THUNK(10) DEF_ACTION_THUNK(11)
DEF_DAMAGE_THUNK(0)  DEF_DAMAGE_THUNK(1)  DEF_DAMAGE_THUNK(2)  DEF_DAMAGE_THUNK(3)
DEF_DAMAGE_THUNK(4)  DEF_DAMAGE_THUNK(5)  DEF_DAMAGE_THUNK(6)  DEF_DAMAGE_THUNK(7)
DEF_DAMAGE_THUNK(8)  DEF_DAMAGE_THUNK(9)  DEF_DAMAGE_THUNK(10) DEF_DAMAGE_THUNK(11)

DEF_STAGE_THUNK(0)   DEF_STAGE_THUNK(1)   DEF_STAGE_THUNK(2)   DEF_STAGE_THUNK(3)
DEF_STAGE_THUNK(4)   DEF_STAGE_THUNK(5)   DEF_STAGE_THUNK(6)   DEF_STAGE_THUNK(7)
DEF_STAGE_THUNK(8)   DEF_STAGE_THUNK(9)   DEF_STAGE_THUNK(10)  DEF_STAGE_THUNK(11)

DEF_RAILWAY_THUNK(0) DEF_RAILWAY_THUNK(1) DEF_RAILWAY_THUNK(2) DEF_RAILWAY_THUNK(3)
DEF_RAILWAY_THUNK(4) DEF_RAILWAY_THUNK(5) DEF_RAILWAY_THUNK(6) DEF_RAILWAY_THUNK(7)
DEF_RAILWAY_THUNK(8) DEF_RAILWAY_THUNK(9) DEF_RAILWAY_THUNK(10) DEF_RAILWAY_THUNK(11)
DEF_RAILWAY_THUNK(12) DEF_RAILWAY_THUNK(13) DEF_RAILWAY_THUNK(14) DEF_RAILWAY_THUNK(15)

DEF_CACHE_THUNK(0)   DEF_CACHE_THUNK(1)   DEF_CACHE_THUNK(2)   DEF_CACHE_THUNK(3)
DEF_CACHE_THUNK(4)   DEF_CACHE_THUNK(5)   DEF_CACHE_THUNK(6)   DEF_CACHE_THUNK(7)
DEF_CACHE_THUNK(8)   DEF_CACHE_THUNK(9)   DEF_CACHE_THUNK(10)  DEF_CACHE_THUNK(11)
DEF_CACHE_THUNK(12)  DEF_CACHE_THUNK(13)  DEF_CACHE_THUNK(14)  DEF_CACHE_THUNK(15)

DEF_NODE_THUNK(0)    DEF_NODE_THUNK(1)    DEF_NODE_THUNK(2)    DEF_NODE_THUNK(3)
DEF_NODE_THUNK(4)    DEF_NODE_THUNK(5)    DEF_NODE_THUNK(6)    DEF_NODE_THUNK(7)
DEF_NODE_THUNK(8)    DEF_NODE_THUNK(9)    DEF_NODE_THUNK(10)   DEF_NODE_THUNK(11)
DEF_NODE_THUNK(12)   DEF_NODE_THUNK(13)   DEF_NODE_THUNK(14)   DEF_NODE_THUNK(15)
DEF_NODE_THUNK(16)   DEF_NODE_THUNK(17)   DEF_NODE_THUNK(18)   DEF_NODE_THUNK(19)

DEF_CACHEARG_THUNK(0)  DEF_CACHEARG_THUNK(1)  DEF_CACHEARG_THUNK(2)  DEF_CACHEARG_THUNK(3)
DEF_CACHEARG_THUNK(4)  DEF_CACHEARG_THUNK(5)  DEF_CACHEARG_THUNK(6)  DEF_CACHEARG_THUNK(7)
DEF_CACHEARG_THUNK(8)  DEF_CACHEARG_THUNK(9)  DEF_CACHEARG_THUNK(10) DEF_CACHEARG_THUNK(11)
DEF_CACHEARG_THUNK(12) DEF_CACHEARG_THUNK(13) DEF_CACHEARG_THUNK(14) DEF_CACHEARG_THUNK(15)
DEF_CACHEARG_THUNK(16) DEF_CACHEARG_THUNK(17) DEF_CACHEARG_THUNK(18) DEF_CACHEARG_THUNK(19)
DEF_CACHEARG_THUNK(20) DEF_CACHEARG_THUNK(21) DEF_CACHEARG_THUNK(22) DEF_CACHEARG_THUNK(23)

DEF_RAILWAYNODE_THUNK(0)  DEF_RAILWAYNODE_THUNK(1)  DEF_RAILWAYNODE_THUNK(2)
DEF_RAILWAYNODE_THUNK(3)  DEF_RAILWAYNODE_THUNK(4)  DEF_RAILWAYNODE_THUNK(5)
DEF_RAILWAYNODE_THUNK(6)  DEF_RAILWAYNODE_THUNK(7)  DEF_RAILWAYNODE_THUNK(8)
DEF_RAILWAYNODE_THUNK(9)  DEF_RAILWAYNODE_THUNK(10) DEF_RAILWAYNODE_THUNK(11)
DEF_RAILWAYNODE_THUNK(12) DEF_RAILWAYNODE_THUNK(13) DEF_RAILWAYNODE_THUNK(14)
DEF_RAILWAYNODE_THUNK(15) DEF_RAILWAYNODE_THUNK(16) DEF_RAILWAYNODE_THUNK(17)
DEF_RAILWAYNODE_THUNK(18) DEF_RAILWAYNODE_THUNK(19) DEF_RAILWAYNODE_THUNK(20)
DEF_RAILWAYNODE_THUNK(21) DEF_RAILWAYNODE_THUNK(22) DEF_RAILWAYNODE_THUNK(23)

DEF_RAILWAYHIST_THUNK(0)  DEF_RAILWAYHIST_THUNK(1)  DEF_RAILWAYHIST_THUNK(2)
DEF_RAILWAYHIST_THUNK(3)  DEF_RAILWAYHIST_THUNK(4)  DEF_RAILWAYHIST_THUNK(5)
DEF_RAILWAYHIST_THUNK(6)  DEF_RAILWAYHIST_THUNK(7)  DEF_RAILWAYHIST_THUNK(8)
DEF_RAILWAYHIST_THUNK(9)  DEF_RAILWAYHIST_THUNK(10) DEF_RAILWAYHIST_THUNK(11)
DEF_RAILWAYHIST_THUNK(12) DEF_RAILWAYHIST_THUNK(13) DEF_RAILWAYHIST_THUNK(14)
DEF_RAILWAYHIST_THUNK(15) DEF_RAILWAYHIST_THUNK(16) DEF_RAILWAYHIST_THUNK(17)
DEF_RAILWAYHIST_THUNK(18) DEF_RAILWAYHIST_THUNK(19) DEF_RAILWAYHIST_THUNK(20)
DEF_RAILWAYHIST_THUNK(21) DEF_RAILWAYHIST_THUNK(22) DEF_RAILWAYHIST_THUNK(23)

static detour_fn pick_detour(int index, LONG kind)
{
    switch (kind) {
    case BWK_UNIT:
        switch (index) {
        case 0: return (detour_fn)hk_unit_0;   case 1: return (detour_fn)hk_unit_1;
        case 2: return (detour_fn)hk_unit_2;   case 3: return (detour_fn)hk_unit_3;
        case 4: return (detour_fn)hk_unit_4;   case 5: return (detour_fn)hk_unit_5;
        case 6: return (detour_fn)hk_unit_6;   case 7: return (detour_fn)hk_unit_7;
        case 8: return (detour_fn)hk_unit_8;   case 9: return (detour_fn)hk_unit_9;
        case 10: return (detour_fn)hk_unit_10; default: return (detour_fn)hk_unit_11;
        }
    case BWK_UNIT_INT_BOOL:
        switch (index) {
        case 0: return (detour_fn)hk_unit_ib_0;  case 1: return (detour_fn)hk_unit_ib_1;
        case 2: return (detour_fn)hk_unit_ib_2;  case 3: return (detour_fn)hk_unit_ib_3;
        case 4: return (detour_fn)hk_unit_ib_4;  case 5: return (detour_fn)hk_unit_ib_5;
        case 6: return (detour_fn)hk_unit_ib_6;  case 7: return (detour_fn)hk_unit_ib_7;
        case 8: return (detour_fn)hk_unit_ib_8;  case 9: return (detour_fn)hk_unit_ib_9;
        case 10: return (detour_fn)hk_unit_ib_10; default: return (detour_fn)hk_unit_ib_11;
        }
    case BWK_UNIT_GET_INT:
        switch (index) {
        case 0: return (detour_fn)hk_unit_gi_0;  case 1: return (detour_fn)hk_unit_gi_1;
        case 2: return (detour_fn)hk_unit_gi_2;  case 3: return (detour_fn)hk_unit_gi_3;
        case 4: return (detour_fn)hk_unit_gi_4;  case 5: return (detour_fn)hk_unit_gi_5;
        case 6: return (detour_fn)hk_unit_gi_6;  case 7: return (detour_fn)hk_unit_gi_7;
        case 8: return (detour_fn)hk_unit_gi_8;  case 9: return (detour_fn)hk_unit_gi_9;
        case 10: return (detour_fn)hk_unit_gi_10; default: return (detour_fn)hk_unit_gi_11;
        }
    case BWK_ACTION_INT:
        switch (index) {
        case 0: return (detour_fn)hk_action_0;  case 1: return (detour_fn)hk_action_1;
        case 2: return (detour_fn)hk_action_2;  case 3: return (detour_fn)hk_action_3;
        case 4: return (detour_fn)hk_action_4;  case 5: return (detour_fn)hk_action_5;
        case 6: return (detour_fn)hk_action_6;  case 7: return (detour_fn)hk_action_7;
        case 8: return (detour_fn)hk_action_8;  case 9: return (detour_fn)hk_action_9;
        case 10: return (detour_fn)hk_action_10; default: return (detour_fn)hk_action_11;
        }
    case BWK_DAMAGE_ACTION:
        switch (index) {
        case 0: return (detour_fn)hk_damage_0;  case 1: return (detour_fn)hk_damage_1;
        case 2: return (detour_fn)hk_damage_2;  case 3: return (detour_fn)hk_damage_3;
        case 4: return (detour_fn)hk_damage_4;  case 5: return (detour_fn)hk_damage_5;
        case 6: return (detour_fn)hk_damage_6;  case 7: return (detour_fn)hk_damage_7;
        case 8: return (detour_fn)hk_damage_8;  case 9: return (detour_fn)hk_damage_9;
        case 10: return (detour_fn)hk_damage_10; default: return (detour_fn)hk_damage_11;
        }
    case BWK_PLAIN:
        switch (index) {
        case 0: return (detour_fn)hk_plain_0;  case 1: return (detour_fn)hk_plain_1;
        case 2: return (detour_fn)hk_plain_2;  case 3: return (detour_fn)hk_plain_3;
        case 4: return (detour_fn)hk_plain_4;  case 5: return (detour_fn)hk_plain_5;
        case 6: return (detour_fn)hk_plain_6;  case 7: return (detour_fn)hk_plain_7;
        case 8: return (detour_fn)hk_plain_8;  case 9: return (detour_fn)hk_plain_9;
        case 10: return (detour_fn)hk_plain_10; default: return (detour_fn)hk_plain_11;
        }
    case BWK_SKV:
        switch (index) {
        case 0: return (detour_fn)hk_skv_0;    case 1: return (detour_fn)hk_skv_1;
        case 2: return (detour_fn)hk_skv_2;    case 3: return (detour_fn)hk_skv_3;
        case 4: return (detour_fn)hk_skv_4;    case 5: return (detour_fn)hk_skv_5;
        case 6: return (detour_fn)hk_skv_6;    case 7: return (detour_fn)hk_skv_7;
        case 8: return (detour_fn)hk_skv_8;    case 9: return (detour_fn)hk_skv_9;
        case 10: return (detour_fn)hk_skv_10;  default: return (detour_fn)hk_skv_11;
        }
    case BWK_STAGE_STAT:
        switch (index) {
        case 0: return (detour_fn)hk_stage_0;  case 1: return (detour_fn)hk_stage_1;
        case 2: return (detour_fn)hk_stage_2;  case 3: return (detour_fn)hk_stage_3;
        case 4: return (detour_fn)hk_stage_4;  case 5: return (detour_fn)hk_stage_5;
        case 6: return (detour_fn)hk_stage_6;  case 7: return (detour_fn)hk_stage_7;
        case 8: return (detour_fn)hk_stage_8;  case 9: return (detour_fn)hk_stage_9;
        case 10: return (detour_fn)hk_stage_10; default: return (detour_fn)hk_stage_11;
        }
    case BWK_RAILWAY_TOTAL:
        switch (index) {
        case 0: return (detour_fn)hk_railway_0;  case 1: return (detour_fn)hk_railway_1;
        case 2: return (detour_fn)hk_railway_2;  case 3: return (detour_fn)hk_railway_3;
        case 4: return (detour_fn)hk_railway_4;  case 5: return (detour_fn)hk_railway_5;
        case 6: return (detour_fn)hk_railway_6;  case 7: return (detour_fn)hk_railway_7;
        case 8: return (detour_fn)hk_railway_8;  case 9: return (detour_fn)hk_railway_9;
        case 10: return (detour_fn)hk_railway_10; case 11: return (detour_fn)hk_railway_11;
        case 12: return (detour_fn)hk_railway_12; case 13: return (detour_fn)hk_railway_13;
        case 14: return (detour_fn)hk_railway_14; default: return (detour_fn)hk_railway_15;
        }
    case BWK_CACHE_SELF:
        switch (index) {
        case 0: return (detour_fn)hk_cache_0;  case 1: return (detour_fn)hk_cache_1;
        case 2: return (detour_fn)hk_cache_2;  case 3: return (detour_fn)hk_cache_3;
        case 4: return (detour_fn)hk_cache_4;  case 5: return (detour_fn)hk_cache_5;
        case 6: return (detour_fn)hk_cache_6;  case 7: return (detour_fn)hk_cache_7;
        case 8: return (detour_fn)hk_cache_8;  case 9: return (detour_fn)hk_cache_9;
        case 10: return (detour_fn)hk_cache_10; case 11: return (detour_fn)hk_cache_11;
        case 12: return (detour_fn)hk_cache_12; case 13: return (detour_fn)hk_cache_13;
        case 14: return (detour_fn)hk_cache_14; default: return (detour_fn)hk_cache_15;
        }
    case BWK_NODE_STATE:
        switch (index) {
        case 0: return (detour_fn)hk_node_0;   case 1: return (detour_fn)hk_node_1;
        case 2: return (detour_fn)hk_node_2;   case 3: return (detour_fn)hk_node_3;
        case 4: return (detour_fn)hk_node_4;   case 5: return (detour_fn)hk_node_5;
        case 6: return (detour_fn)hk_node_6;   case 7: return (detour_fn)hk_node_7;
        case 8: return (detour_fn)hk_node_8;   case 9: return (detour_fn)hk_node_9;
        case 10: return (detour_fn)hk_node_10; case 11: return (detour_fn)hk_node_11;
        case 12: return (detour_fn)hk_node_12; case 13: return (detour_fn)hk_node_13;
        case 14: return (detour_fn)hk_node_14; case 15: return (detour_fn)hk_node_15;
        case 16: return (detour_fn)hk_node_16; case 17: return (detour_fn)hk_node_17;
        case 18: return (detour_fn)hk_node_18; default: return (detour_fn)hk_node_19;
        }
    case BWK_CACHE_ARG1:
        switch (index) {
        case 0: return (detour_fn)hk_cachearg_0;  case 1: return (detour_fn)hk_cachearg_1;
        case 2: return (detour_fn)hk_cachearg_2;  case 3: return (detour_fn)hk_cachearg_3;
        case 4: return (detour_fn)hk_cachearg_4;  case 5: return (detour_fn)hk_cachearg_5;
        case 6: return (detour_fn)hk_cachearg_6;  case 7: return (detour_fn)hk_cachearg_7;
        case 8: return (detour_fn)hk_cachearg_8;  case 9: return (detour_fn)hk_cachearg_9;
        case 10: return (detour_fn)hk_cachearg_10; case 11: return (detour_fn)hk_cachearg_11;
        case 12: return (detour_fn)hk_cachearg_12; case 13: return (detour_fn)hk_cachearg_13;
        case 14: return (detour_fn)hk_cachearg_14; case 15: return (detour_fn)hk_cachearg_15;
        case 16: return (detour_fn)hk_cachearg_16; case 17: return (detour_fn)hk_cachearg_17;
        case 18: return (detour_fn)hk_cachearg_18; case 19: return (detour_fn)hk_cachearg_19;
        case 20: return (detour_fn)hk_cachearg_20; case 21: return (detour_fn)hk_cachearg_21;
        case 22: return (detour_fn)hk_cachearg_22; default: return (detour_fn)hk_cachearg_23;
        }
    case BWK_RAILWAY_NODE:
        switch (index) {
        case 0: return (detour_fn)hk_railn_0;   case 1: return (detour_fn)hk_railn_1;
        case 2: return (detour_fn)hk_railn_2;   case 3: return (detour_fn)hk_railn_3;
        case 4: return (detour_fn)hk_railn_4;   case 5: return (detour_fn)hk_railn_5;
        case 6: return (detour_fn)hk_railn_6;   case 7: return (detour_fn)hk_railn_7;
        case 8: return (detour_fn)hk_railn_8;   case 9: return (detour_fn)hk_railn_9;
        case 10: return (detour_fn)hk_railn_10; case 11: return (detour_fn)hk_railn_11;
        case 12: return (detour_fn)hk_railn_12; case 13: return (detour_fn)hk_railn_13;
        case 14: return (detour_fn)hk_railn_14; case 15: return (detour_fn)hk_railn_15;
        case 16: return (detour_fn)hk_railn_16; case 17: return (detour_fn)hk_railn_17;
        case 18: return (detour_fn)hk_railn_18; case 19: return (detour_fn)hk_railn_19;
        case 20: return (detour_fn)hk_railn_20; case 21: return (detour_fn)hk_railn_21;
        case 22: return (detour_fn)hk_railn_22; default: return (detour_fn)hk_railn_23;
        }
    case BWK_RAILWAY_HIST:
        switch (index) {
        case 0: return (detour_fn)hk_railhist_0;   case 1: return (detour_fn)hk_railhist_1;
        case 2: return (detour_fn)hk_railhist_2;   case 3: return (detour_fn)hk_railhist_3;
        case 4: return (detour_fn)hk_railhist_4;   case 5: return (detour_fn)hk_railhist_5;
        case 6: return (detour_fn)hk_railhist_6;   case 7: return (detour_fn)hk_railhist_7;
        case 8: return (detour_fn)hk_railhist_8;   case 9: return (detour_fn)hk_railhist_9;
        case 10: return (detour_fn)hk_railhist_10; case 11: return (detour_fn)hk_railhist_11;
        case 12: return (detour_fn)hk_railhist_12; case 13: return (detour_fn)hk_railhist_13;
        case 14: return (detour_fn)hk_railhist_14; case 15: return (detour_fn)hk_railhist_15;
        case 16: return (detour_fn)hk_railhist_16; case 17: return (detour_fn)hk_railhist_17;
        case 18: return (detour_fn)hk_railhist_18; case 19: return (detour_fn)hk_railhist_19;
        case 20: return (detour_fn)hk_railhist_20; case 21: return (detour_fn)hk_railhist_21;
        case 22: return (detour_fn)hk_railhist_22; default: return (detour_fn)hk_railhist_23;
        }
    default:
        return (detour_fn)hk_plain_0;
    }
}

/* ------------------------------------------------------------------ */
/* 装钩 / 摘钩                                                        */
/* ------------------------------------------------------------------ */

static BOOL is_all_zero(const unsigned char *p, size_t n)
{
    size_t i;
    for (i = 0; i < n; i++) {
        if (p[i])
            return FALSE;
    }
    return TRUE;
}

static BOOL verify_prologue(void *addr, const unsigned char *expected)
{
    unsigned char buf[16];
    if (!addr || !expected)
        return FALSE;
    if (is_all_zero(expected, 16))
        return TRUE;              /* 全 0 = 放弃自检（调用方会写 WARN 行） */
    memcpy(buf, addr, sizeof(buf));
    return memcmp(buf, expected, sizeof(buf)) == 0;
}

static void uninstall_hooks(void)
{
    int i;
    if (g_hooked) {
        for (i = 0; i < BW_MAX_HOOKS; i++) {
            if (g_active[i] && g_target[i])
                MH_DisableHook(g_target[i]);
        }
        for (i = 0; i < BW_MAX_HOOKS; i++) {
            if (g_active[i] && g_target[i])
                MH_RemoveHook(g_target[i]);
        }
        MH_Uninitialize();
    }
    for (i = 0; i < BW_MAX_HOOKS; i++) {
        g_target[i] = NULL;
        g_original[i] = NULL;
        g_active[i] = FALSE;
    }
    g_hooked = FALSE;
    if (g_cfg) {
        g_cfg->installed = FALSE;
        g_cfg->verified = FALSE;
    }
}

static void install_hooks(void)
{
    HMODULE ga;
    uintptr_t base;
    int i, count, skipped = 0, wanted = 0;
    char line[120];

    if (g_cfg->retry_requested) {
        uninstall_hooks();
        g_cfg->retry_requested = FALSE;
        g_cfg->last_error = BW_ERR_OK;
        for (i = 0; i < BW_MAX_HOOKS; i++)
            InterlockedExchange(&g_cfg->hook_hits[i], 0);
    }
    if (g_hooked)
        return;

    ga = GetModuleHandleW(L"GameAssembly.dll");
    if (!ga)
        return;
    base = (uintptr_t)ga;

    count = (int)g_cfg->hook_count;
    if (count < 0) count = 0;
    if (count > BW_MAX_HOOKS) count = BW_MAX_HOOKS;

    /* 先整体自检：任何一个不符就完全不装（避免半钩状态） */
    for (i = 0; i < count; i++) {
        if (g_cfg->hook_rva[i] <= 0)
            continue;
        wanted++;
        if (!verify_prologue((void *)(base + (uintptr_t)(uint32_t)g_cfg->hook_rva[i]),
                             g_cfg->hook_prologue[i]))
        {
            g_cfg->verified = FALSE;
            g_cfg->installed = FALSE;
            g_cfg->last_error = BW_ERR_PROLOGUE;
            _snprintf(line, sizeof(line) - 1, "ERR prologue mismatch: %s",
                      (const char *)g_cfg->hook_name[i]);
            line[sizeof(line) - 1] = '\0';
            log_line(line, FALSE);
            return;
        }
        if (is_all_zero(g_cfg->hook_prologue[i], 16))
            skipped++;
    }
    g_cfg->verified = TRUE;
    if (skipped)
        log_line("WARN prologue check skipped (no expected bytes)", FALSE);

    if (wanted == 0) {
        g_cfg->last_error = BW_ERR_OK;
        log_line("WARN no hook configured", FALSE);
        return;
    }

    if (MH_Initialize() != MH_OK) {
        g_cfg->last_error = BW_ERR_MH_INIT;
        return;
    }

    for (i = 0; i < count; i++) {
        void *target;
        if (g_cfg->hook_rva[i] <= 0)
            continue;
        target = (void *)(base + (uintptr_t)(uint32_t)g_cfg->hook_rva[i]);
        if (MH_CreateHook(target, (LPVOID)pick_detour(i, g_cfg->hook_kind[i]),
                          &g_original[i]) != MH_OK) {
            g_cfg->last_error = BW_ERR_MH_CREATE;
            _snprintf(line, sizeof(line) - 1, "ERR create hook failed: %s",
                      (const char *)g_cfg->hook_name[i]);
            line[sizeof(line) - 1] = '\0';
            log_line(line, FALSE);
            uninstall_hooks();
            return;
        }
        g_target[i] = target;
        g_kind[i] = g_cfg->hook_kind[i];
        g_active[i] = TRUE;
    }
    if (MH_EnableHook(MH_ALL_HOOKS) != MH_OK) {
        g_cfg->last_error = BW_ERR_MH_ENABLE;
        log_line("ERR enable hooks failed", FALSE);
        uninstall_hooks();
        return;
    }

    g_hooked = TRUE;
    /* 一次性回读：确认 DLL 这侧看到的关注 buff 表（Python 侧同时也回读一遍，两头对得上
     * 才能排除"Python 写了、DLL 没看到"这种错位）。*/
    {
        char info[160];
        int ni = _snprintf(info, sizeof(info) - 1,
                           "INFO installed buffwatch=%d hash0=%016llx hash1=%016llx",
                           (int)g_cfg->buff_watch_count,
                           (unsigned long long)g_cfg->buff_watch_hashes[0],
                           (unsigned long long)g_cfg->buff_watch_hashes[1]);
        if (ni > 0) {
            if (ni > (int)sizeof(info) - 1) ni = (int)sizeof(info) - 1;
            info[ni] = '\0';
            emit(info, TRUE);
        }
    }
    g_cfg->installed = TRUE;
    g_cfg->last_error = BW_ERR_OK;
    _snprintf(line, sizeof(line) - 1, "INFO hooks installed (%d)", wanted);
    line[sizeof(line) - 1] = '\0';
    log_line(line, FALSE);
}

/* ------------------------------------------------------------------ */
/* watcher 线程 / DllMain                                             */
/* ------------------------------------------------------------------ */

static void publish_layout(void)
{
    if (g_cfg && g_cfg->magic == BW_MAGIC) {
        g_cfg->ring_offset = (LONG)offsetof(BW_CONFIG, log_ring);
        g_cfg->struct_size = (LONG)sizeof(BW_CONFIG);
    }
}

static void ensure_config(void)
{
    HANDLE map;
    void *view;

    if (g_cfg && g_cfg->magic == BW_MAGIC) {
        publish_layout();
        return;
    }

    map = OpenFileMappingW(FILE_MAP_ALL_ACCESS, FALSE, BW_MAP_NAME);
    if (!map)
        return;
    view = MapViewOfFile(map, FILE_MAP_ALL_ACCESS, 0, 0, 0);
    if (view) {
        if (view != g_cfg) {
            if (g_cfg)
                UnmapViewOfFile(g_cfg);
            g_cfg = (BW_CONFIG *)view;
        }
        if (g_cfg->magic != BW_MAGIC) {
            UnmapViewOfFile(g_cfg);
            g_cfg = NULL;
        } else {
            publish_layout();
            if (!g_cfg_logged) {
                char info[192];
                int ni;
                g_cfg_logged = TRUE;
                ni = _snprintf(info, sizeof(info) - 1,
                               "INFO cfg view=0x%llx buffwatch=%d hash0=%016llx hash1=%016llx",
                               (unsigned long long)(uintptr_t)g_cfg,
                               (int)g_cfg->buff_watch_count,
                               (unsigned long long)g_cfg->buff_watch_hashes[0],
                               (unsigned long long)g_cfg->buff_watch_hashes[1]);
                if (ni > 0) {
                    if (ni > (int)sizeof(info) - 1) ni = (int)sizeof(info) - 1;
                    info[ni] = '\0';
                    emit(info, TRUE);
                }
            }
        }
    }
    CloseHandle(map);
}

static DWORD WINAPI watcher_thread(LPVOID unused)
{
    DWORD started = GetTickCount();
    DWORD last_attempt = 0;
    (void)unused;

    for (;;) {
        if (WaitForSingleObject(g_stop_event, BW_POLL_MS) == WAIT_OBJECT_0)
            break;

        ensure_config();
        if (!g_cfg)
            continue;
        if (!g_cfg->observing)
            continue;

        if (!GetModuleHandleW(L"GameAssembly.dll")) {
            g_cfg->gameassembly_found = FALSE;
            if (GetTickCount() - started > BW_GA_TIMEOUT_MS)
                g_cfg->last_error = BW_ERR_GA_TIMEOUT;
            continue;
        }
        g_cfg->gameassembly_found = TRUE;

        if (!g_hooked && g_cfg->last_error != BW_ERR_OK &&
            GetTickCount() - last_attempt < 5000)
            continue;
        install_hooks();
        last_attempt = GetTickCount();
    }

    uninstall_hooks();
    return 0;
}

static void attach(void)
{
    HANDLE map;
    void *view;

    g_stop_event = CreateEventW(NULL, TRUE, FALSE, NULL);

    map = OpenFileMappingW(FILE_MAP_ALL_ACCESS, FALSE, BW_MAP_NAME);
    if (map) {
        view = MapViewOfFile(map, FILE_MAP_ALL_ACCESS, 0, 0, 0);
        if (view) {
            g_cfg = (BW_CONFIG *)view;
            if (g_cfg->magic != BW_MAGIC)
                g_cfg = NULL;
            else
                publish_layout();
        }
        CloseHandle(map);
    }

    g_watcher = CreateThread(NULL, 0, watcher_thread, NULL, 0, NULL);
    g_sampler = CreateThread(NULL, 0, sampler_thread, NULL, 0, NULL);
}

static void detach(void)
{
    if (g_stop_event) {
        SetEvent(g_stop_event);
        if (g_watcher) {
            WaitForSingleObject(g_watcher, 2000);
            CloseHandle(g_watcher);
            g_watcher = NULL;
        }
        CloseHandle(g_stop_event);
        g_stop_event = NULL;
    }
    if (g_cfg) {
        UnmapViewOfFile(g_cfg);
        g_cfg = NULL;
    }
}

BOOL WINAPI DllMain(HINSTANCE hinst, DWORD reason, LPVOID reserved)
{
    (void)reserved;
    switch (reason) {
    case DLL_PROCESS_ATTACH:
        DisableThreadLibraryCalls(hinst);
        attach();
        break;
    case DLL_PROCESS_DETACH:
        detach();
        break;
    default:
        break;
    }
    return TRUE;
}
