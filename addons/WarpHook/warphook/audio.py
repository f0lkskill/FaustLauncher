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

import ctypes
import ctypes.wintypes
import os

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


def try_create(host, name, timeout=2.0):
    """照旧插件的预检：让游戏自己造一个事件实例，造得出来才说明名字有效。

    旧插件的 ``switch_rule`` 在停原曲**之前**先调
    ``SoundManager.TryCreateInstance(path, out instance)``；失败就报
    「Cannot create BGM: %s; original music retained.」直接返回。少了这一步，
    名字拼错时我们会先把原曲停掉、``StartAddBGM`` 再静默失败，玩家就只剩静音
    （0.9.16 真机踩过一晚上）。

    第二个参数是 ``FMOD.Studio.EventInstance&``（值类型 out），走 v9 的
    ``('buf', 0)`` 参数：共享内存里那 64 字节交给游戏写，写完我们读回来。

    Returns:
        ``{'ok', 'result', 'handle', 'raw'}`` —— ``handle`` 是造出来的
        EventInstance 内部句柄（0 表示没造出来）。
    """
    import struct

    path = full_path(name)
    if not path:
        return {'ok': False, 'result': '名字是空的', 'handle': 0, 'raw': None}
    if not host.object_ptr(SLOT_SOUND):
        host.call('SoundManager::get_Instance', ret='ref',
                  out_slot=SLOT_SOUND, timeout=timeout)
    if not host.object_ptr(SLOT_SOUND):
        return {'ok': False, 'result': '拿不到 SoundManager',
                'handle': 0, 'raw': None}

    host.clear_buf(0)
    made = host.make_str(path, slot=SLOT_BANK_NAME, timeout=timeout)
    if isinstance(made, str) and made != '已执行':
        return {'ok': False, 'result': made, 'handle': 0, 'raw': None}
    try:
        result = host.call('SoundManager::TryCreateInstance', slot=SLOT_SOUND,
                           args=(('slot', SLOT_BANK_NAME), ('buf', 0)),
                           timeout=timeout)
    finally:
        host.release(SLOT_BANK_NAME)
    raw = host.read_buf(0)
    handle = 0
    if raw and len(raw) >= 8:
        handle = struct.unpack('<Q', raw[:8])[0]
    log(f'TryCreateInstance({path}) -> {result} handle=0x{handle:x}')
    return {'ok': handle != 0, 'result': result, 'handle': handle, 'raw': raw}


