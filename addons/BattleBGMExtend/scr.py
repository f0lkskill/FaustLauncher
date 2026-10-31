# BattleBGMExtend —— WarpHook 移植版
#
# 原理和原版一样：某些人格身上出现特定 buff / 层数变化时，把战斗 BGM 换成
# 指定的曲子，多条规则按优先级覆盖。
#
# 区别只有「怎么换曲」这一步：
#   原版：自带 DLL 钩三十多个音频方法，锁住游戏自己的换曲逻辑。
#   这里：只用 WarpHook 的门面 —— game.on_round_start 拿回合快照，
#         game.bgm() 把曲子塞进游戏的附加曲通道。不需要任何 DLL。
#
# 规则在 rules.json 里（和原版同名同字段），改完点菜单「重载规则」即可生效。

import json
import os
from typing import cast

ADDON_NAME = ADDON_ARG.get('AddonName', 'BattleBGMExtend')  # noqa: F821
_NS = ADDON_ARG.get('Namespaces')                            # noqa: F821
_W = cast("WarpNamespace", _NS.space('warp') if _NS is not None else None)
_GAME = _W.game

HERE = os.path.dirname(os.path.abspath(__file__))
RULES_FILE = os.path.join(HERE, 'rules.json')

# ---- 条件类型（与旧插件完全一致）----
HAS_BUFF = 'has_active_buff'                   # 身上有该 buff 就换
START_STACK = 'round_start_buff_stack_equals'  # 回合开始时层数正好等于 N
START_NO_BUFF = 'round_start_without_buff'     # 回合开始时身上没有该 buff
END_TRANSITION = 'round_end_buff_transition'   # 回合末从 A 转成 B 之后换

# rules.json 读不到时的兜底（与随包的 rules.json 一致）
DEFAULT_RULES = [
    {'id': 'sinclair_crimson_god_noble_dignity', 'enabled': True,
     'personality_id': 11016, 'personality_name': '辛克莱 红派 赤红之神',
     'condition': {'type': HAS_BUFF, 'keyword': 'TransformSinclair'},
     'bgm': 'Battle_Cp10_Boss_10', 'priority': 10000},
    {'id': 'ryoshu_dihui', 'enabled': True,
     'personality_id': 10415, 'personality_name': '良秀 蜘蛛巢之刃',
     'condition': {'type': HAS_BUFF, 'keyword': 'SojiRyoshuShin'},
     'bgm': 'Battle_Cp9_Boss_6', 'priority': 9000},
    {'id': 'yisang_hermes', 'enabled': True,
     'personality_id': 10115, 'personality_name': '李箱 蜘蛛巢食指父辈',
     'condition': {'type': START_STACK, 'keyword': 'StackYisangSpecialSkill',
                   'stack': 9},
     'bgm': 'Battle_Cp9_Boss_10', 'priority': 8800},
    {'id': 'rodion_overheat', 'enabled': True,
     'personality_id': 10916, 'personality_name': '罗佳 蜘蛛巢拇指父辈',
     'condition': {'type': END_TRANSITION, 'keyword': 'FutureEyeOffRodion',
                   'from_keyword': 'FutureEyeOnRodion'},
     'bgm': 'Battle_Cp9_Boss_1_2', 'priority': 8700},
    {'id': 'outis_laevateinn', 'enabled': True,
     'personality_id': 11115, 'personality_name': '奥提斯 蜘蛛巢中指父辈',
     'condition': {'type': HAS_BUFF, 'keyword': 'MiddleFatherSwordFourOutis'},
     'bgm': 'Battle_Cp9_Boss_3_2', 'priority': 8600},
    {'id': 'honglu_tableau', 'enabled': True,
     'personality_id': 10614, 'personality_name': '鸿璐 蜘蛛巢环指父辈',
     'condition': {'type': START_NO_BUFF, 'keyword': 'GoldenOpportunity'},
     'bgm': 'Battle_Cp9_Boss_4_2', 'priority': 8500},
    {'id': 'don_procuration', 'enabled': True,
     'personality_id': 10314, 'personality_name': '堂吉诃德 食指代行者',
     'condition': {'type': HAS_BUFF, 'keyword': 'Blandishment_Shin'},
     'bgm': 'Battle_Cp9_Boss_2_2', 'priority': 8000},
    {'id': 'meursault_tiantui', 'enabled': True,
     'personality_id': 10512, 'personality_name': '默尔索 拇指东部指挥官',
     'condition': {'type': HAS_BUFF, 'keyword': 'IrritationAlly'},
     'bgm': 'Battle_Cp8_Boss_2', 'priority': 7000},
    {'id': 'rodion_wolf', 'enabled': True,
     'personality_id': 10915, 'personality_name': '罗佳 环指野兽派讲解员',
     'condition': {'type': HAS_BUFF, 'keyword': 'FaubismWolfMaskRodion'},
     'bgm': 'Battle_Cp9_5_Thread_Boss', 'priority': 6000},
]


