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
import threading

ADDON_NAME = ADDON_ARG.get('AddonName', 'BattleBGMExtend')  # noqa: F821
def _game():
    """现取命名空间门面 —— 本插件可能先于 WarpHook 载入，顶层快照会拿旧模块。"""
    ns = ADDON_ARG.get('Namespaces')                          # noqa: F821
    space = ns.space('warp') if ns is not None else None
    if space is None or not getattr(space, 'game', None):
        raise RuntimeError('WarpHook 命名空间尚未就绪')
    return space.game

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
    # 通过命名空间使用宿主的轮转日志，不把独立插件绑死到 Python 导入路径。
    try:
        ns = ADDON_ARG.get('Namespaces')  # noqa: F821
        space = ns.space('warp') if ns is not None else None
        writer = getattr(getattr(space, 'log', None), 'write', None)
        if callable(writer):
            writer(str(text), prefix=f'[{ADDON_NAME}]')
            return
    except Exception:
        pass  # 宿主尚未注册/已卸载时，仍保留控制台诊断。
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
                'bank': str(row.get('bank') or '').strip() or None,
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
_pending = False    # 命中规则的放曲线程在排队（_check_now 据此不说「没命中」）
_prev = {}          # 上一回合快照 {单位 id: {buff 英文 ID: 层数}}
_battle_id = None   # 生命周期哨兵：由战斗结束回调重置，单位名单不是战斗 ID
_check_guard = threading.Lock()  # 菜单请求只排一个；不得在菜单线程等待状态锁
_state_lock = threading.RLock()
_revision = 0       # 战斗切换/恢复/卸载使旧延迟任务失效
_pending_rule = None
_last_error = ''
_lock_ready = False # 换曲锁钩子装好了吗（惰性：第一场战斗的回合开始才装）


def _install_lock():
    """装换曲锁钩子（一次）。游戏早期类没加载也不要紧 —— 宿主每 2 秒重试。"""
    global _lock_ready
    if _lock_ready:
        return
    try:
        result = _game().bgm_lock_install()
        _lock_ready = bool(result.get('ok'))
        if not _lock_ready:
            _log(f'换曲锁安装未完成（下回合重试）：{result}')
        if _lock_ready:
            _lock(True)                  # 初始放行
            _log('换曲锁钩子已安装（StartBGM / StartAddBGM / StopBGM 三个拦截点）')
    except Exception as exc:             # noqa: BLE001
        _log(f'换曲锁安装失败（下回合重试）：{exc}')


def _lock(allow):
    """开/关换曲锁；True=放行游戏换曲，False=锁死。"""
    try:
        result = _game().bgm_lock(allow)
        if result is not True:
            _log(f'换曲锁操作未完成（allow={allow}）：{result}')
            return False
        return True
    except Exception as exc:             # noqa: BLE001
        _log(f'换曲锁操作失败：{exc}')
        return False


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
        # 存在性不等于层数；旧版 HasActivatedBuff 支持零层状态。
        return key in table
    if kind == START_STACK:
        return _stack(table, key) == int(cond.get('stack') or 0)
    if kind == START_NO_BUFF:
        return key not in table
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
    with _state_lock:
        return _apply_locked(battle)


