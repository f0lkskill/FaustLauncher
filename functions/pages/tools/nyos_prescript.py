#! 今日指令?
#? 词库来源: config/nyos_prescript.json
#? 使用 pywebview 展示: html/nyos_prescript/index.html

import difflib
import os
import random
import subprocess
import sys

if getattr(sys, "frozen", False):
    # 打包环境下模块在临时解压目录, 以 exe 所在目录为项目根目录 (config/html/assets 在 exe 旁)
    _PROJECT_ROOT = os.path.dirname(os.path.abspath(sys.executable))
else:
    _PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

try:
    from functions.base.common.json_io import read_json
except ImportError:
    import json

    def read_json(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)

CONFIG_PATH = os.path.join(_PROJECT_ROOT, "config", "nyos_prescript.json")

DEFAULT_DATA = {
    "do": [
        "&time&击杀&pepople&",
        "在目击到&pepople&后立刻&action&",
        "在&where&&do&",
        "今天结束前，不要想起这条指令",
        "选择一条从未走过的路回家",
        "尽量让所有人都看不出你在执行指令",
    ],
    "where": ["街道", "商场", "学校", "医院", "图书馆", "咖啡馆"],
    "people": ["陌生人", "你认识的人", "你的挚亲", "正在&action&的人", "从未谋面的人", "看起来最心不在焉的人"],
    "when": ["眨眼&count&次之后", "&time&", "路灯亮起的时候", "太阳正对头顶的时候"],
    "actions": ["深呼吸三次", "低头系鞋带", "发呆", "向&pepople&点头"],
    "drinks": ["水", "牛奶", "爱", "你最喜欢的饮料"],
    "foods": ["苹果", "包子", "饭团", "三明治"],
    "objects": ["硬币", "一支笔", "一张便利贴", "一片落叶"],
    "songs": ["小星星", "生日快乐歌", "卡农"],
    "words": ["早安", "谢谢", "对不起", "一切都好"],
    "creatures": ["鸽子", "流浪猫", "蝴蝶", "蚂蚁"],
    "direction": ["左", "右", "前", "后"],
    "turn": ["顺时针", "逆时针"],
    "color": ["红", "蓝", "白", "你难以定义的颜色"],
}


