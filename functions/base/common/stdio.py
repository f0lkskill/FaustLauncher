"""标准输出加固 —— 让"打印"永远不会因为编码把程序打崩

现场（真实用户）::

    Failed to execute script 'main' due to unhandled exception:
    'cp950' codec can't encode character '\\u5f20' in position 17: illegal multibyte sequence
    File "functions\\pages\\app\\app_core.py", line 61, in load_background_images
    File "rich\\console.py", line 1704, in print

原因链:

1. 打包时 ``console=False``（windowed exe），**sys.stdout / sys.stderr 都是 None**；
2. rich 的 ``Console.file`` 在 ``file is None`` 时退回它自己的
   ``NULL_FILE = open(os.devnull, "w")`` —— 这个流用的是「系统首选编码」；
3. 用户机器区域设置是繁体中文（cp950/Big5），**放不下简体字**，
   于是打印 ``找到 3 张背景图片`` 里的「张」直接抛 UnicodeEncodeError；
4. 该异常未被捕获 → PyInstaller 弹出 "Unhandled exception in script"。

所以启动最早期调用 ``harden_stdio()``：

* 已有流 → ``reconfigure(errors="replace")``：**编码保持不变**（中文在 GBK/cp950 控制台仍正常显示），
  只有放不下的字符（简体/emoji）退化成 ``?``，绝不抛异常；
* 流为 None → 绑定到 UTF-8 + replace 的 ``os.devnull``，让 rich / print 都有落点
  （Web 界面启动后 stdout 会被 WebLogRedirector 接管，早期输出也就有去处了）。

只依赖标准库，可被任意入口（启动器 main.py、app_web.run_web）在最早期调用，重复调用无副作用。
"""

import io
import os
import sys

__all__ = ["harden_stdio"]

_hardened = False


def _harden_rich_null_file():
    """rich 已导入时，顺手把它那个 locale 编码的 NULL_FILE 也改成不炸的

    （正常情况下把 sys.stdout 补上就不会再走到 NULL_FILE，这里只是双保险）
    """
    try:
        module = sys.modules.get("rich.console")
        null_file = getattr(module, "NULL_FILE", None)
        if null_file is not None and hasattr(null_file, "reconfigure"):
            null_file.reconfigure(errors="replace")
    except Exception:
        pass


def harden_stdio(force=False):
    """加固 sys.stdout / sys.stderr；返回（加固后的）sys.stdout"""
    global _hardened
    if _hardened and not force:
        return sys.stdout
    _hardened = True

    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            # 无控制台的 windowed 打包：必须补一个真实流，否则第三方库会自己去 open(devnull, 'w')
            try:
                setattr(sys, name, open(os.devnull, "w", encoding="utf-8", errors="replace"))
            except Exception:
                pass
            continue
        try:
            stream.reconfigure(errors="replace")          # type: ignore[attr-defined]
            continue
        except Exception:
            pass
        # 不支持 reconfigure（自定义流等）：能包一层就包一层
        try:
            buffer = getattr(stream, "buffer")
            encoding = getattr(stream, "encoding", None) or "utf-8"
            setattr(sys, name, io.TextIOWrapper(buffer, encoding=encoding,
                                                errors="replace", line_buffering=True))
        except Exception:
            pass

    _harden_rich_null_file()
    return sys.stdout