def _apply_locked(battle):
    """回合开始的主判定：解锁 -> 挑规则 -> 比优先级 -> 放曲 -> 上锁。

    锁的时序（照旧插件 block_game 的语义，绕开 own_call）：
      1. 先解锁 —— 接下来的 StopBGM/StartAddBGM 直调不被自己的钩子拦；
      2. 规则命中才放曲（直调发生在回合开始时机，不在回合结束的
         FMOD 重建间隙 —— 0.9.26 第 7 次崩溃的教训）；
      3. 放完上锁 —— 本回合内游戏想盖回默认曲/停我们的曲，全部被
         guard 钩子丢弃，实例不中断、不重播；
      4. 规则还在命中的回合**不重放**，只保持锁 —— 曲子一直是同一个
         实例在响（旧插件同款）。
    """
    global _active, _battle_id, _prev, _revision, _pending, _pending_rule

    _install_lock()
    # 不在每次扫描时解锁；实际换曲前才放行，避免游戏抢回原曲。

    # Battle 只有当前单位视图，没有稳定战斗 ID。死亡、增援、换波及
    # 单次读失败都会改变名单；不能据此清除生效规则/重播同一首曲子。
    # 以首次快照进入、on_battle_end 退出维护生命周期（与旧版地板一致）。
    if _battle_id is None:
        _battle_id = object()
        _lock(True)
        _revision += 1
        _pending, _pending_rule = False, None
        _active = None
        _prev = {}

    best = _scan(battle)
    if best is None:
        _revision += 1
        _pending, _pending_rule = False, None
        if _active is not None:
            # 旧版 cfg->priority 是整场战斗的地板，不因瞬时条件消失降级。
            _lock(False)
            return '当前无更高命中，维持生效规则及优先级地板'
        else:
            _lock(True)
            # 诊断行：无命中时把扫描现场打出来（人格 ID + buff key），
            # 否则「条件达成了却没反应」没法远程定位 —— rules.json 的
            # identity/keyword 和游戏实际值对不上时，一眼就能看出来。
            rows = []
            for unit in list(battle.units)[:8]:
                keys = ','.join(sorted(_buff_table(unit))) or '-'
                rows.append(f"{unit.identity}:{keys}")
            _say(f"回合检测：无命中（在场 {len(battle.units)} 人）："
                 f"{' / '.join(rows) or '空场'}")
        _active = None
        return '当前无命中规则，保持游戏原曲'
    if _active is not None and best['priority'] <= _active['priority']:
        _lock(False)                     # 3'. 优先级地板：保持锁，不重放
        return f"维持规则 {_active['id']}，未超过优先级地板 {_active['priority']}"

    # 同一命中尚在排队时不重复开线程；较高优先级命中可替换旧任务。
    if _pending_rule is not None and best['priority'] <= _pending_rule['priority']:
        return f"跳过重复提交：规则 {_pending_rule['id']} 正在排队"
    rule = best
    _revision += 1
    revision = _revision
    _pending, _pending_rule = True, rule

    def _submit():
        global _active, _pending, _pending_rule, _last_error
        # 无人为等待；后台线程 + 状态锁串行，revision 令牌取消旧任务。
        with _state_lock:
            if revision != _revision:
                return
            try:
                if not _lock(True):
                    raise RuntimeError('放曲前解锁失败，未停止原曲')
                # 已由回合命中确认战斗；不再做一次可能失败的场景查询。
                # 不等待新宿主，避免旧战斗的任务在重新注入后突然播放。
                result = _game().bgm(rule['bgm'], bank=rule.get('bank'), wait=False)
                if not isinstance(result, dict) or not result.get('ok'):
                    raise RuntimeError((result.get('reason') or str(result))
                                       if isinstance(result, dict) else str(result))
                _active = rule
                locked = _lock_ready and _lock(False)
                _last_error = ''
                _say(f"换曲调用已提交：「{rule['name'] or rule['id']}」→ {rule['bgm']}"
                     f"（音库 {rule.get('bank') or '未指定'}，优先级 {rule['priority']}，"
                     f"换曲锁{'已开启' if locked else '未开启'}；未验证实际出声）")
            except Exception as exc:
                _last_error = str(exc)
                _lock(True)
                # 错误不可受「播报切换」开关屏蔽。
                _log(f"换曲失败（规则 {rule['id']}，曲目 {rule['bgm']}，"
                     f"音库 {rule.get('bank') or '未指定'}）：{exc}（保持解锁）")
            finally:
                _pending, _pending_rule = False, None

    threading.Thread(target=_submit, daemon=True, name='bgm-apply').start()
    return f"已排队换曲：规则 {rule['id']} → {rule['bgm']}（后台提交，未验证出声）"


def _on_round(battle):
    try:
        _apply(battle)
    except Exception as exc:                             # noqa: BLE001
        _log(f'回合判定出错：{exc}')


def _on_battle_end(_scene):
    """取消排队播放并解锁；离开战斗后不再调用战斗音频通道。"""
    global _active, _prev, _battle_id, _revision, _pending, _pending_rule
    with _state_lock:
        _revision += 1
        _pending, _pending_rule = False, None
        _lock(True)
        _active, _prev, _battle_id = None, {}, None
        _say('战斗结束：已取消排队换曲并解锁，场景音乐由游戏接管')


