"""战斗 BGM 原语。

沿用独立旧版的短名 StartAddBGM 通道、指定音库预载和停曲顺序。
音库预载失败不停止原曲；不自动轮询 FMOD 播放状态（场景切换存在竞态）。
返回 ok 仅表示命令成功执行，verified=False 明示未证实实际出声。
"""

import ctypes
import ctypes.wintypes
import os

from . import objects
from .base import log as _log

BGM_PREFIX = 'event:/BGM/Battle/'

# FMOD.Studio.STOP_MODE：0=ALLOWFADEOUT 1=IMMEDIATE
STOP_MODE_IMMEDIATE = 1
STOP_MODE_FADE = 0

# 对象槽 27 是辅助段的临时槽，用完就还（28/29 被门面占着，30/31 是每帧回调）
SLOT_SCRATCH = 27
# 26：静态字段读取取得的 SoundManager 临时实例
SLOT_SOUND = 26
# 24：音库名与绝对路径字符串临时槽
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
    """``host.call`` 的成功判定：ret='void' 的成功返回值就是「已执行」字符串
    （v0.9.27 真机教训：``not isinstance(str)`` 把成功误判成失败，插件于是
    不上锁 —— 游戏盖回默认曲时和我们的曲撞车，游戏崩溃）。"""
    if not isinstance(result, str):
        return isinstance(result, (bool, int, float)) and result is not False
    return result == '已执行'


def ensure_bank(host, bank, timeout=5.0):
    """按旧版预载指定音库；失败不停止当前曲。返回 ``(ok, reason)``。

    从继承的静态字段取得实例，不调用泛型 get_Instance；两个音库文件均
    使用游戏安装目录的绝对路径。所有临时槽在成功、失败和异常路径释放。
    """
    bank = str(bank or '').strip()
    if not bank:
        return True, '未指定音库'
    if '/' in bank or '\\' in bank or bank in ('.', '..'):
        return False, '音库应为短名，不能包含路径'
    try:
        got = host.static_get('SoundManager::_instance', out_slot=SLOT_SOUND,
                              timeout=timeout)
        if not _ok(got):
            return False, f'SoundManager 单例拿不到：{got}'
        made = host.make_str(bank, slot=SLOT_BANK_NAME, timeout=timeout)
        if not _ok(made):
            return False, f'音库名造不出来：{made}'
        # 独立旧版通过 runtime_invoke 调用 SoundManager；该路径要求宿主
        # 正确区分引用参数（对象本身）和值参数（地址），不能沿用 direct 打包。
        kw = dict(slot=SLOT_SOUND, timeout=timeout, via='invoke')
        loaded = host.call('SoundManager::IsLoadedBank',
                           args=(('slot', SLOT_BANK_NAME),),
                           sig='S', ret='bool', **kw)
        _log(f'音库预载 bank={bank} stage=query-before via=invoke result={loaded!r}')
        if loaded is True:
            return True, '已加载'
        if loaded is not False:
            return False, f'音库查询失败：{loaded}'
        directory = game_dir()
        if not directory:
            return False, '游戏安装目录不可用，未尝试相对路径预载'
        base = os.path.join(directory, 'LimbusCompany_Data', 'StreamingAssets',
                            'Assets', 'Sound', 'FMODBuilds', 'Desktop')
        for suffix in ('.assets.bank', '.bank'):
            path = os.path.join(base, bank + suffix).replace('\\', '/')
            # 文件检查提供诊断证据，不把 void 调用返回当作 FMOD 加载成功。
            try:
                size = os.path.getsize(path)
            except OSError:
                size = None
            _log(f'音库预载 bank={bank} stage=load via=invoke path={path} bytes={size}')
            made = host.make_str(path, slot=SLOT_BANK_NAME, timeout=timeout)
            if not _ok(made):
                return False, f'音库路径造不出来：{made}'
            result = host.call('SoundManager::LoadBankFromLocal',
                               args=(('slot', SLOT_BANK_NAME), 0, 0),
                               sig='S,B,B', ret='void', slot=SLOT_SOUND,
                               via='invoke', timeout=max(timeout * 2.5, 5.0))
            if not _ok(result):
                return False, f'音库加载失败（{path}）：{result}'
        # 对齐独立旧版：两次加载调用完成即继续，不以登记查询作为硬门槛。
        _log(f'音库预载 bank={bank} stage=submitted via=invoke；'
             '两次加载调用完成，继续尝试播放（未验证出声）')
        return True, '预载调用已完成，未验证出声'
    except Exception as exc:
        return False, f'音库预载异常：{exc}'
    finally:
        for slot in (SLOT_BANK_NAME, SLOT_SOUND):
            try:
                host.release(slot)
            except Exception as exc:
                _log(f'音库临时槽 {slot} 释放失败：{exc}')