class NyosPrescript:
    """
    今日指令
    """
    do = []
    where = []
    people = []
    when = []
    actions = []
    drinks = []
    foods = []
    objects = []
    songs = []
    words = []
    creatures = []
    direction = []
    turn = []
    color = []
    mems = []
    where_flag = False

    def __init__(self):
        pass

    @staticmethod
    def reload_data():
        """
        从 config/nyos_prescript.json 重新加载词库
        """
        keys = ["do", "where", "people", "when", "actions", "drinks",
                "foods", "objects", "songs", "words", "creatures",
                "direction", "turn", "color"]
        try:
            data = read_json(CONFIG_PATH)
            if not isinstance(data, dict) or not data.get("do"):
                raise ValueError("配置内容为空")
            for key in keys:
                value = data.get(key)
                setattr(NyosPrescript, key, value if isinstance(value, list) else list(DEFAULT_DATA[key]))
        except Exception as e:
            print(f"[今日指令] 读取 {CONFIG_PATH} 失败({e}), 使用内置默认词库")
            for key in keys:
                setattr(NyosPrescript, key, list(DEFAULT_DATA[key]))

    @staticmethod
    def spawn_prescript_steps():
        """
        生成今日指令, 并返回每一步的解析过程

        :return: (steps:list[str], final:str)
        """
        NyosPrescript.mems.clear()
        NyosPrescript.where_flag = False

        do: str = random.choice(NyosPrescript.do)
        steps = []

        depth = 0
        while '&' in do:
            depth += 1
            if depth > 30:
                do = NyosPrescript.resolve_tail(do)
                if not steps or steps[-1] != do:
                    steps.append(do)
                break
            do = NyosPrescript.check_text(do)
            if not steps or steps[-1] != do:
                steps.append(do)

        if not steps:
            steps.append(do)

        return steps, do

    @staticmethod
    def compute_birth(steps):
        """
        根据解析步骤, 计算最终文本每个字符在第几步被解析出来

        :param steps: 解析过程中的文本列表 (steps[-1] 为最终文本)
        :return: list[int], 与最终文本等长
        """
        if not steps:
            return []
        final = steps[-1]
        if len(steps) == 1:
            return [0] * len(final)

        birth = {}
        pos_map = list(range(len(final)))
        cur = final
        for i in range(len(steps) - 2, -1, -1):
            prev = steps[i]
            sm = difflib.SequenceMatcher(None, prev, cur, autojunk=False)
            new_pos_map = []
            for tag, _i1, _i2, j1, j2 in sm.get_opcodes():
                if tag == "equal":
                    new_pos_map.extend(pos_map[j1:j2])
                else:
                    for p in pos_map[j1:j2]:
                        birth[p] = i + 1
            pos_map = new_pos_map
            cur = prev

        return [birth.get(i, 0) for i in range(len(final))]

    @staticmethod
    def spawn_prescript():
        """
        今日指令的预脚本
        生成今日指令的预脚本

        :return: 指令 str
        """
        steps, final = NyosPrescript.spawn_prescript_steps()
        return final

    @staticmethod
    def check_text(text: str):
        """
        _检查文本是否符合指令的格式_
        
        Args:
            text (str): _需要检查的文本_
        """
        key_words = ["&time&", "&pepople&", "&where&", "&do&", "&drink&", "&food&", "&count&", "&action&", "&object&", "&song&", "&word&", "&creature&", "&direction&", "&turn&", "&color&"]
        for word in key_words:
            if word not in text:
                continue
            else:
                if word == "&time&":
                    text = NyosPrescript.replace_text(text, word, random.choice(NyosPrescript.when))
                elif word == "&pepople&":
                    text = NyosPrescript.replace_text(text, word, random.choice(NyosPrescript.people))
                elif word == "&where&":
                    text = NyosPrescript.replace_text(text, word, random.choice(NyosPrescript.where))
                elif word == "&do&":
                    do_text = random.choice(NyosPrescript.do)
                    if NyosPrescript.where_flag and "&where&" in do_text:
                        continue
                    text = NyosPrescript.replace_text(text, word, do_text)
                elif word == "&drink&":
                    text = NyosPrescript.replace_text(text, word, random.choice(NyosPrescript.drinks))
                elif word == "&food&":
                    text = NyosPrescript.replace_text(text, word, random.choice(NyosPrescript.foods))
                elif word == "&count&":
                    text = NyosPrescript.replace_text(text, word, str(random.randint(1, 100)))
                elif word == "&action&":
                    text = NyosPrescript.replace_text(text, word, random.choice(NyosPrescript.actions))
                elif word == "&object&":
                    text = NyosPrescript.replace_text(text, word, random.choice(NyosPrescript.objects))
                elif word == "&song&":
                    text = NyosPrescript.replace_text(text, word, random.choice(NyosPrescript.songs))
                elif word == "&word&":
                    text = NyosPrescript.replace_text(text, word, random.choice(NyosPrescript.words))
                elif word == "&creature&":
                    text = NyosPrescript.replace_text(text, word, random.choice(NyosPrescript.creatures))
                elif word == "&direction&":
                    text = NyosPrescript.replace_text(text, word, random.choice(NyosPrescript.direction))
                elif word == "&turn&":
                    text = NyosPrescript.replace_text(text, word, random.choice(NyosPrescript.turn))
                elif word == "&color&":
                    text = NyosPrescript.replace_text(text, word, random.choice(NyosPrescript.color))
        return text

    @staticmethod
    def replace_text(text: str, old: str, new: str):

        # for m in NyosPrescript.mems:
        #     if new in m:
        #         return text

        if new in NyosPrescript.mems:
            return text

        if NyosPrescript.where_flag and old == "&where&":
            return text

        NyosPrescript.mems.append(new)
        if old == "&where&":
            NyosPrescript.where_flag = True

        return text.replace(old, new)

    @staticmethod
    def resolve_tail(text: str):
        """
        递归过深时的兜底, 把残留的占位符一次性替换为最终值, 防止死循环
        """
        finals = {
            "&time&": "现在",
            "&do&": "做一件平常的小事",
            "&action&": "深吸一口气",
            "&drink&": "一杯水",
            "&food&": "一样吃的",
            "&count&": "3",
            "&pepople&": "你眼前的人",
            "&where&": "原地",
            "&object&": "一样东西",
            "&song&": "一首歌",
            "&word&": "一句话",
            "&creature&": "一只小动物",
            "&direction&": "左",
            "&turn&": "顺时针",
            "&color&": "红",
        }
        for key, value in finals.items():
            text = text.replace(key, value)
        return text