def _check_now():
    """菜单只登记后台检查，快照、扫描和状态锁等待均不占用菜单线程。"""
    _log('手动检测：收到请求')
    if not _check_guard.acquire(blocking=False):
        _log('手动检测：跳过重复请求，上一次检查仍在后台执行')
        return

    def _check():
        try:
            # 与异步放曲串行；先拿锁再取快照，避免等待期间快照失效。
            with _state_lock:
                _log('手动检测：开始读取战斗快照')
                battle = _game().battle()
                if battle is None:
                    label = (f"维持规则 {_active['id']} → {_active['bgm']}"
                             if _active else '当前没有已提交规则')
                    _log(f'手动检测：跳过扫描，快照不可用（不等于不在战斗）；{label}')
                    return
                outcome = _apply_locked(battle)
                _log(f'手动检测：{outcome}')
        except Exception as exc:
            _log(f'手动检测异常：{exc}')
        finally:
            _check_guard.release()

    try:
        threading.Thread(target=_check, daemon=True, name='bgm-check').start()
    except Exception as exc:
        _check_guard.release()
        _log(f'手动检测异常：无法启动后台检查：{exc}')


def _show_status():
    label = (_active['id'] + ' -> ' + _active['bgm']) if _active else '无已提交规则'
    _log(f"当前状态：{label}；排队={_pending}；换曲锁安装={_lock_ready}；"
         f"最后错误={_last_error or '无'}；播放调用成功不代表已验证出声")


def _restore():
    """菜单：取消待播任务、清除规则状态并恢复原曲。"""
    global _active, _prev, _revision, _pending, _pending_rule
    with _state_lock:
        _revision += 1
        _pending, _pending_rule = False, None
        _active, _prev = None, {}
        if not _lock(True):
            return
        result = _game().bgm_stop()
        if not isinstance(result, dict) or not result.get('ok'):
            _log(f'手动恢复原曲失败：{result}')
        else:
            _say('手动操作：已解锁并提交恢复原曲调用')


def _reload():
    """菜单：改完 rules.json 不用重启启动器。"""
    global RULES, WATCHED, _revision, _pending, _pending_rule
    with _state_lock:
        _revision += 1
        _pending, _pending_rule = False, None
        RULES = _load_rules()
        WATCHED = _watched()
    _say(f'规则已重新载入：{len(RULES)} 条')


def _inject():
    """手动菜单必须显示结果；失败日志不受播报开关影响。"""
    _log('正在请求注入/连接游戏宿主')
    try:
        result = _game().inject()
        _log(f'后台注入请求受理：{result}（尚未确认宿主就绪或 BGM 播放）')
        return result
    except Exception as exc:
        _log(f'注入请求失败：{exc}')
        return None


if _settings()[0]:
    # scr.py 在重载/启动游戏之前同步执行：这里只登记回调、启动后台连接。
    # 不得在此注入、安装锁、查询场景或 wait_ready；实际配置由 Service
    # 在后台检测到 GameAssembly 后推送，锁在回合事件中惰性安装。
    _game().on_round_start(_on_round)
    _game().on_battle_end(_on_battle_end)
    _game().start(menu=(
        ('注入游戏', _inject),
        ('立刻检查', _check_now),
        ('恢复原曲', _restore),
        ('查看状态', _show_status),
        ('重载规则', _reload),
    ))
    # 托盘右键菜单（FrameUnlocker 同款注册方式）
    try:
        import pystray
        _submenu = pystray.Menu(
            pystray.MenuItem('注入游戏', _inject),
            pystray.MenuItem('立刻检查', _check_now),
            pystray.MenuItem('恢复原曲', _restore),
            pystray.MenuItem('查看状态', _show_status),
            pystray.MenuItem('重载规则', _reload),
        )
        _MANAGER = ADDON_ARG.get('AddonManager')               # noqa: F821
        _register = getattr(_MANAGER, 'register_tray_item', None)
        _tray = pystray.MenuItem('战斗BGM替换', action=_submenu)
        if callable(_register):
            _register(_tray)
        elif _MANAGER is not None:
            _MANAGER.menu_items.append(_tray)
    except Exception as _exc:                                  # noqa: BLE001
        _log(f'托盘菜单注册失败：{_exc}')
    _log(f'已启动：{len(RULES)} 条规则（换曲锁版：命中即锁，游戏盖不回去）')
else:
    _log('设置里关掉了（enable=false），本次不启用')


def on_unload():
    # 卸载顺序不保证：WarpHook 可能已先被卸载，命名空间拿不到就没什么可收的
    global _revision, _pending, _pending_rule
    try:
        with _state_lock:
            _revision += 1
            _pending, _pending_rule = False, None
            # 未连接/未安装过锁时不要为了卸载创建 Host 映射或解析导出表。
            if _lock_ready:
                _lock(True)
            return _game().close()
    except Exception:                    # noqa: BLE001
        return None
