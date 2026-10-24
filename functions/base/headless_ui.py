"""完全静默模式：把会创建窗口的 UI 入口换成不建窗的替身。

`--launcher-mode` 是被 Steam 按启动项拉起来的后台进程，这个进程里没有 Tk 主循环。
只要有代码走到 `tk.Tk()` / `tk.Toplevel()`，就会留下一个永远不响应的窗口——Tk 的
事件循环根本没在跑，窗口不会重绘也不会响应点击。这就是「从 Steam 点启动，先弹
一个空窗口，然后卡死」的成因。

这里只做替换，不改业务流程：
- 下载进度窗口换成 `HeadlessDownloadGUI`，回调、`is_downloading`、`root.destroy()`
  这些接口都还在，流程能照常跑完；
- 对话框改成直接返回默认值并打一行日志，不阻塞、不弹窗；
- mod 加载进度窗口**不归这里管**：它是独立进程（`--mod-loader-progress --pid N`），
  自己跑自己的 mainloop，所以照常显示。
"""

__all__ = ["install", "is_installed", "reset"]

_installed = False


def is_installed() -> bool:
    """当前进程是否已经切到静默模式。"""
    return _installed


def reset() -> None:
    """把标记复位（只给自检用，运行期不需要）。"""
    global _installed
    _installed = False


def _patch_download_gui() -> None:
    """把下载窗口替换成无头版本。

    `page_loader.download_and_launch()` 里有两种用法，都要覆盖：
    - `main_gui(parent, config_path)`：汉化包下载；
    - `DownloadGUI(parent, config_path, auto_start, download_func)`：资源更新。
    第一个位置参数都是 parent（Tk 容器），无头版则把它当成 config_path，所以要
    用两个独立适配层，不能直接把类指过去。
    """
    import functions.web_update.zeroasso_download as zd
    from functions.pages.download.headless_gui import HeadlessDownloadGUI

    def _main_gui(parent=None, config_path="", **_kwargs):
        return HeadlessDownloadGUI(config_path, download_func=zd.download_and_extract_gui)

    def _download_gui(parent=None, config_path="", auto_start=True,
                      download_func=None, task=None, **_kwargs):
        return HeadlessDownloadGUI(config_path, auto_start=auto_start,
                                   download_func=download_func, task=task)

    zd.main_gui = _main_gui  # type: ignore[assignment]
    zd.DownloadGUI = _download_gui  # type: ignore[assignment]

    try:
        import functions.update.version_utils as vu
        vu.DownloadGUI = _download_gui  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        print(f"[Headless] 同步 version_utils 失败(忽略): {exc}")


def _patch_dialogs() -> None:
    """对话框静默化：不建窗，直接返回「用户没点」的默认值。"""
    try:
        import tkinter.messagebox as mb
        import tkinter.simpledialog as sd
    except Exception as exc:  # noqa: BLE001
        print(f"[Headless] 无法导入对话框模块(忽略): {exc}")
        return

    # 返回值语义按 tkinter 的默认按钮来：确认类一律「否」，这样不会有人不在场
    # 却自动点了「是」；askyesnocancel 的 None 表示「取消」。
    defaults = {
        "showinfo": None,
        "showwarning": None,
        "showerror": None,
        "askyesno": False,
        "askokcancel": False,
        "askretrycancel": False,
        "askquestion": "no",
        "askyesnocancel": None,
    }

    def _make_handler(kind, default):
        def _handler(*args, **kwargs):
            title = args[0] if len(args) > 0 else kwargs.get("title", "")
            message = args[1] if len(args) > 1 else kwargs.get("message", "")
            print(f"[Headless] 对话框已静默({kind}): {title} | {message}")
            return default
        return _handler

    for kind, default in defaults.items():
        setattr(mb, kind, _make_handler(kind, default))

    for name in ("askstring", "askinteger", "askfloat"):
        setattr(sd, name, lambda *a, **k: None)

    # 文件选择框也是模态窗口，后台进程里同样会卡住，这里直接返回「没选」。
    try:
        import tkinter.filedialog as fd
        fd.askopenfilename = lambda *a, **k: ""
        fd.askopenfilenames = lambda *a, **k: ()
        fd.askdirectory = lambda *a, **k: ""
        fd.asksaveasfilename = lambda *a, **k: ""
    except Exception as exc:  # noqa: BLE001
        print(f"[Headless] 无法导入文件对话框(忽略): {exc}")


def _audit_tk() -> None:
    """兜底审计：还有别处建 Tk 顶层窗口时，至少在日志里留下证据。

    不拦截（拦截会让本来能跑的流程直接抛异常），但它会明确告诉我们是哪条路
    径漏了——下次就能针对性替换掉。
    """
    try:
        import tkinter
    except Exception:  # noqa: BLE001
        return

    original_tk_init = tkinter.Tk.__init__

    def _patched_tk_init(self, *args, **kwargs):
        print("[Headless] 警告: 仍有代码调用 tk.Tk()，该窗口不会响应（请补充静默替身）")
        return original_tk_init(self, *args, **kwargs)

    tkinter.Tk.__init__ = _patched_tk_init  # type: ignore[method-assign]


def install() -> bool:
    """切到静默模式。幂等。"""
    global _installed
    if _installed:
        return True

    _patch_download_gui()
    _patch_dialogs()
    _audit_tk()

    _installed = True
    print("[Headless] 已切换到完全静默模式（本进程不创建任何窗口）")
    return True
