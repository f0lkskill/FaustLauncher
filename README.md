<div align="center">

# <img src="assets/images/icon/icon.png" width="52" height="52" style="vertical-align: middle;"> **FaustLauncher** 浮士德启动器

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
| 🧩 **Mod + 插件双生态** | 自带改装版 Mod 加载器；用户可自写插件（启动事件钩子 + `changes.json` 汉化补丁），见 [MakeAnAddon.md](MakeAnAddon.md) |
| 📝 **自定义翻译器** | 可视化改写游戏任意文本，生成可移植的补丁；与美化功能互不冲突 |
| 🤖 **AI 批量翻译** | 接入思知 AI 批量翻译剧情文本，提示词可自定义 |
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

### 1. 启动初始化（前端 8 阶段）

界面框架与后端数据解耦：splash 先出，业务数据后到，任何一步失败都只降级不白屏。

```
① 环境准备(探测 pywebview 桥) → ② 首屏数据(主页卡片) → ③ UI 绑定 → ④ 通知后端 UI 就绪
→ ⑤ 预取(背景/音效/时钟) → ⑥ 拉取 bootstrap → ⑦ 渲染与尺寸锁定 → ⑧ splash 淡出
```

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

### 3. 云端数据链（读 / 写分离）

| 用途 | 地址 | 说明 |
|:---|:---|:---|
| 读 | `webnote_bases`（`/note/{key}`） | 模板列表，按顺序回退 |
| 写 | `webnote_update_url`（`/update/`） | 下载计数 / 排序上传，POST 提交 |

读取侧对国内线路做了加固：**IPv4 优先 → 超时重试 → DoH 兜底解析 → 直连 IP → 本地缓存降级**，每一级都打 `[云端]` 日志，不再出现「浏览器正常、启动器整段失败且无原因」。排障用 `python tools/diag/webnote_diag.py`。

### 4. 用户数据同步（服务端 API）

用户数据**不再整表读写笔记**（那是"最后写入者胜"，会成批丢用户），改为走服务端自助接口：

```
首次/每次同步  POST /api/register   (幂等: 已存在则一个字段都不改)
读自己         GET  /api/me
上报皮肤       POST /api/me/skins    (整体替换自己那一行)
上报昵称       POST /api/me/name
切换账号       POST /api/login
```

- 服务端在锁内「读整表 → 只改自己这一行 → 原子写回」，结构上不可能牵连别人；
- 皮肤的合并策略是**并集（只增不减）**，避免把本地新解锁的覆盖掉；切换账号则以服务端记录为准；
- 登录态是 30 天签名 Cookie，落在 `%APPDATA%\FaustLauncher\user\session.json`；
- 所有网络访问都有 `[用户API]` / `[用户]` 两级脱敏日志（用户 ID 打码、凭据只报有无）。

### 5. 版本自动更新

```
检查更新 → 下载更新包到 cache/new_version/ → wscript 运行 updater.vbs
         → ① 新内容复制成 _internal.new  ② 旧目录改名 _internal.old  ③ 新目录就位 → 删 .old
```

替换运行时目录采用「三步改名」，任何一步失败都不会破坏当前安装；顶层数据目录（`config` / `lang` / `mods` / `addons`）只做合并覆盖，绝不清空。

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
| **界面** | **pywebview 6.2（WebView2）** + 原生 HTML / CSS / JavaScript，**无前端框架**；模块按 `core → ui → features → app` 分层，共 25 个文件 |
| **后端** | Python 3.14（标准库 + `requests` / `Pillow`） |
| **进程间** | pywebview `js_api` 双向桥：前端 `window.pywebview.api.*`，后端 `evaluate_js` 推送日志与事件 |
| **窗口模型** | 主窗口占用 pywebview 主线程；Mod 管理器 / 自定义汉化 / 扩展工具 / 今日指令等独立窗口通过 `main.py --xxx-window` 拉起**子进程**（pywebview 要求 `start()` 在主线程，与主循环互斥） |
| **打包** | PyInstaller 6.16（onedir）+ `FaustLauncher.spec`；运行时收在 `_internal/` |
| **更新** | Windows Script Host（`updater.vbs`） |
| **游戏资源** | UnityPy · texture2ddecoder · astc-encoder · etcpak · fmod_toolkit · pyfmodex |
| **逆向 / Hook** | capstone · pefile · pythonnet（偏移索引、元数据恢复、战斗事件观测） |
| **服务端** | 独立仓库 FaustLauncherWeb（Bottle + PythonAnywhere），提供 `/api/*` 与笔记存储 |
| **目标平台** | Windows 10 / 11 |