def play(host, name, bank=None, stop_current=True, timeout=2.0,
         require_battle=True, check=True):
    """放一首战斗 BGM。返回 ``{'ok', 'name', 'path', 'reason'}``。

    顺序照旧插件 ``switch_rule``，但**先把音库准备好，再动原曲** —— 音库
    没加载时 ``StartAddBGM`` 会静默失败，如果此时已经把原曲停掉，玩家就
    只剩静音（0.9.16 真机踩过）。

    Args:
        host: ``Host`` 实例（``Service.host()`` / ``game.live().host()``）。
        name: 短名（``Battle_Cp9_Boss_10``）或完整路径。
        bank: 曲目所在音库名（``BGM_Default_S7_3``，不含 ``.bank``）。
            给了就先调 ``LoadBankFromLocal`` 把它加进来 —— 别的关卡的曲
            不在当前已加载的音库里，这一步不能省。
        stop_current: 先停掉当前战斗曲，默认 True。
        require_battle: 先确认在战斗里再放，默认 True —— 非战斗场景下
            战斗曲的 FMOD 通道没初始化，这一步不能省。

    只读的 :func:`is_playing` / :func:`current_index` 也走同一条命令通道。
    """
    short = short_name(name)
    path = full_path(name)
    if not short:
        return {'ok': False, 'name': '', 'path': '', 'reason': '名字是空的'}

    if require_battle and not in_battle(host):
        return {'ok': False, 'name': short, 'path': path,
                'reason': '不在战斗场景'}

    slot = SLOT_SCRATCH
    # 旧插件顺序：先拿 SoundManager 实例 → 准备音库 → 停旧曲（两个 StopBGM
    # 都要调）→ StartAddBGM。少一步 SoundManager.StopBGM 就是 0.9.10 的崩溃。
    sound = host.call('SoundManager::get_Instance', ret='ref',
                      out_slot=SLOT_SOUND, timeout=timeout)
    has_sound = bool(host.object_ptr(SLOT_SOUND))

    try:
        if bank:
            loaded = ensure_bank(host, bank, timeout=max(timeout, 5.0))
            if not loaded.get('ok'):
                return {'ok': False, 'name': short, 'path': path,
                        'reason': loaded.get('reason') or '音库加载失败'}

        # 旧插件的预检：先让游戏造一个事件实例试试名字，造不出来就别停原曲。
        # 少了这一步，名字拼错 = 停掉原曲 + StartAddBGM 静默失败 = 只剩静音。
        if check:
            probe = try_create(host, short, timeout=timeout)
            if not probe.get('ok'):
                return {'ok': False, 'name': short, 'path': path,
                        'reason': f"事件名无效（TryCreateInstance: "
                                  f"{probe.get('result')}）"}

        made = host.make_str(short, slot=slot, timeout=timeout)
        if isinstance(made, str) and made != '已执行':
            return {'ok': False, 'name': short, 'path': path, 'reason': made}

        if stop_current:
            host.call('BattleSoundGenerator::StopBGM', args=(0, 0),
                      timeout=timeout)
            if has_sound:
                host.call('SoundManager::StopBGM', slot=SLOT_SOUND,
                          args=(0,), timeout=timeout)
        result = host.call('BattleSoundGenerator::StartAddBGM',
                           args=(('slot', slot), STOP_MODE_IMMEDIATE, 0),
                           timeout=timeout)
    finally:
        host.release(slot)

    if not _ok(result):
        return {'ok': False, 'name': short, 'path': path, 'reason': result}
    return {'ok': True, 'name': short, 'path': path, 'reason': ''}


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
    """把音库 ``bank`` 加载进来（重复调用无害）。

    游戏自己的 ``LoadBankFromLocal`` 收的是**绝对路径**，一个音库要加两个
    文件：``X.assets.bank`` 与 ``X.bank``（旧插件就是按这个顺序加两遍的）。
    音库由游戏持有和卸载，插件只触发加载。

    注意**不要**用 ``SoundManager.IsLoadedBank`` 先查状态：它有两个 1 参
    重载（``AssetReference`` / ``string``），宿主按「名字 + 参数个数」选
    方法会挑错重载，把字符串当对象指针传进去 —— 直接崩（0.9.16 实测）。
    """
    from .base import log

    root = game_dir()
    if not root:
        return {'ok': False, 'reason': '找不到游戏进程'}
    if not host.object_ptr(SLOT_SOUND):
        got = host.call('SoundManager::get_Instance', ret='ref',
                        out_slot=SLOT_SOUND, timeout=timeout)
        if not host.object_ptr(SLOT_SOUND):
            return {'ok': False, 'reason': f'拿不到 SoundManager（{got}）'}

    base_dir = os.path.join(root, 'LimbusCompany_Data', 'StreamingAssets',
                            'Assets', 'Sound', 'FMODBuilds', 'Desktop')
    slot = SLOT_BANK_NAME
    tried = []
    try:
        for suffix in ('.assets', ''):
            target = os.path.join(base_dir, f'{bank}{suffix}.bank')
            if not os.path.exists(target):
                tried.append(f'{bank}{suffix}.bank 不存在')
                continue
            made = host.make_str(target, slot=slot, timeout=timeout)
            if isinstance(made, str) and made != '已执行':
                return {'ok': False, 'reason': made}
            result = host.call('SoundManager::LoadBankFromLocal',
                               slot=SLOT_SOUND,
                               args=(('slot', slot), 0, 0),
                               timeout=max(timeout, 10.0))
            if not _ok(result):
                return {'ok': False, 'reason': f'LoadBankFromLocal: {result}'}
            tried.append(f'{bank}{suffix}.bank')
    finally:
        host.release(slot)
    if not tried:
        return {'ok': False, 'reason': f'音库里没有可用文件（{bank}）'}
    log(f'音库就绪：{", ".join(tried)}')
    return {'ok': True, 'reason': '', 'files': tried}


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
    result = host.call('BattleSoundGenerator::PauseBGM',
                       args=(1 if value else 0,), timeout=timeout)
    return {'ok': _ok(result), 'reason': '' if _ok(result) else result}


# ---- 改写游戏自己的换曲（v8）-------------------------------------------
# 直调 ``StartAddBGM`` 是「我们自己出声」；另一种办法是让游戏自己出声、我们
# 只改它要传的曲名 —— 命中时把参数换成对象槽里的字符串，原函数照常执行。
# 好处是整条播放流程都由游戏自己走，插件一次 invoke 都不用发。
SLOT_BATTLE_BGM = 25
# 24：临时放音库路径字符串（比 SLOT_BATTLE_BGM 早定义，play() 里也用）
SLOT_BANK_NAME = 24


def hook_battle_bgm(host, name, klass='BattleSoundGenerator',
                    method='StartAddBGM', push=True):
    """让游戏自己放我们的曲子。

    钩住 ``BattleSoundGenerator.StartAddBGM(string, STOP_MODE, bool)`` 的第一
    个参数（曲名），命中时换成 ``name`` 的短名，再照常调原函数 —— 于是游戏
    每一次「起附加曲」放的都是我们的曲子，而整条播放流程由游戏自己走，
    插件一次 invoke 都不用发。曲名走 ``make_str`` 放在对象槽 25 里。

    ``method='TryStartBattleBgmByName'`` 可以换成游戏按名字起曲的高层入口
    （``argc=1``），两者二选一。

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
