# tools/ — 开发与排障工具

根目录只留**入口和基本文件**（`main.py` ...），其余零散的小工具都收到这里，按用途分目录。

> `tools/` 整体被 `.gitignore` 当成"本地脚手架目录"忽略（`**/tools/` + `/tools/*`）。
> 下面这些**手写工具要入库**，所以在 `.gitignore` 末尾逐项放行了
> `tools/README.md` / `tools/dev/` / `tools/diag/` / `tools/run/` / `tools/doc/` /
> `tools/build/` / `tools/build_temp/updater.vbs`；

| 目录 | 放什么 |
|---|---|
| `build/` | 打包：可视化构建工具 + PyInstaller spec |
| `build_temp/` | 打包输入：`updater.vbs`（唯一入库的文件，其余是产物，包含在本项目独立发布的附属构建文件内，不入库） |
| `dev/` | 开发时跑的小脚本（统计、检查） |
| `diag/` | 线上排障用的一次性诊断脚本（网络/云端/缓存） |
| `run/` | 免记命令的启动快捷方式（`.bat`，双击即用） |
| `doc/` | 面向二次开发的文档 |
| `preview/` | 界面预览图与预览页（本地产物，不入库） |

## build/

| 文件 | 用法 | 说明 |
|---|---|---|
| `build.py` | `python tools/build/build.py` | 可视化构建工具（pywebview）：PyInstaller → 复制运行环境/资产/配置 → 压缩 zip → 可选发布。**素材没拉时第一步就报错**并提示去跑 `assets.bat fetch` |
| `FaustLauncher.spec` | `python -m PyInstaller tools/build/FaustLauncher.spec` | PyInstaller 配方。源路径全部锚定仓库根（`SPECPATH` 现在是 `tools/build/`，不能直接拿来拼 `web/`、`config/`），所以不依赖当前工作目录 |
| `assets_pack.py` | `python tools/build/assets_pack.py pack\|status\|fetch\|upload` | 素材资源包：制作 / 校验 / 拉取 / 发布。素材（`assets/images`、`assets/voices`、皮肤图片）不入库，靠它分发；包是"**解压到仓库根即合并**"的覆盖包，内含逐文件 sha256 清单 |

## build_temp/

| 文件 | 说明 |
|---|---|
| `updater.vbs` | 版本更新器：启动器下载新版本后以 `wscript` 运行它，由它把新版本文件覆盖到安装目录。**必须入库**（换机器/重新 clone 后 `build.py` 找不到就会直接报错），`.gitignore` 里为此专门放行了这一条 |

> 这个目录里其它的 `addons/ lang/ mods/ _internal/` 是历史构建产物（不入库、也没有任何代码引用），可以随时删。

> 打包产物固定落在**仓库根**的 `build/`（PyInstaller workpath + 内嵌 `web_config_data`）与 `dist/`；
> `.gitignore` 里因此把 `build/` 锚定成 `/build/`，只忽略根目录那份。

## dev/

| 工具 | 用法 | 说明 |
|---|---|---|
| `count_lines.py` | `python tools/dev/count_lines.py [目录]` | 统计 `.py`/`.js`/`.html` 行数并排行。**不带参数默认统计整个仓库**（按脚本位置推仓库根，不受当前工作目录影响） |

## diag/

| 工具 | 用法 | 说明 |
|---|---|---|
| `webnote_diag.py` | `python tools/diag/webnote_diag.py` | 云端访问自检：逐个源打印解析 / 连接 / 握手 / 响应状态与耗时 / 缓存命中情况。用户反馈"浏览器能开、启动器云端全失败"时用它定位卡在哪一环 |
| `enkephalin_probe.py` | `python tools/diag/enkephalin_probe.py` | 脑啡肽内存读取自检：找进程 / `OpenProcess` 权限 / `GameAssembly.dll` 基址与大小 / 逐级指针 / 最终值，逐步打印。**不依赖启动器**，游戏跑着就能单独测。`--watch` 连续读、`--raw` 只出数字、`--json` 机器可读；退出码 0 成功 / 1 游戏没开 / 2 权限被拒 / 3 找不到模块 / 4 指针链断 |

## run/

| 快捷方式 | 等价命令 | 说明 |
|---|---|---|
| `assets.bat` | `python tools/build/assets_pack.py <动作>` | 素材资源包：`pack`（生成 zip）/ `status`（本地 vs 包）/ `fetch`（下载合并）/ `upload`（gh 发布）。**不带参数＝pack**。clone 之后先跑 `assets.bat fetch` |
| `upload_assets.bat` | `pack` + `upload` 两步 | **素材改动后的一键发布**：先查关键素材在不在 → `pack`（覆盖 `faust-assets.zip`）→ `upload`（覆盖 Release `tag=assets` 的资产）。可选参数传版本号（默认今天日期）。任何一步失败就中止，不会拿旧 zip 去传。改完素材、想让别人 `fetch` 到新版就跑它 |
| `debug.bat` | `python main.py --debug` | 调试模式启动启动器（`--debug` 不重定向 stdout，控制台能直接看到输出） |
| `web_tool.bat` | `python main.py --extension-tools-window` | 只拉起"扩展工具"窗口 |
| `update_hook.bat` | `python -m functions.hook.main update` | 手动重建并上传偏移索引（约 1~2 分钟满核）请先挂起游戏之后再运行 |

这几个 `.bat` 都先 `cd /d "%~dp0..\.."` 回到仓库根再执行，所以**双击、从任意目录调用都能用**；
找不到 `venv\Scripts\python.exe` 时自动退回 PATH 里的 `python`。