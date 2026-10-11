<div align="center">

# <img src="previews/readme/icon.png" width="52" height="52" style="vertical-align: middle;"> **FaustLauncher** 浮士德启动器

### *您人生中绝无仅有的完美启动器 —— 让每一个但丁都解放双手，专心坐牢*

<br>

[![版本](https://img.shields.io/badge/V0.9.1--release.fix.1-blue?style=for-the-badge&logo=git)](https://github.com/f0lkskill/FaustLauncher/releases)
[![许可证](https://img.shields.io/badge/许可证-MIT-green?style=for-the-badge&logo=opensourceinitiative)](LICENSE)
[![状态](https://img.shields.io/badge/状态-开发中-orange?style=for-the-badge&logo=githubactions)](https://github.com/f0lkskill/FaustLauncher)
[![平台](https://img.shields.io/badge/平台-Windows%2010%20%2F%2011-lightgrey?style=for-the-badge&logo=windows)](https://github.com/f0lkskill/FaustLauncher)
[![Stars](https://img.shields.io/github/stars/f0lkskill/FaustLauncher?style=for-the-badge&logo=github)](https://github.com/f0lkskill/FaustLauncher/stargazers)
[![Downloads](https://img.shields.io/github/downloads/f0lkskill/FaustLauncher/total?style=for-the-badge&logo=github)](https://github.com/f0lkskill/FaustLauncher/releases)

</div>

---

## 📖 这个项目做什么

**FaustLauncher** 是《边狱巴士 (Limbus Company)》玩家的一体化启动器：汉化更新、游戏美化、Mod / 插件管理、自定义翻译、版本自动更新，**点一次「启动游戏」全部自动完成**。

它不是一个「把官网链接摆一排」的导航页，而是真正动手处理游戏文件的一层——下载汉化包、按需改写 `Lang` 文本、经符号链接搬运资源、加载 Mod、最后把游戏拉起来。

| 能力 | 一句话说明 |
|:---|:---|
| 🚀 **一键启动流水线** | 一次点击跑完 8 步：汉化检测下载 → 文件同步 → 补丁应用 → 美化 → 字体 → 配置 → 用户名写入 → 启动游戏 |
| 🌐 **汉化自动更新** | 内置 4 种下载源（蓝奏云转存 / gh-proxy / upfile / GitHub Releases），自动比对版本、更新汉化与气泡文本 |
| 🎨 **界面全方位美化** | 气泡渐变 · 技能名罪孽渐变 · 技能描述 · EGO 名称（含侵蚀）· 零协会私活 Tip · 自定义字体，逐项可开关 |
| 🧩 **Mod + 插件双生态** | 自带改装版 Mod 加载器；用户可自写插件（启动事件钩子 + `changes.json` 汉化补丁），见 [MakeAnAddon.md](tools/doc/MakeAnAddon.md) |
| 📝 **自定义翻译器** | 可视化改写游戏任意文本，生成可移植的补丁；与美化功能互不冲突 |
| 🏆 **成就系统** | 观测游戏内战斗事件并弹出成就提示，偏移索引随游戏版本自动适配 |
| 🖼️ **皮肤系统** | 启动器界面可换肤（CSS 变量覆盖 + 资源替换），带解锁条件 |
| 👤 **用户系统** | 用户 ID 即账号，皮肤解锁状态跨设备同步；本地数据不随程序卸载丢失 |
| 🔄 **自动更新** | 支持预发布版；更新器原子替换运行时目录，失败可回滚 |
| 🛠️ **工具集** | 文件夹超链接（释放 C 盘）· 字体替换 · 渐变文本处理器 · CDN 优选 · Mod 管理器 · 今日指令 |

<br>

## 🚀 快速开始

| 步骤 | 操作 |
|:---:|:---|
| **1** | 到 [Releases](https://github.com/f0lkskill/FaustLauncher/releases) 下载最新版并解压（不要放进需要管理员权限的目录） |
| **2** | 双击 `FaustLauncher.exe` |
| **3** | 在「设置」页确认**游戏安装路径**（必须是指向 `LimbusCompany.exe` 所在目录） |
| **4** | 回主页点 **「启动游戏」**，等它自动完成汉化更新并拉起游戏 |
| **5** | （可选）在「设置」里调美化、音效、主题；在「玻璃窗」换皮肤 |

> 使用视频教程：程序内「关于 → 程序介绍」页面。

<br>

## 🖼️ 界面预览

| 主界面 | 插件与 Mod 管理 | 下载中心 |
|:---:|:---:|:---:|
| ![主界面](previews/preview_1.png) | ![插件和模组管理](previews/preview_2.png) | ![社区下载中心](previews/preview_3.png) |

| 关于界面 | 个性化设置 | 工具组 |
|:---:|:---:|:---:|
| ![关于界面](previews/preview_4.png) | ![多种个性化设置](previews/preview_5.png) | ![丰富的工具组](previews/preview_6.png) |

---

## 🔄 流程实现

### 1. 启动初始化

界面框架与后端数据解耦：splash 先出、业务数据后到，任何一步失败都只降级，不会白屏。

### 2. 一键启动流水线（后端 8 步）

| 步骤 | 内容 |
|:---:|:---|
| 1 | 汉化下载更新（多源 + 版本比对） |
| 2 | 复制汉化文件到游戏目录 |
| 3 | 应用**已启用**的 Mod / 插件 / 自定义翻译补丁；被禁用的自动还原它改过的文本 |
| 4 | 应用美化（气泡 / 技能 / EGO / Tip） |
| 5 | 部署字体 |
| 6 | 生成零协会配置 |
| 7 | 写入用户名（`UserInfo_Friends.json`） |
| 8 | 触发插件启动事件 + 加载 Mod + 拉起游戏 |

> 非关键步骤失败不阻塞启动；关键步骤（汉化复制 / 字体）失败会明确弹窗。

### 3. 云端数据

云端清单（汉化版本、插件与 Mod 列表、资源包等）由启动器统一拉取，多线路自动回退，并在本地留一份缓存；
网络不可用时用缓存继续工作，不会卡在启动流程里。对国内线路做了加固（多源回退、超时重试、解析兜底、缓存降级），
每一级都有 `[云端]` 日志。排障用 `python tools/diag/webnote_diag.py`。

> 具体的服务端地址、接口与实现细节不在公开文档里 —— 见仓库维护者内部说明。

### 4. 账号与数据同步

- 用户数据存在服务端账号下，客户端**只读写自己那份数据**，账号之间不会互相影响；
- 同步口径是**并集（只增不减）**：本地新解锁的内容不会被云端旧记录覆盖；
- 登录态保存在 `%APPDATA%\FaustLauncher\` 下，日志对身份与凭据全程脱敏。

### 5. 版本自动更新

检查更新 → 下载更新包 → 由更新脚本替换运行时目录。替换采用「先落地新目录、再切换」的方式，
任何一步失败都不会破坏当前安装、可以回滚；顶层数据目录（`config` / `lang` / `mods` / `addons`）
只做合并覆盖，绝不清空。

### 6. 皮肤加载

皮肤 = **CSS 变量覆盖层** + 资源目录替换 + `config.json` 元信息（含解锁条件）：

```
web/app_skins/<id>/ css/style.css    → 作为 <style> 追加在默认样式之后（只写差异）
                    profile.jpg      → 玻璃窗卡片图
                    assets/launcher/ → 可选替换背景图 / 快捷方式卡 / 工具卡
                    assets/web/      → 可选替换 web/app/assets
```

解锁条件写在 `config.json` 的 `unlock` 字段：`free`（免费）/ `edge_window_title`（检测窗口标题）等；未解锁的皮肤在玻璃窗里显示「待解锁」，点击进入二级模态验证。

---

## 🧰 技术栈

| 层 | 技术 |
|:---|:---|
| **界面** | **pywebview 6.2（WebView2）** + 原生 HTML / CSS / JavaScript，**无前端框架**；模块按 `core → ui → features → app` 分层 |
| **后端** | Python 3.14（标准库 + `requests` / `Pillow`） |
| **进程间** | pywebview `js_api` 双向桥：前端 `window.pywebview.api.*`，后端 `evaluate_js` 推送日志与事件 |
| **窗口模型** | 主窗口占用 pywebview 主线程；Mod 管理器 / 自定义汉化 / 扩展工具 / 今日指令等独立窗口通过 `main.py --xxx-window` 拉起**子进程**（pywebview 要求 `start()` 在主线程，与主循环互斥） |
| **打包** | PyInstaller（onedir）+ `tools/build/FaustLauncher.spec`；运行时收在 `_internal/` |
| **更新** | Windows Script Host（`updater.vbs`） |
| **游戏资源** | UnityPy · texture2ddecoder · astc-encoder · etcpak · fmod_toolkit · pyfmodex |
| **逆向 / Hook** | capstone · pefile · pythonnet（偏移索引、元数据恢复、战斗事件观测） |
| **服务端** | 独立部署（另行维护，不随本项目分发）；客户端只通过公开接口读写自己的数据 |
| **目标平台** | Windows 10 / 11 |

---

## 🏗️ 项目架构

```
FaustLauncher/
├─ main.py                    # 入口（默认 Web UI；各独立窗口以 --xxx-window 子进程拉起）
├─ tools/                     # 开发与排障工具（构建 / 资源包 / 诊断 / 快捷方式，见 tools/README.md）
│  ├─ build/                  #   构建：build.py + FaustLauncher.spec + assets_pack.py（资源包）
│  ├─ build_temp/             #   打包输入（updater.vbs）
│  ├─ dev/ diag/ run/         #   小脚本、排障脚本、.bat 快捷方式
│  └─ doc/ preview/ wiki_fetch/
├─ web/                       # 前端（不被 Python 直接引用）
│  ├─ app/                    #   主界面：index.html + css + js(core/ui/features)
│  └─ app_skins/              #   皮肤（faust / deepseek …；图片在资源包里，css/config 在仓库）
├─ functions/                 # 后端
│  ├─ base/                   #   基础设施：设置、网络配置、用户系统、JSON 读写、路径
│  ├─ pages/app/app_web.py    #   pywebview 主窗口桥接（AppApi：前端能调的全部接口）
│  ├─ pages/…                 #   各独立窗口（Mod 管理器 / 自定义汉化 / 扩展工具 …）
│  ├─ web_update/ webFunc/    #   云端资源、下载源、笔记与 GitHub 客户端
│  ├─ fancy/                  #   游戏美化（气泡 / 技能 / EGO / Tip）
│  ├─ modloader/              #   Mod 加载（bank 音频、贴图重打包）
│  ├─ hook/ achievement/      #   内存 Hook、偏移索引、成就系统
│  ├─ translate/ tools/       #   AI 翻译、扩展工具
│  └─ update/                 #   版本更新流程
├─ assets/                    # 素材（图片/语音）——**不在仓库里**，见下面「素材与资源包」
├─ config/                    # settings.json（用户设置）/ web_config.json（云端地址）
├─ resources/                 # 运行期资源（Mod 加载器等，启动器自己下载，不入库）
└─ previews/                  # README 截图
```

**数据放哪**：用户数据在 `%APPDATA%\FaustLauncher\`（卸载重装不丢），程序运行时可读写的缓存与更新包在安装目录的 `cache/`。

---

## 🎨 素材与资源包（clone 后必做）

图标、音效、背景、皮肤图片合计约 15 MB，**不在 git 里**。仓库只放代码，素材走一个独立的
**资源包**（`tools/build/assets_pack.py`）；发布包仍然由构建工具把素材一起打进去，最终用户无感。

```bat
tools\run\assets.bat fetch      :: 下载资源包并合并（推荐，clone 之后跑一次）
tools\run\assets.bat status     :: 看本地和资源包差在哪（缺失 / 被改过 / 多出来的）
tools\run\assets.bat pack       :: 生成 faust-assets.zip（改了素材之后）
tools\run\assets.bat upload     :: 用 gh 传成 Release 资产（需要 gh auth login）
```

包格式就是**把仓库根当解压目标**：里面是 `assets/images/...`、`web/app_skins/<皮肤>/assets/...`
这类和仓库完全一致的相对路径，所以"解压覆盖"即完成合并，代码里的相对路径（`assets/images/icon/icon.ico`）原样可用。
固定分发地址（tag 不变，永远这一个）：

```
https://github.com/f0lkskill/FaustLauncher/releases/download/assets/faust-assets.zip
```

手动分发也行：把 zip 发给别人，`assets.bat fetch` 支持 `--from <zip>` 离线合并。包内自带
`.assets-pack/manifest.json`（逐文件 sha256），拉取前会先整体校验，坏包不会把工作区改成半截状态。

> **注意**：素材只是"不再进新提交"，**旧的 git 历史里还在** —— 已 clone 的仓库不会因此变小。
> 想让仓库体积真正降下来需要重写历史（`git filter-repo` / BFG）+ force push，属于一次性破坏性操作，要单独安排。

---

## 🙋 用户系统与隐私

- **账号就是用户 ID**，没有密码；首次运行由启动器生成并向服务端登记；
- 本地只保存必要数据：本机用户 ID、已解锁皮肤、操作冷却时间戳；
- 日志默认**脱敏**：用户 ID 打码显示，凭据信息只打印「有 / 无」，绝不落盘到日志；
- 服务端只允许读到公开资料，写入一律只作用于**自己那份数据**，不接受替别人写入。

---

## 🛠️ 二次开发

| 需求 | 入口 |
|:---|:---|
| 写插件 | [MakeAnAddon.md](tools/doc/MakeAnAddon.md)（启动事件钩子、`changes.json` 补丁、资源打包） |
| 写皮肤 | 复制 `web/app_skins/faust/`，改 `css/style.css` 与 `config.json`；皮肤图片属于资源包（见上一节） |
| 源码运行 | `python main.py`（默认 Web UI；`--tk-ui` 回旧界面，`--debug` 开调试）｜需要 `pip install -r requirements.txt` **并先拉素材**：`tools\run\assets.bat fetch` |
| 打包 | `python tools/build/build.py`（可视化构建工具；等价于 `python -m PyInstaller tools/build/FaustLauncher.spec`）｜**需要素材已就位**，缺了会直接报错 |
| 资源包 | `tools\run\assets.bat [pack\|status\|fetch\|upload]`（素材的打包 / 校验 / 拉取 / 发布，见上一节） |
| 云端排障 | `python tools/diag/webnote_diag.py`（逐项打印 DNS / TCP / TLS / HTTP 与缓存状态） |

> 维护约定：前端改动后请同步提升 `web/app/index.html` 里资源引用的 `?v=NN` 缓存版本号；所有 JS 文件共享同一全局作用域，新增模块请追加到入口之前。

---

## 🤝 贡献者

| 头像 | 姓名 | 角色 | 贡献 |
|:---:|:---|:---|:---|
| <img src="previews/readme/contributors/folkskill.png" width="40" height="40"> | **FolkSkill** | 项目创始人 & 主开发者 | 整体架构设计与全部核心功能（2025-11-25 立项） |
| <img src="previews/readme/contributors/HZB.png" width="40" height="40"> | **HZBHZB1234** | 项目程序贡献者 | 开发早期的部分代码贡献与流程指导，LCTA 作者 |
| <img src="previews/readme/contributors/chen.png" width="40" height="40"> | **尘** | 项目程序贡献者 | LC Mod Loader 手机版作者，贡献 rebank 加载机制 |
| <img src="previews/readme/contributors/bob.png" width="40" height="40"> | **Bob** | 项目程序贡献者 | 修复自定义汉化的递归问题 |
| <img src="previews/readme/contributors/Ariko.png" width="40" height="40"> | **里诺Ariko** | 民间有色战斗气泡文本作者 | 持续为启动器提供有色战斗气泡文本 |
| <img src="previews/readme/contributors/zeroasso.jpg" width="40" height="40"> | **零协会** | 汉化支持 | 都市零协会汉化组官方本地化项目 |
| <img src="previews/readme/contributors/community.png" width="40" height="40"> | **社区贡献者** | 测试 & 反馈 | 使徒 · HZB · 尘 · 海螺 · 庭渡久歌 · 终末之影 · 四季交融 · 快乐咸鱼君 · 盘 等 |

**反馈渠道**：[Bug 反馈](https://github.com/f0lkskill/FaustLauncher/issues/new?template=bug_report.md) · [功能建议](https://github.com/f0lkskill/FaustLauncher/issues/new?template=feature_request.md) · [讨论区](https://github.com/f0lkskill/FaustLauncher/discussions)

---

<div align="center">

[![Star History Chart](https://api.star-history.com/svg?repos=f0lkskill/FaustLauncher&type=Date)](https://star-history.com/#f0lkskill/FaustLauncher&Date)

</div>

---

## 📜 免责声明（必读）

> 使用本软件即视为您已阅读并同意以下全部内容：

1. **软件性质**：开源免费，仅限学习、研究与个人交流，禁止商业用途。
2. **版权归属**：《边狱巴士 (Limbus Company)》及其素材版权归 **Project Moon** 及相关权利方；汉化文本版权归**零协会汉化组**等原权利人。本项目不含盗版内容，请确保您已购买正版游戏。
3. **修改风险**：本软件会自动写入与修改游戏本地化文件；因版本更新、文件结构变更等导致游戏无法启动、存档异常或其它损失，**作者与贡献者不承担任何责任**。
4. **风险自担**：使用 Mod、汉化、第三方脚本产生的账号风险（含封禁、处罚）由使用者自行承担。
5. **第三方内容**：通过「下载中心」等获取的资源版权归原作者，请自行确认授权与合法性。
6. **版权申诉**：如认为本项目引用了您的受版权保护内容，请通过 [Issues](https://github.com/f0lkskill/FaustLauncher/issues) 联系，我们会尽快处理。

---

## 📄 许可证

本项目基于 **[MIT 许可证](LICENSE)** 分发。

部分代码引用自 [LCTA (Limbus Company Transfer Auto)](https://github.com/HZBHZB1234/LCTA-Limbus-company-transfer-auto)，同样遵循 [MIT 许可证](https://github.com/HZBHZB1234/LCTA-Limbus-company-transfer-auto/blob/main/LICENSE)。

<br>

<div align="center">

*Built with ❤️ for Limbus Company players.*
**© 2025-2026 FaustLauncher Contributors**

</div>