def _settings():
    """(开关, 播报)"""
    try:
        manager = ADDON_ARG.get('AddonManager')      # noqa: F821
        info = manager.get_addon_info(ADDON_NAME) if manager else None
    except Exception:                                # noqa: BLE001
        info = None
    data = (info or {}).get('settings') or {}
    return bool(data.get('enable', True)), bool(data.get('播报切换', True))


def _log(text):
    print(f'[{ADDON_NAME}] {text}', flush=True)


def _say(text):
    if _settings()[1]:
        _log(text)


def _load_rules():
    """读 rules.json；读不到或格式不对就退回内置表，不让插件整体挂掉。"""
    try:
        with open(RULES_FILE, 'r', encoding='utf-8-sig') as handle:
            document = json.load(handle)
        rows = document.get('rules') if isinstance(document, dict) else document
        if not isinstance(rows, list):
            raise ValueError('rules.json 里没有 rules 数组')
    except Exception as exc:                          # noqa: BLE001
        _log(f'读 rules.json 失败（用内置规则）：{exc}')
        rows = DEFAULT_RULES

    rules = []
    for row in rows:
        try:
            if not row.get('enabled', True):
                continue
            cond = dict(row.get('condition') or {})
            identity = int(row.get('personality_id') or 0)
            bgm = str(row.get('bgm') or '').strip()
            if identity <= 0 or not bgm:
                _log(f"跳过一条规则（缺 personality_id 或 bgm）：{row.get('id')}")
                continue
            rules.append({
                'id': str(row.get('id') or bgm),
                'name': str(row.get('personality_name') or ''),
                'identity': identity,
                'condition': cond,
                'bgm': bgm,
                'priority': int(row.get('priority') or 0),
            })
        except Exception as exc:                      # noqa: BLE001
            _log(f"跳过一条规则（{row.get('id')}）：{exc}")
    return rules


RULES = _load_rules()


def _watched():
    """规则里用到的全部 buff 英文 ID —— 只读这些，别把整个 buff 表翻一遍。"""
    names = set()
    for rule in RULES:
        cond = rule['condition']
        if cond.get('keyword'):
            names.add(str(cond['keyword']))
        if cond.get('from_keyword'):
            names.add(str(cond['from_keyword']))
    return names


WATCHED = _watched()

_active = None      # 当前生效的规则；None = 没锁，游戏原曲在放
_prev = {}          # 上一回合快照 {单位 id: {buff 英文 ID: 层数}}
_battle_id = None   # 场上单位次序，换战斗就清状态


def _buff_table(unit):
    """{英文 ID: Buff}。只收规则关心的那几个，层数用到再读。"""
    table = {}
    try:
        for buff in unit.buffs:
            key = buff.key
            if key and key in WATCHED:
                table[key] = buff
    except Exception:                                 # noqa: BLE001
        pass
    return table


def _stack(table, key):
    buff = table.get(key)
    if buff is None:
        return 0
    try:
        return int(buff.stack or 0)
    except Exception:                                 # noqa: BLE001
        return 0


