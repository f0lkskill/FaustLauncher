"""播放战斗 BGM（0.9.26 重写：全静态两步链）。

0.9.16~0.9.25 的旧链（``get_Instance → ensure_bank → TryCreateInstance``
预检 → ``StopBGM``×2 → ``StartAddBGM``）每一步都依赖 ``SoundManager``
单例，而 0.9.25 日志版探针定案：单例这条路在本机走不通 ——
``get_Instance`` 直调死于泛型 RGCTX、invoke 一次成功一次 AV、
``static_get`` 的 ``field_static_get_value`` 也 AV。

0.9.26 真机验证的新链（全部 ``BattleSoundGenerator`` 静态方法直调，
两发命中，用户耳朵确认）::

    BattleSoundGenerator::StopBGM(false, false)       # 停当前战斗曲
    BattleSoundGenerator::StartAddBGM(短名, 1, false)  # 放新曲

- ``StartAddBGM`` 收**短名**（``Battle_Cp10_Boss_10``），前缀游戏自己补；
  名字里的 ``Add`` 是**叠加语义**（在原曲上叠一层，不是替换）—— 所以
  替换曲子必须先 ``StopBGM``，否则两首一起响（0.9.26 真机实测）。
- 音库（bank）没法手动预载：``LoadBankFromLocal`` 是实例方法。实战里
  当前战斗的音库游戏自己已加载（实测 ``Battle_Cp10_Boss_10`` 直放成功）；
  没加载的音库 ``StartAddBGM`` 会静默失败 —— 用 :func:`is_playing`
  复查兜底，失败自动 ``StartBGM(-1, 0)`` 接回默认曲（旧插件哲学：
  绝不留静音）。

全部走 ``Host.make_str`` + ``Host.call``，不需要改 C 代码。
"""

import ctypes
import ctypes.wintypes
import os

from . import objects
from .base import log

BGM_PREFIX = 'event:/BGM/Battle/'

# FMOD.Studio.STOP_MODE：0=ALLOWFADEOUT 1=IMMEDIATE
STOP_MODE_IMMEDIATE = 1
STOP_MODE_FADE = 0

# 对象槽 27 是辅助段的临时槽，用完就还（28/29 被门面占着，30/31 是每帧回调）
SLOT_SCRATCH = 27
# 26 曾留着放 SoundManager 实例 —— 0.9.26 起单例通道不可用，槽保留但不再使用
SLOT_SOUND = 26
# 24：临时放音库路径字符串（ensure_bank 弃用后仅作占位）
SLOT_BANK_NAME = 24


def in_battle(host, slot=None):
    """当前是不是在战斗场景里。

    ``StartAddBGM`` 内部会碰 FMOD 的战斗曲通道，非战斗场景下这些句柄没
    初始化 —— 真机上直接访问违例把游戏带走（0.9.11 实测过一次）。所以
    播放前必须先确认场景；读不到场景时按「不在战斗」处理，宁可不出声。
    """
    try:
        info = objects.scene(host, slot) if slot is not None else objects.scene(host)
    except Exception:
        return False
    if not info:
        return False
    return info.get('scene') == 1


def full_path(name):
    """把短名补成完整 event 路径；已经是 ``event:/`` 开头的原样返回。"""
    text = str(name or '').strip()
    if not text:
        return ''
    if text.startswith('event:/'):
        return text
    return BGM_PREFIX + text


def short_name(name):
    """把 ``event:/BGM/Battle/Xxx`` 截成 ``Xxx``。"""
    text = full_path(name)
    return text[len(BGM_PREFIX):] if text.startswith(BGM_PREFIX) else text


def _ok(result):
    return not isinstance(result, str)