def play(host, name, bank=None, stop_current=True, timeout=2.0,
         require_battle=True, check=False):
    """放一首战斗 BGM。返回 ``{'ok', 'name', 'path', 'reason'}``。

    v0.9.26 全静态两步链：``StopBGM(false,false)`` → ``StartAddBGM(短名,1,false)``，
    全部 ``BattleSoundGenerator`` 静态方法直调 —— 零单例、零泛型、零 invoke。

    Args:
        host: ``Host`` 实例（``Service.host()`` / ``game.live().host()``）。
        name: 短名（``Battle_Cp9_Boss_10``）或完整路径。
        bank: 指定音库短名；播放前通过 SoundManager 静态字段取得实例，
            查询并预载 assets.bank/bank，失败保留原曲。
        stop_current: 先停掉当前战斗曲，默认 True —— ``StartAddBGM`` 是
            叠加语义，不停就是两首一起响。
        require_battle: 先确认在战斗里再放，默认 True —— 非战斗场景下
            战斗曲的 FMOD 通道没初始化（0.9.11 崩溃教训）。
        check: 兼容参数，当前不执行有竞态风险的自动播放状态检查。
    """
    short = short_name(name)
    path = full_path(name)
    if not short:
        return {'ok': False, 'name': '', 'path': '', 'reason': '名字是空的'}

    if require_battle:
        # 场景读数链不可靠（经常 None）。这里只拦「明确不在战斗」：
        # 读得到且 scene != 1 才拒绝；读不到时放行 —— 回合钩子命中本身
        # 就说明在战斗里，别让两道门打架（外层已按命中继续，内层又拒）。
        try:
            info = objects.scene(host)
        except Exception:
            info = None
        scene = (info or {}).get('scene')
        if scene is not None and scene != 1:
            return {'ok': False, 'name': short, 'path': path,
                    'reason': f'不在战斗场景（scene={scene}）'}

    slot = SLOT_SCRATCH
    if bank:
        # 和旧版一样：预载失败必须保留原曲，不在未知音库上撞运气。
        ok, why = ensure_bank(host, str(bank), timeout=timeout)
        if not ok:
            return {'ok': False, 'name': short, 'path': path,
                    'reason': f'音库预载未通过（{bank}）：{why}',
                    'stage': 'bank', 'bank': str(bank)}
    try:
        made = host.make_str(short, slot=slot, timeout=timeout)
        if not _ok(made):
            return {'ok': False, 'name': short, 'path': path,
                    'reason': f'曲名创建失败：{made}', 'stage': 'string'}
        if stop_current:
            stopped = host.call('BattleSoundGenerator::StopBGM', args=(0, 0),
                                sig='B,B', ret='void', timeout=timeout)
            if not _ok(stopped):
                return {'ok': False, 'name': short, 'path': path,
                        'reason': f'停止原曲失败：{stopped}', 'stage': 'stop'}
        result = host.call('BattleSoundGenerator::StartAddBGM',
                           args=(('slot', slot), STOP_MODE_IMMEDIATE, 0),
                           sig='S,FMOD.Studio.STOP_MODE,B', ret='void',
                           timeout=timeout)
    finally:
        host.release(slot)

    if not _ok(result):
        return {'ok': False, 'name': short, 'path': path, 'reason': f'附加曲调用失败：{result}',
                'stage': 'start'}
    # **不放 is_playing 复查** —— 第 7 次崩溃（0.9.26）的根因就是它：
    # 回合结束间隙游戏正在重建 FMOD 实例，IsBattleBgmPlaying 直调撞进
    # 竞态窗口内部 AV，VEH 接住线程但 il2cpp 状态已污染，游戏随后崩。
    # 旧版另用 FMOD event 验证实际播放；当前桥接不支持该安全预检。
    # 不把命令成功等同于实际出声，也不额外添加危险自动查询。
    return {'ok': True, 'name': short, 'path': path, 'reason': '',
            'stage': 'submitted', 'verified': False}