def _match(rule, table, previous):
    """这条规则此刻成立吗。"""
    cond = rule['condition']
    kind = cond.get('type')
    key = str(cond.get('keyword') or '')

    if kind == HAS_BUFF:
        return _stack(table, key) > 0
    if kind == START_STACK:
        return _stack(table, key) == int(cond.get('stack') or 0)
    if kind == START_NO_BUFF:
        return _stack(table, key) <= 0
    if kind == END_TRANSITION:
        # 转换发生在回合末，我们到下一个回合开始才看得见：
        # 「上回合还有 A、现在换成了 B」才算成立。
        source = str(cond.get('from_keyword') or '')
        return int((previous or {}).get(source, 0)) > 0 and _stack(table, key) > 0
    _log(f"未知条件类型：{kind}（规则 {rule['id']}）")
    return False


def _scan(battle):
    """一次遍历：挑出优先级最高的规则，同时把本回合快照记下来。"""
    global _prev
    best = None
    snap = {}

    for unit in battle.units:
        identity = unit.identity
        if not identity:
            continue
        matched = [r for r in RULES if r['identity'] == identity]
        if not matched:
            continue
        table = _buff_table(unit)
        previous = _prev.get(unit.id) or {}
        snap[unit.id] = {key: _stack(table, key) for key in table}
        for rule in matched:
            if _match(rule, table, previous):
                if best is None or rule['priority'] > best['priority']:
                    best = rule

    _prev = snap
    return best


def _apply(battle):
    """回合开始的主判定：挑规则 -> 比优先级 -> 换曲。"""
    global _active, _battle_id

    mark = tuple(sorted(u.id for u in battle.units))
    if _battle_id != mark:               # 换了战斗，状态清零重来
        _battle_id = mark
        _active = None
        _prev = {}

    best = _scan(battle)
    if best is None:
        return
    if _active is not None and best['priority'] <= _active['priority']:
        return                           # 正在放更高优先级的曲子，不换

    result = _GAME.bgm(best['bgm'])
    if result.get('ok'):
        _active = best
        _say(f"切到「{best['name'] or best['id']}」-> {best['bgm']}"
             f"（优先级 {best['priority']}）")
    else:
        _say(f"「{best['name'] or best['id']}」换曲失败："
             f"{result.get('reason') or '未知原因'}")


def _on_round(battle):
    try:
        _apply(battle)
    except Exception as exc:                             # noqa: BLE001
        _log(f'回合判定出错：{exc}')


def _on_battle_end(_scene):
    """离开战斗就把附加曲收掉，接回游戏原曲。"""
    global _active, _prev, _battle_id
    if _active is not None:
        _GAME.bgm_stop()
        _say(f"战斗结束，恢复原曲（上一首「{_active['name'] or _active['id']}」）")
    _active, _prev, _battle_id = None, {}, None


def _check_now():
    """菜单：不等回合，立刻看一次。"""
    battle = _GAME.battle()
    if battle is None:
        _say('现在不在战斗里')
        return
    _apply(battle)
    if _active is None:
        _say('没有任何规则命中')


def _show_status():
    index = _GAME.bgm_index()
    if _active is None:
        _say(f'未锁定；游戏原曲；当前曲目编号 {index}')
    else:
        _say(f"锁定「{_active['name'] or _active['id']}」-> {_active['bgm']}；"
             f"当前曲目编号 {index}")


def _reload():
    """菜单：改完 rules.json 不用重启启动器。"""
    global RULES, WATCHED
    RULES = _load_rules()
    WATCHED = _watched()
    _say(f'规则已重新载入：{len(RULES)} 条')


if _settings()[0]:
    _GAME.on_round_start(_on_round)
    _GAME.on_battle_end(_on_battle_end)
    _GAME.start(menu=(
        ('立刻检查', _check_now),
        ('恢复原曲', lambda: _GAME.bgm_stop()),
        ('查看状态', _show_status),
        ('重载规则', _reload),
    ))
    _log(f'已启动：{len(RULES)} 条规则（WarpHook 移植版，无需 DLL）')
else:
    _log('设置里关掉了（enable=false），本次不启用')


def on_unload():
    return _GAME.close()