---

## 🏗️ 项目架构

```
FaustLauncher/
├─ main.py                    # 入口（默认 Web UI；各独立窗口以 --xxx-window 子进程拉起）
├─ build.py / *.spec          # PyInstaller 构建
├─ web/                       # 前端（不被 Python 直接引用）
│  ├─ app/                    #   主界面：index.html + css + js(core/ui/features)
│  └─ app_skins/              #   皮肤（faust / deepseek …）
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
├─ assets/                    # 图片、字体、语音
├─ config/                    # settings.json（用户设置）/ web_config.json（云端地址）
├─ resources/                 # 内嵌资源（Mod 加载器等）
└─ previews/                  # README 截图
```

**数据放哪**：用户数据在 `%APPDATA%\FaustLauncher\`（卸载重装不丢），程序运行时可读写的缓存与更新包在安装目录的 `cache/`。

---

## 🙋 用户系统与隐私

- **账号就是用户 ID**，没有密码；ID 形如 `FL-` + 16 位字符，首次运行由启动器生成并向服务端登记；
- 本地用户文件（`%APPDATA%\FaustLauncher\user\settings.json`）保存三项：本机用户 ID、已解锁皮肤、服务端返回的**完整资料快照**（原样镜像，便于字段级对照）；操作冷却的时间戳另存一个文件；
- 日志默认**脱敏**：用户 ID 打码显示，Cookie / 签名 / 令牌只打印「有 / 无」，绝不落盘到日志；
- 按 ID 查资料的公开接口是**只读**的；所有写接口都只作用于**自己那一行**（uid 由服务端从登录会话取，不接受请求体传入）。

---

## 🛠️ 二次开发

| 需求 | 入口 |
|:---|:---|
| 写插件 | [MakeAnAddon.md](MakeAnAddon.md)（启动事件钩子、`changes.json` 补丁、资源打包） |
| 写皮肤 | 复制 `web/app_skins/faust/`，改 `css/style.css` 与 `config.json` |
| 源码运行 | `python main.py`（默认 Web UI；`--tk-ui` 回旧界面，`--debug` 开调试）｜需要 `pip install -r requirements.txt` |
| 打包 | `python build.py` |
| 云端排障 | `python tools/diag/webnote_diag.py`（逐项打印 DNS / TCP / TLS / HTTP 与缓存状态） |

> 维护约定：前端改动后请同步提升 `web/app/index.html` 里资源引用的 `?v=NN` 缓存版本号；所有 JS 文件共享同一全局作用域，新增模块请追加到入口之前。

---

## 🤝 贡献者

| 头像 | 姓名 | 角色 | 贡献 |
|:---:|:---|:---|:---|
| <img src="assets/images/contributor/folkskill.png" width="40" height="40"> | **FolkSkill** | 项目创始人 & 主开发者 | 整体架构设计与全部核心功能（2025-11-25 立项） |
| <img src="assets/images/contributor/HZB.png" width="40" height="40"> | **HZBHZB1234** | 项目程序贡献者 | 开发早期的部分代码贡献与流程指导，LCTA 作者 |
| <img src="assets/images/contributor/chen.png" width="40" height="40"> | **尘** | 项目程序贡献者 | LC Mod Loader 手机版作者，贡献 rebank 加载机制 |
| <img src="assets/images/contributor/bob.png" width="40" height="40"> | **Bob** | 项目程序贡献者 | 修复自定义汉化的递归问题 |
| <img src="assets/images/contributor/Ariko.png" width="40" height="40"> | **里诺Ariko** | 民间有色战斗气泡文本作者 | 持续为启动器提供有色战斗气泡文本 |
| <img src="assets/images/contributor/zeroasso.jpg" width="40" height="40"> | **零协会** | 汉化支持 | 都市零协会汉化组官方本地化项目 |
| <img src="assets/images/contributor/community.png" width="40" height="40"> | **社区贡献者** | 测试 & 反馈 | 使徒 · HZB · 尘 · 海螺 · 庭渡久歌 · 终末之影 · 四季交融 · 快乐咸鱼君 · 盘 等 |

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
