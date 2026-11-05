"""规则：禁止浪费狂气。

在游戏里点抽卡时，先拦下来，然后用游戏自己的原版弹窗吐槽一句——
「又抽！？瓦夜不想过了？」。不扣狂气、不动数值，纯整活。

所有行为都由依赖插件 ``WarpHook`` 的
``warp_host.dll`` 驱动，这里只声明三件事：

1. **钩哪两个方法**——``GachaUIPresenter::OpenGachaAlarmUI``（确认框弹出，
   只旁观）与 ``GachaUIPresenter::OnGachaSelected``（真正下单，拦掉）。
2. **探针读什么**——第一个钩子把 ``GachaPayment::get_GachaType`` 的值写进
   ``vars[0]``，第二个钩子用它判断「这是不是付费单抽」。
3. **什么条件放行**——``guard_var=0 / guard_value=1`` 时，GachaType 为 1
   （付费单抽）的请求完全不拦、不弹。

弹窗同样不需要这里的进程参与：第二个钩子带 ``ACT_POPUP``，宿主命中后自己从
本插件的文案段里随机挑一句弹出来。所以启动器关掉、DLL 转入 standalone 之后
拦截与弹窗都还在，只有改设置时要重新打开启动器推一次配置。

改文案、改放行规则、开关拦截，全部只动这份 Python 文件，不必再编译任何东西。
"""

import os
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from addons.WarpHook.warp_stub import Service, WarpNamespace  # noqa: F401

ADDON_NAME = ADDON_ARG['AddonName']  # type: ignore  # noqa: F821
# 命名空间容器由启动器提供；WarpHook 把自己的能力收在 ``warp`` 这一个 space 里，
# 所以这里取完容器还得再取一层 —— 不能把整个容器直接当依赖库用，
# 那样根上谁都可以占名字，生态里就只能存在一套命名空间。
_NS = ADDON_ARG.get('Namespaces')  # type: ignore  # noqa: F821
# WarpNamespace 是依赖库给的类型桩（只给 IDE 看，运行时不会 import）：
# 这样 _W.game.gacha.on_buy(...) 在编辑器里既有补全也有参数提示。
_W = cast("WarpNamespace", _NS.space('warp') if _NS is not None else None)
_ADDON_MANAGER = ADDON_ARG.get('AddonManager')  # type: ignore  # noqa: F821


def _log(message):
    try:
        writer = getattr(getattr(_W, 'log', None), 'write', None)
        if callable(writer):
            writer(str(message), prefix=f'[{ADDON_NAME}]')
            return
    except Exception:
        pass
    print(f"[{ADDON_NAME}] {message}", flush=True)

# ========== 常量 ==========

#: 共享映射名；测试时可用 NO_GACHA_MAP_NAME 换掉，免得撞上正开着的游戏
MAP_NAME = os.environ.get("NO_GACHA_MAP_NAME") or "Local\\NoGacha_Plugin"

#: GACHA_TYPE.PAIDONLY —— 只能用「付费狂气」的提取（UI 上第一种、13 付费那个）
GACHA_TYPE_PAIDONLY = 1

#: 默认文案池（设置里的「弹窗文案列表」可以完全替换它）
DEFAULT_POPUP_TEXTS = [
    "又抽！？瓦夜不想过了？",
    "冷静一点，但丁！狂气不是大风刮来的！",
    "去刷镜牢换碎片，别在这赌狗！",
    "维吉里乌斯正在看着你的狂气余额……",
    "浮士德计算表明：你这发十连只有保底。",
    "联动限定不要了？现在抽卡到时候哭都来不及！",
    "管好你的手，经理！",
    "再忍忍，下个池子更强！",
    "梅菲斯托费勒斯号不需要赌徒。",
    "系统已强制没收你的抽卡冲动，请回镜牢坐牢。",
]
DEFAULT_AUTO = True
#: 默认放行「付费单抽」
DEFAULT_ALLOW_PAID = True


# ========== 业务：文案池 ==========


def _parse_text_items(raw_val):
    """把字符串（支持 ``|`` 或换行分隔）或列表解析为去重后的非空文案列表。"""
    result = []
    if isinstance(raw_val, list):
        for item in raw_val:
            result.extend(_parse_text_items(item))
    elif isinstance(raw_val, str):
        for part in raw_val.replace("\r\n", "\n").replace("\n", "|").split("|"):
            cleaned = part.strip()
            if cleaned and cleaned not in result:
                result.append(cleaned)
    return result


def _settings():
    """读这个插件的设置，返回 ``(texts, auto, allow_paid)``。"""
    info = (_ADDON_MANAGER.get_addon_info(ADDON_NAME) if _ADDON_MANAGER else {}) or {}
    st = info.get('settings') or {}
    texts = []
    # 同时兼容「弹窗文案列表」与「弹窗文案」，自动合并去重
    for key in ('弹窗文案列表', '弹窗文案'):
        for item in _parse_text_items(st.get(key)):
            if item not in texts:
                texts.append(item)
    # 用户没配、或者只留了原始默认那一句时，用内置的多文案池
    if not texts or texts == ["又抽！？瓦夜不想过了？"]:
        texts = list(DEFAULT_POPUP_TEXTS)
    auto = bool(st.get('自动注入', DEFAULT_AUTO))
    allow_paid = bool(st.get('放行付费单抽', DEFAULT_ALLOW_PAID))
    return texts, auto, allow_paid


# 运行骨架实例（赋值在文件末尾）。这里前置声明一次，让静态检查知道有这个名字，
# 也让阅读者一眼看到「真正干活的是 service，不是我」。
service: "Service"


# ========== 运行骨架（全部交给 WarpHook）==========


def _push():
    """把当前设置写进共享内存。Service 需要推配置时就调这里。"""
    texts, _auto, allow_paid = _settings()
    host = service.host()
    host.configure(texts=texts)
    # 拦截和弹窗都由宿主 DLL 自己完成：命中即拦、即从本插件文案段里随机弹一条。
    # 这条路不经过 Python，所以启动器关掉后 DLL 转入 standalone 仍然照弹。
    message = _W.game.gacha.watch_native(host=host, allow_paid=allow_paid)
    return message is not None and message != "共享内存不可用"


service = _W.plugin.Service(
    addon_name=ADDON_NAME,
    name=ADDON_NAME,
    sync=_push,
    auto=lambda: _settings()[1],
    menu=(
        ('注入拦截', lambda: service.inject_now(wait=True)),
        ('解除拦截', lambda: service.set_enabled(False)),
        ('应用设置', lambda: service.sync()),
    ),
)

# ---------- 启动器会在卸载时调用 ----------


def on_unload():
    """插件卸载：后台流程、抽卡循环、映射视图一起收掉。"""
    return service.stop()

# 自己先把后台流程点起来。启动器的 gamestart 通知只是「更快」，不能当唯一开关：
# 独立宿主进程里没人发那条通知，少了这一步插件就永远不登记钩子。
if _settings()[1]:
    service.start()

_log("抽卡拦截插件成功载入~ 版本：V0.2.1！")