class NyosPrescriptApi:
    """
    pywebview js_api
    供前端调用的指令生成接口
    """

    def generate(self):
        """
        生成今日指令, 返回解析步骤、最终文本与每字符的解析时序

        :return: {"steps": [...], "final": "...", "birth": [0,1,...]}
        """
        NyosPrescript.reload_data()
        steps, final = NyosPrescript.spawn_prescript_steps()
        birth = NyosPrescript.compute_birth(steps)
        return {"steps": steps, "final": final, "birth": birth}

    @staticmethod
    def assets():
        """
        返回背景装饰图与解析音效的 base64 data URI

        :return: {"bg": "data:image/png;base64,...", "sfx": "data:audio/mp3;base64,..."}
        """
        import base64

        def data_uri(rel_path, mime):
            try:
                with open(os.path.join(_PROJECT_ROOT, rel_path), "rb") as f:
                    return f"data:{mime};base64," + base64.b64encode(f.read()).decode("ascii")
            except Exception as e:
                print(f"[今日指令] 读取 {rel_path} 失败: {e}")
                return None

        return {
            "bg": data_uri(os.path.join("assets", "images", "icon", "index.png"), "image/png"),
            "sfx": data_uri(os.path.join("assets", "voices", "beep.mp3"), "audio/mp3"),
            "sfx2": data_uri(os.path.join("assets", "voices", "beepstart.mp3"), "audio/mp3"),
        }


def _msgbox(title, text, is_error=True):
    """
    原生消息框 (ctypes MessageBoxW), 不依赖 tkinter:
    打包子进程里 tkinter messagebox 可能触发 0x80010108 崩溃
    """
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10 if is_error else 0x40)
    except Exception:
        pass


def run_prescript_window(debug: bool = False):
    """
    在当前进程内启动今日指令 pywebview 窗口

    源码模式: pythonw 子进程运行本脚本时调用; 打包模式: 主程序以
    --nyos-window 参数重新拉起自身 exe 后, main() 再调用本函数,
    不依赖外部 pythonw/解释器。
    """
    try:
        import webview
    except BaseException as e:
        import traceback
        try:
            with open(os.path.join(_PROJECT_ROOT, "nyos_window_error.log"), "a", encoding="utf-8") as f:
                f.write("import webview failed:\n" + traceback.format_exc())
        except Exception:
            pass
        _msgbox("今日指令", f"未安装 pywebview 依赖:\n{type(e).__name__}: {e}")
        raise SystemExit(1)

    html_path = os.path.join(_PROJECT_ROOT, "html", "nyos_prescript", "index.html")
    if not os.path.exists(html_path):
        _msgbox("今日指令", f"找不到页面文件:\n{html_path}")
        raise SystemExit(1)

    try:
        webview.create_window(
            "今日指令",
            html_path,
            js_api=NyosPrescriptApi(),
            width=640,
            height=540,
            min_size=(480, 400),
            background_color="#060f22",
        )
        webview.start(debug=debug)
    except BaseException as e:
        import traceback
        try:
            log_path = os.path.join(_PROJECT_ROOT, "nyos_window_error.log")
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(traceback.format_exc())
        except Exception:
            pass
        _msgbox("今日指令", f"无法启动窗口:\n{type(e).__name__}: {e}")
        raise SystemExit(1)


def open_prescript_window(debug: bool = False):
    """
    打开今日指令窗口

    说明: pywebview 6 要求 webview.start() 运行在主线程, 与 tkinter 主循环互斥,
    故以独立子进程方式拉起窗口, 与启动器完全解耦:
    - 源码模式: 用 pythonw 运行 nyos_prescript.py 子进程
    - 打包模式 (sys.frozen): 用自身 exe 以 --nyos-window 参数二次启动原生子进程

    Args:
        debug (bool): 是否开启 pywebview 调试
    """
    if getattr(sys, "frozen", False):
        cmd = [os.path.abspath(sys.executable), "--nyos-window"]
    else:
        script = os.path.join(_PROJECT_ROOT, "functions", "pages", "tools", "nyos_prescript.py")
        if not os.path.exists(script):
            _msgbox("今日指令", f"找不到脚本:\n{script}")
            return
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = sys.executable
        cmd = [pythonw, script]

    if debug:
        cmd.append("--debug")

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.Popen(cmd, cwd=_PROJECT_ROOT, creationflags=flags)
    except Exception as e:
        _msgbox("今日指令", f"无法启动窗口进程:\n{e}")


NyosPrescript.reload_data()

if __name__ == "__main__":
    # 源码模式启动方式: 本脚本被 pythonw 子进程运行
    run_prescript_window(debug="--debug" in sys.argv)