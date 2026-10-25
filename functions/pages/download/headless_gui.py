"""无头下载界面。

给没有 Tk 主循环的运行环境（web 后端、`--launcher-mode` 后台流程）用的
`DownloadGUI` 替身：对外接口（`is_downloading`、`current_file_var` 等）与
`functions.pages.download.download_gui.DownloadGUI` 一致，但不创建任何窗口。

真实 Tk 版本在无主循环的环境里会弹出一个永远无响应的窗口，因为 Tk 的主循环
根本没在跑 —— 这就是 Steam 拉起启动器后卡住的原因。
"""

import threading


class _VarHook:

    def __init__(self, on_change=None, initial=""):
        self._value = initial
        self._on_change = on_change

    def set(self, value):
        self._value = str(value)
        if self._on_change:
            try:
                self._on_change(self._value)
            except Exception:
                pass

    def get(self):
        return self._value

    def trace(self, *args):
        pass


class _RootShim:

    def __init__(self, owner):
        self._owner = owner
        self._closed = False

    def after(self, ms, cb):
        def _run():
            if not self._closed:
                try:
                    cb()
                except Exception:
                    pass
        threading.Timer(ms / 1000.0, _run).start()

    def deiconify(self):
        pass

    def withdraw(self):
        pass

    def destroy(self):
        self._closed = True
        self._owner.is_downloading = False

    def update_idletasks(self):
        pass


class HeadlessDownloadGUI:

    def __init__(self, config_path: str = "", auto_start: bool = True,
                 download_func=None, task: str = None): # type: ignore
        """_初始化一个无头下载器_

        Args:
            config_path (str, optional): _配置的下载路径_. Defaults to "".
            auto_start (bool, optional): _是否自动开始下载_. Defaults to True.
            download_func (_type_, optional): _下载回调方法_. Defaults to None.
            task (str, optional): _任务名称_. Defaults to None.
        """
        self.config_path = config_path
        self.is_downloading = True
        self.task = task
        self._push_progress = None
        self._on_done = None
        self.current_file_var = _VarHook(self._on_status, "初始化下载组件...")
        self.progress_var = _VarHook(initial="0")
        self.progress_text_var = _VarHook(initial="0%")
        self.speed_var = _VarHook(initial="0 KB/s")
        self.status_var = _VarHook(initial="准备开始下载...")
        self.root = _RootShim(self)

        if auto_start:
            self.start_download(download_func)

    def _on_status(self, text):
        import functions.web_update.zeroasso_download as zd
        try:
            getattr(zd, "_web_progress", lambda e, d: None)("status", {
                "task": self.task, "text": text,
            })
        except Exception:
            pass

    def update_progress(self, percent, downloaded, total, speed):
        import functions.web_update.zeroasso_download as zd
        try:
            getattr(zd, "_web_progress", lambda e, d: None)("progress", {
                "task": self.task,
                "percent": round(float(percent), 1),
                "downloaded": downloaded, "total": total, "speed": speed,
            })
        except Exception:
            pass
        self.progress_var.set(percent)
        self.speed_var.set(f"速度: {speed:.1f} KB/s" if speed < 1024 else f"速度: {speed / 1024:.1f} MB/s")

    def start_download(self, download_func=None):
        """_开始下载_

        Args:
            download_func (_type_, optional): _下载回调方法_. Defaults to None.
        """
        self.is_downloading = True
        threading.Thread(target=self.run_download, args=(download_func,),
                         daemon=True).start()

    def run_download(self, download_func=None):
        try:
            success = download_func(self, self.config_path)  # type: ignore
            if success:
                self.root.after(500, self.root.destroy)
            else:
                self.current_file_var.set("下载失败, 请检查错误信息")
                self.root.after(1000, self.root.destroy)
        except Exception as e:
            self.current_file_var.set(f"下载过程中出现错误: {e}")
        finally:
            self.is_downloading = False
            self.root.after(500, self.root.destroy)
            if self._on_done:
                try:
                    self._on_done()
                except Exception:
                    pass