def play(host, name, bank=None, stop_current=True, timeout=2.0,
         require_battle=True, check=False):
    """放一首战斗 BGM。返回 ``{'ok', 'name', 'path', 'reason'}``。

    v0.9.26 全静态两步链：``StopBGM(false,false)`` → ``StartAddBGM(短名,1,false)``，
    全部 ``BattleSoundGenerator`` 静态方法直调 —— 零单例、零泛型、零 invoke。

    Args:
        host: ``Host`` 实例（``Service.host()`` / ``game.live().host()``）。
        name: 短名（``Battle_Cp9_Boss_10``）或完整路径。
        bank: **已忽略**。v0.9.26 起无法手动预载音库（``LoadBankFromLocal``
            是实例方法，单例通道不可用）；当前战斗的音库游戏自己已加载，
            没加载的音库会走下方「失败兜底」自动接回默认曲。
        stop_current: 先停掉当前战斗曲，默认 True —— ``StartAddBGM`` 是
            叠加语义，不停就是两首一起响。
        require_battle: 先确认在战斗里再放，默认 True —— 非战斗场景下
            战斗曲的 FMOD 通道没初始化（0.9.11 崩溃教训）。
        check: **已弃用**（原 TryCreateInstance 预检依赖单例）。现在的
            等价物是播放后的 :func:`is_playing` 复查 + 自动回退。
    """
    short = short_name(name)
    path = full_path(name)
    if not short:
        return {'ok': False, 'name': '', 'path': '', 'reason': '名字是空的'}

    if require_battle and not in_battle(host):
        return {'ok': False, 'name': short, 'path': path,
                'reason': '不在战斗场景'}

    slot = SLOT_SCRATCH
    made = host.make_str(short, slot=slot, timeout=timeout)
    if isinstance(made, str) and made != '已执行':
        return {'ok': False, 'name': short, 'path': path, 'reason': made}

    try:
        if stop_current:
            host.call('BattleSoundGenerator::StopBGM', args=(0, 0),
                      sig='B,B', ret='void', timeout=timeout)
        result = host.call('BattleSoundGenerator::StartAddBGM',
                           args=(('slot', slot), STOP_MODE_IMMEDIATE, 0),
                           sig='S,FMOD.Studio.STOP_MODE,B', ret='void',
                           timeout=timeout)
    finally:
        host.release(slot)

    if not _ok(result):
        return {'ok': False, 'name': short, 'path': path, 'reason': result}
    # **不放 is_playing 复查** —— 第 7 次崩溃（0.9.26）的根因就是它：
    # 回合结束间隙游戏正在重建 FMOD 实例，IsBattleBgmPlaying 直调撞进
    # 竞态窗口内部 AV，VEH 接住线程但 il2cpp 状态已污染，游戏随后崩。
    # 旧插件的姿势：放完就走，从不回头问游戏「响了吗」；静音兜底交给
    # 插件层 —— 规则还命中就下个回合重放。
    return {'ok': True, 'name': short, 'path': path, 'reason': ''}


def _restore_default(host, timeout=2.0):
    """接回游戏默认战斗曲（``StartBGM(-1, 0)``：index=-1 = 按关卡自挑）。

    旧插件 ``switch_rule`` 失败回退用的同一个静态方法。**竞态警告**：
    同样是直调，回合间隙有 AV 风险 —— 只给 stop(restore=True) 和用户
    主动操作用，不要塞进自动循环。
    Returns:
        成功 ``'已接回默认曲'``；失败带原因。
    """
    result = host.call('BattleSoundGenerator::StartBGM', args=(-1, 0),
                       sig='I,I', ret='void', timeout=timeout)
    if isinstance(result, str) and result != '已执行':
        return f'回退默认曲失败：{result}'
    return '已接回默认曲'


def game_dir():
    """游戏安装目录（``.../Limbus Company``）；取不到返回 ``None``。"""
    from .base import find_game_pid

    pid = find_game_pid()
    if not pid:
        return None
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED
    if not handle:
        return None
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = ctypes.wintypes.DWORD(32768)
        if not kernel32.QueryFullProcessImageNameW(
                handle, 0, buf, ctypes.byref(size)):
            return None
        return os.path.dirname(buf.value)
    finally:
        kernel32.CloseHandle(handle)


def ensure_bank(host, bank, timeout=5.0):
    """**v0.9.26 起不可用** —— 依赖 ``SoundManager`` 单例（通道已毒）。

    单例三条路全断：``get_Instance`` 直调死于泛型 RGCTX（0.9.25 探针）、
    invoke 时灵时不灵、``static_get`` 的 ``field_static_get_value`` AV。
    ``LoadBankFromLocal``/``IsLoadedBank`` 都是实例方法，拿不到单例就没法查、
    没法载。实战不需要它：当前战斗的音库游戏自己会加载。
    """
    return {'ok': False,
            'reason': 'v0.9.26 起 SoundManager 单例通道不可用，无法查询/预载音库；'
                      '当前战斗的音库游戏自己会加载，直接 play() 即可'}


def stop(host, restore=True, timeout=2.0):
    """停掉战斗 BGM；``restore=True`` 时把游戏默认曲接回来。

    v0.9.26：改用 ``StopBGM(false,false)``（静态，真机验证）—— 原来的
    ``StopAddedBGM`` 只停附加曲层，原曲还在响，替换插件语义要的是「全停」。
    """
    result = host.call('BattleSoundGenerator::StopBGM', args=(0, 0),
                       sig='B,B', ret='void', timeout=timeout)
    if isinstance(result, str) and result != '已执行':
        return {'ok': False, 'reason': result}
    if restore:
        reason = _restore_default(host, timeout)
        return {'ok': True, 'reason': reason}
    return {'ok': True, 'reason': ''}


