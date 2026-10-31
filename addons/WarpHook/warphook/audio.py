"""播放战斗 BGM（0.9.10，0.9.13 按旧插件流程补全）。

游戏用 FMOD/Wwise，战斗曲归 ``BattleSoundGenerator`` 管。旧插件
BattleBGMExtend 为了「锁住」自己放的曲子，钩了三十多个音频方法互相
放行；我们不需要那套互斥 —— 但**它换曲那三步一步都不能少**
（``battlebgmextend.c`` 的 ``switch_rule``）：

    sound = SoundManager.get_Instance()
    StopBGM(false, false)              # 停掉当前战斗曲
    sound.StopBGM(false)               # 再清一次 SoundManager 侧的状态
    StartAddBGM(短名, STOP_MODE=1, false)   # 放新曲（1 = 立刻停旧的）

0.9.10 漏了中间那步 ``SoundManager.StopBGM``，``StartAddBGM`` 内部碰到的
FMOD 实例状态不干净 —— 真机上是直接访问违例把游戏带走。

``StartAddBGM`` 收的是**短名**（``Battle_Cp9_Boss_10``），不是完整的
``event:/BGM/Battle/Battle_Cp9_Boss_10`` —— 前缀游戏自己补。

全部走 ``Host.make_str`` + ``Host.call``，不需要改 C 代码，也不需要
自己解析 il2cpp 导出名。
"""

from . import objects
from .base import log

BGM_PREFIX = 'event:/BGM/Battle/'

# FMOD.Studio.STOP_MODE：0=ALLOWFADEOUT 1=IMMEDIATE 2=ALLOWFADEOUT+...
STOP_MODE_IMMEDIATE = 1
STOP_MODE_FADE = 0

# 对象槽 27 是辅助段的临时槽，用完就还（28/29 被门面占着，30/31 是每帧回调）
SLOT_SCRATCH = 27
# 26 留着放 SoundManager 实例（get_Instance 的 ref 出参）
SLOT_SOUND = 26


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


def play(host, name, stop_current=True, timeout=2.0, require_battle=True,
         allow_unsafe=False):
    """放一首战斗 BGM。返回 ``{'ok', 'name', 'path', 'reason'}``。

    .. danger:: **默认拒绝，因为没有安全路径**
       ``BattleSoundGenerator.StartAddBGM`` 在 il2cpp ``runtime_invoke`` 下
       调用时内部会访问违例（0.9.10 崩过两次，0.9.12 的异常保护接住了
       第一击，但进程随后仍然死）。这条调用链目前**确认不安全**，所以
       默认直接返回 ``ok=False``，要冒险自己传 ``allow_unsafe=True``。

    Args:
        host: ``Host`` 实例（``Service.host()`` / ``game.live().host()``）。
        name: 短名（``Battle_Cp9_Boss_10``）或完整路径。
        stop_current: 先停掉当前战斗曲，默认 True。
        require_battle: 先确认在战斗里再放，默认 True。
        allow_unsafe: 真的去调 ``StartAddBGM``。会让游戏进程消失，
            只在你自己能承受重开游戏时用。

    只读的 :func:`is_playing` / :func:`current_index` 是安全的 —— 它们是
    纯 getter，不会碰 FMOD 的实例状态。
    """
    short = short_name(name)
    path = full_path(name)
    if not short:
        return {'ok': False, 'name': '', 'path': '', 'reason': '名字是空的'}

    if not allow_unsafe:
        return {'ok': False, 'name': short, 'path': path,
                'reason': 'StartAddBGM 会让游戏崩，默认不调用（要冒险传 allow_unsafe=True）'}

    if require_battle and not in_battle(host):
        return {'ok': False, 'name': short, 'path': path,
                'reason': '不在战斗场景'}

    slot = SLOT_SCRATCH
    made = host.make_str(short, slot=slot, timeout=timeout)
    if isinstance(made, str) and made != '已执行':
        return {'ok': False, 'name': short, 'path': path, 'reason': made}

    # 旧插件顺序：先拿 SoundManager 实例，再停旧曲（两个 StopBGM 都要调），
    # 最后才 StartAddBGM。少一步 SoundManager.StopBGM 就是 0.9.10 的崩溃。
    try:
        sound = host.call('SoundManager::get_Instance', ret='ref',
                          out_slot=SLOT_SOUND, timeout=timeout, unsafe=True)
        has_sound = bool(host.object_ptr(SLOT_SOUND))
        if stop_current:
            host.call('BattleSoundGenerator::StopBGM', args=(0, 0),
                      timeout=timeout, unsafe=True)
            if has_sound:
                host.call('SoundManager::StopBGM', slot=SLOT_SOUND,
                          args=(0,), timeout=timeout, unsafe=True)
        result = host.call('BattleSoundGenerator::StartAddBGM',
                           args=(('slot', slot), STOP_MODE_IMMEDIATE, 0),
                           timeout=timeout, unsafe=True)
    finally:
        host.release(slot)

    if not _ok(result):
        return {'ok': False, 'name': short, 'path': path, 'reason': result}
    return {'ok': True, 'name': short, 'path': path, 'reason': ''}


def stop(host, restore=True, timeout=2.0):
    """停掉附加曲；``restore=True`` 时把游戏自己的战斗曲接回来。"""
    result = host.call('BattleSoundGenerator::StopAddedBGM',
                       args=(STOP_MODE_IMMEDIATE, 0), timeout=timeout,
                       unsafe=True)
    if isinstance(result, str) and result != '已执行':
        return {'ok': False, 'reason': result}
    if restore:
        # StartBGM(-1, 0)：index=-1 = 让游戏按当前关卡自己挑
        host.call('BattleSoundGenerator::StartBGM', args=(-1, 0),
                  timeout=timeout, unsafe=True)
    return {'ok': True, 'reason': ''}


def current_index(host, timeout=2.0):
    """当前战斗曲的索引（游戏自己的编号，``-1`` 表示没在放）。"""
    result = host.call('BattleSoundGenerator::get_CurrentBgmIndex',
                       timeout=timeout)
    return result if _ok(result) else None


def is_playing(host, timeout=2.0):
    """游戏认为战斗曲在响吗（``IsBattleBgmPlaying``）。"""
    result = host.call('BattleSoundGenerator::IsBattleBgmPlaying',
                       timeout=timeout)
    return bool(result) if _ok(result) else False


def pause(host, value=True, timeout=2.0):
    """暂停 / 继续战斗曲。"""
    result = host.call('BattleSoundGenerator::PauseBGM', args=(1 if value else 0,), unsafe=True,
                       timeout=timeout)
    return {'ok': _ok(result), 'reason': '' if _ok(result) else result}
