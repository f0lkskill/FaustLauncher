"""播放战斗 BGM（0.9.10）。

游戏用 FMOD/Wwise，战斗曲归 ``BattleSoundGenerator`` 管。旧插件
BattleBGMExtend 为了「锁住」自己放的曲子，钩了三十多个音频方法互相
放行；我们不需要那套互斥 —— 只要把想放的曲子塞进游戏的附加曲通道：

    StopBGM(false, false)              # 停掉当前战斗曲
    StartAddBGM(短名, STOP_MODE=1, false)   # 放新曲（1 = 立刻停旧的）

``StartAddBGM`` 收的是**短名**（``Battle_Cp9_Boss_10``），不是完整的
``event:/BGM/Battle/Battle_Cp9_Boss_10`` —— 前缀游戏自己补。

全部走 ``Host.make_str`` + ``Host.call``，不需要改 C 代码，也不需要
自己解析 il2cpp 导出名。
"""

from .base import log

BGM_PREFIX = 'event:/BGM/Battle/'

# FMOD.Studio.STOP_MODE：0=ALLOWFADEOUT 1=IMMEDIATE 2=ALLOWFADEOUT+...
STOP_MODE_IMMEDIATE = 1
STOP_MODE_FADE = 0

# 对象槽 27 是辅助段的临时槽，用完就还（28/29 被门面占着，30/31 是每帧回调）
SLOT_SCRATCH = 27


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


def play(host, name, stop_current=True, timeout=2.0):
    """放一首战斗 BGM。返回 ``{'ok', 'name', 'path', 'reason'}``。

    Args:
        host: ``Host`` 实例（``Service.host()`` / ``game.live().host()``）。
        name: 短名（``Battle_Cp9_Boss_10``）或完整路径。
        stop_current: 先停掉当前战斗曲，默认 True。留在原曲上面叠着
            会两条一起响，一般不需要关掉。

    名字写错时 ``ok=False``，游戏那边会继续放原曲（``StartAddBGM`` 找
    不到 event 会静默失败，返回码看不出来），所以失败时建议再调一次
    :func:`stop` 把附加通道清干净。
    """
    short = short_name(name)
    path = full_path(name)
    if not short:
        return {'ok': False, 'name': '', 'path': '', 'reason': '名字是空的'}

    slot = SLOT_SCRATCH
    made = host.make_str(short, slot=slot, timeout=timeout)
    if isinstance(made, str) and made != '已执行':
        return {'ok': False, 'name': short, 'path': path, 'reason': made}
    try:
        if stop_current:
            host.call('BattleSoundGenerator::StopBGM', args=(0, 0),
                      timeout=timeout)
        result = host.call('BattleSoundGenerator::StartAddBGM',
                           args=(('slot', slot), STOP_MODE_IMMEDIATE, 0),
                           timeout=timeout)
    finally:
        host.release(slot)

    if not _ok(result):
        return {'ok': False, 'name': short, 'path': path, 'reason': result}
    return {'ok': True, 'name': short, 'path': path, 'reason': ''}


def stop(host, restore=True, timeout=2.0):
    """停掉附加曲；``restore=True`` 时把游戏自己的战斗曲接回来。"""
    result = host.call('BattleSoundGenerator::StopAddedBGM',
                       args=(STOP_MODE_IMMEDIATE, 0), timeout=timeout)
    if isinstance(result, str) and result != '已执行':
        return {'ok': False, 'reason': result}
    if restore:
        # StartBGM(-1, 0)：index=-1 = 让游戏按当前关卡自己挑
        host.call('BattleSoundGenerator::StartBGM', args=(-1, 0),
                  timeout=timeout)
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
    result = host.call('BattleSoundGenerator::PauseBGM', args=(1 if value else 0,),
                       timeout=timeout)
    return {'ok': _ok(result), 'reason': '' if _ok(result) else result}
