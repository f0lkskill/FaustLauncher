# tools/ — 开发与排障工具

根目录只留**入口与构建**（`main.py` / `build.py` / `FaustLauncher.spec` / `build.json` /
`requirements.txt` / 文档），其余零散的小工具都收到这里，按用途分目录。

> `tools/` 整体被 `.gitignore` 当成"本地脚手架目录"忽略（`**/tools/` + `/tools/*`）。
> 下面这些**手写工具要入库**，所以在 `.gitignore` 末尾逐项放行了
> `tools/README.md` / `tools/dev/` / `tools/diag/` / `tools/run/`；
> `tools/wiki_fetch/`（自带 `.venv` 与下载产物）和 `tools/preview/` 仍然不入库。

| 目录 | 放什么 |
|---|---|
| `dev/` | 开发时跑的小脚本（统计、检查） |
| `diag/` | 线上排障用的一次性诊断脚本（网络/云端/缓存） |
| `run/` | 免记命令的启动快捷方式（`.bat`，双击即用） |
| `preview/` | 界面预览图与预览页（本地产物，不入库） |
| `wiki_fetch/` | wiki 图标抓取子项目（自带独立 `.venv`，不入库） |

## dev/

| 工具 | 用法 | 说明 |
|---|---|---|
| `count_lines.py` | `python tools/dev/count_lines.py [目录]` | 统计 `.py`/`.js`/`.html` 行数并排行。**不带参数默认统计整个仓库**（按脚本位置推仓库根，不受当前工作目录影响） |

## diag/

| 工具 | 用法 | 说明 |
|---|---|---|
| `webnote_diag.py` | `python tools/diag/webnote_diag.py` | 云端笔记（webnote）访问自检：逐个源打印 DNS / 建连 / TLS / HTTP 状态 / 耗时 / DoH 直连 / 本地缓存。用户反馈"浏览器能开、启动器云端全失败"时让他跑这个 |

## run/

| 快捷方式 | 等价命令 | 说明 |
|---|---|---|
| `debug.bat` | `python main.py --debug` | 调试模式启动启动器（`--debug` 不重定向 stdout，控制台能直接看到输出） |
| `web_tool.bat` | `python main.py --extension-tools-window` | 只拉起"扩展工具"窗口 |
| `update_hook.bat` | `python -m functions.hook.main update` | 手动重建并上传偏移索引（约 1~2 分钟满核） |

三个 `.bat` 都先 `cd /d "%~dp0..\.."` 回到仓库根再执行，所以**双击、从任意目录调用都能用**；
找不到 `venv\Scripts\python.exe` 时自动退回 PATH 里的 `python`。