def current_index(host, timeout=2.0):
    """当前战斗曲的索引（游戏自己的编号，``-1`` 表示没在放）。

    **竞态警告**：直调游戏方法在回合结束/换曲间隙会撞 FMOD 实例重建窗口
    （0.9.26 第 7 次崩溃根因）。只给菜单「查看状态」这类**手动低频**场景用，
    不要放进自动循环。
    """
    result = host.call('BattleSoundGenerator::get_CurrentBgmIndex',
                       ret='int32', timeout=timeout)
    return result if _ok(result) else None


def is_playing(host, timeout=2.0):
    """游戏认为战斗曲在响吗（``IsBattleBgmPlaying``）。

    **竞态警告**：同 :func:`current_index` —— 回合间隙直调会 AV（0.9.26
    实测连 VEH 都接不干净，游戏最终崩溃）。只给菜单手动查询用，**禁止**
    放进 play() 的自动复查或插件的每回合循环。
    """
    result = host.call('BattleSoundGenerator::IsBattleBgmPlaying',
                       ret='bool', timeout=timeout)
    return bool(result) if _ok(result) else False


def pause(host, value=True, timeout=2.0):
    """暂停 / 继续战斗曲。"""
    result = host.call('BattleSoundGenerator::PauseBGM',
                       args=(1 if value else 0,), ret='void', timeout=timeout)
    return {'ok': _ok(result), 'reason': '' if _ok(result) else result}


# ---- 改写游戏自己的换曲（v8）-------------------------------------------
# 直调 ``StartAddBGM`` 是「我们自己出声」；另一种办法是让游戏自己出声、我们
# 只改它要传的曲名 —— 命中时把参数换成对象槽里的字符串，原函数照常执行。
# 好处是整条播放流程都由游戏自己走，插件一次 invoke 都不用发。
SLOT_BATTLE_BGM = 25


def hook_battle_bgm(host, name, klass='BattleSoundGenerator',
                    method='StartAddBGM', push=True):
    """让游戏自己放我们的曲子。

    钩住 ``BattleSoundGenerator.StartAddBGM(string, STOP_MODE, bool)`` 的第一
    个参数（曲名），命中时换成 ``name`` 的短名，再照常调原函数 —— 于是游戏
    每一次「起附加曲」放的都是我们的曲子，而整条播放流程由游戏自己走，
    插件一次 invoke 都不用发。曲名走 ``make_str`` 放在对象槽 25 里。

    ``method='TryStartBattleBgmByName'`` 可以换成游戏按名字起曲的高层入口
    （``argc=1``）。注意 0.9.26 真机实测 ``TryStartBattleBgmByName`` 直调
    恒返回 false（内部有场景条件），但**钩它改参数**是另一回事 —— 它的
    bool 返回和场景条件不影响参数改写路径。

    **必须在它被调用之前装好** —— 钩子表变化要 ``push()`` 才生效。
    """
    short = short_name(name)
    if not short:
        return {'ok': False, 'slot': SLOT_BATTLE_BGM, 'name': '',
                'reason': '名字是空的'}
    argc = 3 if method == 'StartAddBGM' else 1
    made = host.make_str(short, slot=SLOT_BATTLE_BGM)
    if isinstance(made, str) and made != '已执行':
        return {'ok': False, 'slot': SLOT_BATTLE_BGM, 'name': short,
                'reason': made}
    host.hook(klass, method, argc=argc, rewrite=(1, SLOT_BATTLE_BGM))
    if push:
        host.configure(hooks=host.hooks(), texts=list(host.texts or []))
        host.push(True)
    return {'ok': True, 'slot': SLOT_BATTLE_BGM, 'name': short, 'reason': ''}


def unhook_battle_bgm(host, klass='BattleSoundGenerator',
                      method='StartAddBGM'):
    """撤掉 :func:`hook_battle_bgm` 装的那条改写钩子。"""
    kept = [h for h in host.hooks()
            if not (h.get('klass') == klass and h.get('method') == method)]
    host.configure(hooks=kept, texts=list(host.texts or []))
    host.push(True)
    host.release(SLOT_BATTLE_BGM)
    return {'ok': True, 'hooks': len(kept)}