def _restore_default(host, timeout=2.0):
    """接回游戏默认战斗曲（``StartBGM(-1, 0)``：index=-1 = 按关卡自挑）。

    旧插件 ``switch_rule`` 失败回退用的同一个静态方法。**竞态警告**：
    同样是直调，回合间隙有 AV 风险 —— 只给 stop(restore=True) 和用户
    主动操作或条件失效时的一次性后台交还使用，不要塞进周期查询循环。
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
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    # Win64 HANDLE 不能使用 ctypes 默认 c_int 返回值，否则高位被截断。
    kernel32.OpenProcess.argtypes = [ctypes.wintypes.DWORD,
                                    ctypes.wintypes.BOOL,
                                    ctypes.wintypes.DWORD]
    kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD,
        ctypes.wintypes.LPWSTR, ctypes.POINTER(ctypes.wintypes.DWORD)]
    kernel32.QueryFullProcessImageNameW.restype = ctypes.wintypes.BOOL
    kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
    kernel32.CloseHandle.restype = ctypes.wintypes.BOOL
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



def stop(host, restore=True, timeout=2.0):
    """停掉战斗 BGM；``restore=True`` 时把游戏默认曲接回来。

    必须分别停止附加曲与主曲；StopBGM 不能代替 StopAddedBGM。
    调用前须放行换曲锁，否则插件自己的停止调用也会被阻断。
    """
    added = host.call('BattleSoundGenerator::StopAddedBGM',
                      args=(STOP_MODE_IMMEDIATE, 0),
                      sig='FMOD.Studio.STOP_MODE,B', ret='void', timeout=timeout)
    if not _ok(added):
        return {'ok': False, 'reason': f'停止附加曲失败：{added}'}
    result = host.call('BattleSoundGenerator::StopBGM', args=(0, 0),
                       sig='B,B', ret='void', timeout=timeout)
    if isinstance(result, str) and result != '已执行':
        return {'ok': False, 'reason': result}
    if restore:
        reason = _restore_default(host, timeout)
        return {'ok': reason == '已接回默认曲', 'reason': reason}
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


# ---- 换曲锁（0.9.27）：拦住游戏回合结束的「盖回默认曲」-------------------
# 旧插件哲学（battlebgmextend.c 的 block_game）：曲子放出来后锁住所有换曲
# 入口，游戏想换/想停一律丢弃 —— FMOD 实例不中断，不重播。guard 机制
# （vars[LOCK_SLOT] == 1 时放行原调用）让锁的开/关只是一次内存写入，
# 不用每回合重推钩子表；「先解锁 → 放曲 → 再上锁」的时序也顺势绕开了
# 旧插件 own_call() 那套「自己的调用要放行」的复杂度。
LOCK_SLOT = 4        # vars[4]：1=放行（游戏管曲） 0=锁（只许我们的曲）
# 辅段一共只有 5 格（27..31），门面回合钩子要占 1 格：锁钩子最多 4 条。
# 当前覆盖以下四条入口，并非完整复刻旧插件 block_game。
# 旧版还拦 SoundManager/CurrentBGM/FMOD 等入口；不能无证据宣称它们
# 只在场景切换时调用。是否仍有绕行路径，需要实际 blocked 计数诊断。
LOCK_TARGETS = (
    ('BattleSoundGenerator', 'StartBGM', 2),
    ('BattleSoundGenerator', 'StartAddBGM', 3),
    ('BattleSoundGenerator', 'StopBGM', 2),
    # StartAddBGM 的配对停止入口；旧版明确同时保护，不能只拦主曲 StopBGM。
    ('BattleSoundGenerator', 'StopAddedBGM', 2),
)


def guard_hook_defs():
    """锁钩子定义列表（并入门面钩子表、与回合钩子一次 push 共存）。"""
    return [{'klass': k, 'method': m, 'argc': a, 'actions': 0,
             'block': True, 'guard': (LOCK_SLOT, 1)}
            for k, m, a in LOCK_TARGETS]


def guard_status(host, owner=None):
    """只读实际锁配置及计数；有配置不等于原生安装成功，更不等于出声。"""
    targets = {(k, m) for k, m, _ in LOCK_TARGETS}
    rows = [row for row in host.hook_status(owner=owner)
            if (row['klass'], row['method']) in targets]
    configured = {(row['klass'], row['method']) for row in rows}
    return {'targets': len(targets), 'configured': len(rows), 'rows': rows,
            'missing': [f'{k}.{m}' for k, m, _ in LOCK_TARGETS
                        if (k, m) not in configured],
            'coverage': 'partial', 'installed_verified': False}


def install_guard_hooks(host):
    """装换曲锁钩子（独立 push；门面请改用 :func:`guard_hook_defs` 合并）。

    .. deprecated:: v0.9.27
       独立 push 会覆盖同一 owner 的回合钩子（钩子表按 owner 分段、
       configure 全量重写）——门面 :meth:`Battle.bgm_lock_install` 已改为
       把 :func:`guard_hook_defs` 并进自己钩子表一次 push。本函数仅
       保留给没有回合回调的裸 Host 用户。
    """
    host.clear_hooks()
    for item in guard_hook_defs():
        host.hook(item['klass'], item['method'], argc=item['argc'],
                  block=True, guard=(LOCK_SLOT, 1))
    host.configure(hooks=host.hooks(), texts=list(host.texts or []))
    host.push(True)
    return {'ok': True, 'targets': len(LOCK_TARGETS)}


def lock(host, allow):
    """开/关换曲锁。``allow=True`` 放行游戏换曲（解锁）；``False`` 锁死。

    一次共享内存写入，随时可调、零直调。放曲前先 ``lock(host, True)``，
    否则自己的 StopBGM/StartAddBGM 直调会撞上自己的锁。
    """
    return host.set_var(LOCK_SLOT, 1 if allow else 0)


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
