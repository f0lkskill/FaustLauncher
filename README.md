<div align="center">

# <img src="assets/images/icon/icon.png" width="52" height="52" style="vertical-align: middle;"> **FaustLauncher** 浮士德启动器

### *您人生中绝无仅有的完美启动器 —— 让每一个但丁都解放双手，专心坐牢*

<br>

[![版本](https://img.shields.io/badge/版本-V0.6.0--pre.7.fix.2-blue?style=for-the-badge&logo=git)](https://github.com/f0lkskill/FaustLauncher/releases)
[![许可证](https://img.shields.io/badge/许可证-MIT-green?style=for-the-badge&logo=opensourceinitiative)](LICENSE)
[![状态](https://img.shields.io/badge/状态-开发中-orange?style=for-the-badge&logo=githubactions)](https://github.com/f0lkskill/FaustLauncher)
[![平台](https://img.shields.io/badge/平台-Windows%2010%20%2F%2011-lightgrey?style=for-the-badge&logo=windows)](https://github.com/f0lkskill/FaustLauncher)
[![Stars](https://img.shields.io/github/stars/f0lkskill/FaustLauncher?style=for-the-badge&logo=github)](https://github.com/f0lkskill/FaustLauncher/stargazers)
[![Downloads](https://img.shields.io/github/downloads/f0lkskill/FaustLauncher/total?style=for-the-badge&logo=github)](https://github.com/f0lkskill/FaustLauncher/releases)

<br>

**📺 使用视频教程：可在程序「关于 → 程序介绍」页面中查看。**

</div>

---

## 📖 项目简介

> **FaustLauncher（浮士德启动器）**是一款专为 **《边狱巴士 (Limbus Company)》** 玩家打造的全功能一体化启动器。
> 集 **汉化自动下载更新、Mod 管理与加载、界面美化、自定义汉化、AI 自动翻译、插件扩展、下载中心** 等实用功能于一体。
> 一切只需一键操作，无需多余配置，全部内置 —— 这就是浮士德大人的聪明才智口牙！

- 🗓️ 项目始于 2025-11-25，持续开发迭代中
- 🎯 核心理念：**让每一个但丁都解放自己的双手，专心坐牢。**

<br>

## 📊 项目信息

| 项目 | 信息 |
|:---|:---|
| 🏷️ 当前版本 | `V0.6.0-pre.7.fix.2` |
| 📅 最后更新 | 2026-08-09 |
| 🛠️ 开发状态 | 开发中... |
| 🎯 目标平台 | Windows 10 / 11 |
| 🛠️ 技术栈 | Python · Tkinter · PyInstaller |
| 📜 开源协议 | MIT |
| 💬 交流反馈 | [Issues](https://github.com/f0lkskill/FaustLauncher/issues) · [Discussions](https://github.com/f0lkskill/FaustLauncher/discussions) |

<br>

## ✨ 亮点总览

| | 亮点 | 说明 |
|:---:|:---|:---|
| 🚀 | **懒人到位的 一键配置启动** | 点击「启动游戏」，自动完成汉化更新、补丁应用、美化、字体、用户名写入、Mod 载入等全部流程 |
| 🌐 | **零协会汉化自动更新** | 内置 4 种下载源，自动获取零协会最新汉化，无需手动下载 |
| 🎨 | **游戏界面全方面美化** | 与零协会本土化相互兼容，支持气泡渐变、技能描述美化、EGO 样式、私活 Tip、字体替换 |
| 🧩 | **Mod 与插件管理系统** | 自带改装版 Mod 加载器，支持用户自编写插件扩展启动器 |
| 📝 | **自定义汉化与 AI 翻译** | 可视化编辑游戏文本、生成 `changes.json` 补丁，配合思知 AI 补充翻译 |
| 🎛️ | **个性化设置中心** | 用户热门、背景模糊、主题颜色、欢迎音效、托盘行为自由定制 |

> ⚠️ **Mod 相关说明**：由于游戏引擎更新，**大部分旧 Mod 已失效**，Mod 功能正在适配新引擎中，预计将在后续版本修复。建议暂时关闭「启用 Mod 功能」。

---

## 🖼️ 界面预览

> 截图取自最新版本 (V0.6.0-pre.7)。

| 主界面 — 快速启动与迷你终端 | 功能页 — 常用链接 | 工具页 — 工具集 |
|:---:|:---:|:---:|
| ![主界面](previews/preview_1.png) | ![功能页](previews/preview_2.png) | ![工具页](previews/preview_3.png) |

| Mod 与插件管理 | 下载中心 |
|:---:|:---:|
| ![Mod 与插件管理](previews/preview_4.png) | ![下载中心](previews/preview_5.png) |

<br>

---

## ✨ 核心功能

### 🚀 一键启动游戏（流水线式）

点击主界面「🚀 启动游戏」，自动按顺序执行以下全部步骤，**无需任何手动操作**：

| 步骤 | 内容 |
|:---|:---|
| 1️⃣ 汉化下载更新 | 自动检测并下载零协会最新汉化包 + 气泡文本 Mod（多下载源） |
| 2️⃣ 复制汉化文件 | 将 `lang/LLC_zh-CN` 同步到游戏目录 |
| 3️⃣ 应用拓展汉化修改 | 一键应用所有已启用 Mod / 插件 / 自定义翻译的补丁（`changes.json`） |
| 4️⃣ 应用美化功能 | 气泡渐变、技能描述、EGO 样式、私活 Tip、技能渐变色 |
| 5️⃣ 复制字体文件 | 内置字体自动部署 |
| 6️⃣ 创建零协会配置 | 自动生成汉化所需配置文件 |
| 7️⃣ 设置用户名称 | 将您设置的用户名写入游戏车票（UserInfo_Friends.json） |
| 8️⃣ 启触发插件事件 + 载入游戏 | 加载 Mod 并正式启动游戏 |

> 非关键步骤失败不会阻塞启动；关键步骤失败会弹出明确错误提示。

### 🌐 汉化系统

- **零协会汉化自动更新**：内置 `4 种下载源` 可选
  - ☁️ 蓝奏云转存下载源（推荐）
  - ⚡ gh-proxy 代理加速下载
  - 🔄 upfile 动态更新下载源
  - 🐙 GitHub Releases 官方下载源（可能被墙，不推荐）
- **气泡文本 Mod 自动更新下载**
- 支持**手动更新汉化**（「🎯 汉化更新」按钮）

### 🎨 游戏美化功能x

| 功能 | 说明 |
|:---|:---|
| 🫧 气泡文本渐变色 | 为对话气泡文本添加渐变色彩，可调渐变系数 |
| 💠 技能名称渐变色 | 按技能罪孽颜色自动添加渐变 |
| 📝 技能描述美化 | 数字特殊样式、`>` `<` 规范化等 |
| ✨ EGO 样式美化 | 正常 EGO 与侵蚀 EGO 名称特殊样式 |
| 🗣️ 零协会私活 Tip | 替换战斗文本 Tip |
| 🧾 用户名字幕 | 个人名片显示自定义用户名 |
| 🔤 自定义字体 | 用您喜欢的字体替换汉化包字体（工具页 → 字体修改） |

### 🧩 Mod 与插件系统

- 📥 **Mod 管理**：添加 / 删除 / 启用 / 禁用 Mod，支持外置 Mod 加载器
- 🔌 **插件系统（v0.6.0+）**：用户可自编写插件扩展启动器功能
  - 📘 **[→ 插件制作指南 (MakeAnAddon.md)](MakeAnAddon.md)**
  - 支持 `插件激活事件`、`游戏启动事件` 等生命周期钩
  - 支持 `changes.json` 汉化补丁、背景图片、插件图标等
- ⚠️ 当前因游戏引擎更新 Mod 兼容性受限，修复中见开发动态

### 📝 自定义翻译器（changes.json 补丁）

- 可视化修改游戏内任意文本，自动记录并生成 `lang/changes.json` 补丁
- 支持 Mod/插件的 `changes.json` 打包分发，天然与官方汉化教程共存
- **不会与美化渐变功能冲突**
- 兼容 Windows 旧式反斜杠路径键自动归一化，位置独立可移植

### 🤖 AI 辅助汉化（自动翻译）

- 使用**思知 AI** 对游戏剧情等文本进行**批量自动翻译**（自动汉化工具）
- 在设置页配置 AI 密钥与翻译提示词，提示词支持 `{text}` 占位替换

### 🛠️ 工具集（工具页）

| 工具 | 说明 |
|:---|:---|
| 🔧 自定义汉化 | 可视化编辑 `lang` 目录下任意 JSON 文本 |
| 📦 文件夹超链接 | 为资源文件夹创建符号链接，**转移占位，释放 C 盘空间** |
| 💻 渐变文本处理器 | 根据输入文本生成 Unity 富文本渐变色代码 |
| 📝 字体修改 | 选择自己喜欢的字体替换汉化包字体 |
| 🔄 自动汉化 | 思知 AI 批量剧情文本翻译补充 |
| 📖 今日指令 | 获取食指的最新指令（独立窗口自动解析） |
| 🚀 零协会 CDN 优选 | 自动选择最优 CDN，优化资源下载与连接速度 |
| 📦 Mod 管理器 | 管理边狱巴士的 Mod 文件 |

### 📥 下载中心

- 在线浏览并下载 **Mod / 插件**（按下载次数排序）
- 自动缓存插件与 Mod 图标，展示完整的在线图片

### ⚙️ 个性化设置

| 分类 | 设置项 |
|:---|:---|
| 通用 | 游戏路径、翻译下载方式、退出后操作（最小化到系统托盘 / 关闭）、终端打字机效果（实验性） |
| 美化 | 用户名、显示用户名、私活 Tip、技能描述美化、EGO 样式、气泡渐变（渐变系数）、技能名称渐变（渐变系数） |
| Mod | 启用 Mod 功能、隐藏 Mod 加载窗口、外置 Mod 加载器路径 |
| 翻译 | AI 密钥、AI 翻译提示词 |
| 其它 | 欢迎音效（支持自定义 wav 路径）、背景模糊强度、主题颜色（实验性） |

### 🔔 其它贴心细节

- 🖥️ **内置迷你终端**：实时日志输出、一键复制 / 清空，错误一目了然
- 📌 **退出后可最小化到系统托盘** 后台常驻
- 🔄 **自动更新机制**（支持预发布版本自动更新 + 版本详情窗口）
- 🎵 **专属欢迎音效**（可自定义 wav 文件，路径留空即关闭）

<br>

---

## 🌐 常用入口（功能页）

| 入口 | 用途 |
|:---|:---|
| 📁 游戏目录 | 打开边狱巴士安装目录 |
| 🔄 零协会 | 前往零协会汉化组主页 |
| 📒 气泡文本 | 下载气泡 Mod 汉化版（提取码：fib6） |
| 📝 维基 | 边狱巴士灰机 Wiki |
| 📖 N 网 (Nexus) | 下载边狱巴士 Mod |
| 📦 GitHub | 查看本项目源码 |

---

## 🤝 贡献者

| 头像 | 姓名 | 角色 | 简介 |
|:---:|:---|:---|:---|
| ![FolkSkill](assets/images/contributor/folkskill.png) | **FolkSkill** | 项目创始人 & 主开发者 | 项目于 2025-11-25 开始开发，负责整体架构与全部核心功能 |
| ![HZB](assets/images/contributor/HZB.png) | **HZBHZB1234** | 程序贡献者 | 早期代码贡献与流程指导，LCTA 作者 |
| ![Ariko](assets/images/contributor/Ariko.png) | **里诺Ariko** | 民间气泡汉化作者 | 持续提供有色战斗气泡文本汉化 |
| ![零协会](assets/images/contributor/zeroasso.jpg) | **零协会** | 汉化支持 | 都市零协会汉化组官方本地化项目 |
| ![社区](assets/images/contributor/community.png) | **社区贡献者** | 测试 & 反馈 | 使徒、HZB、尘、海螺、庭渡久歌、终末之影、四季交融、快乐咸鱼君、盘 等 |

---

## 💬 反馈与贡献

我们欢迎一切建议与帮助！

- 🐛 [反馈 Bug](https://github.com/f0lkskill/FaustLauncher/issues/new?template=bug_report.md)
- 💡 [功能建议](https://github.com/f0lkskill/FaustLauncher/issues/new?template=feature_request.md)
- ❓ [提问与交流](https://github.com/f0lkskill/FaustLauncher/discussions)

---

## 📜 免责声明（必读）

> 使用本软件前请仔细阅读以下条款，**使用本软件即视为您已阅读并同意全部内容**：

1. **软件性质**：FaustLauncher 为开源免费软件，仅限用于学习、研究与个人交流目的，禁止任何形式的商业用途。
2. **版权归属**：《边狱巴士 (Limbus Company)》游戏本体及其所有素材的版权归 **Project Moon** 及相关权利方所有。汉化文本版权归**零协会汉化组**等原权利人所有。本项目不包含任何盗版内容，请确保您已自行购买正版游戏。
3. **修改风险**：本软件会对游戏本地化文件进行自动写入与修改。若因游戏版本更新、文件结构变更等原因导致游戏无法启动、存档异常或其他任何损失，作者与贡献者不对使用者承担任何责任。
4. **风险自担**：任何使用 Mod、汉化、用户脚本等第三方内容所致的账号风险（包括但不限于封禁、处罚），均由使用者自行承担，作者不承担连带责任。
5. **第三方内容**：通过「下载中心」等功能获取的 Mod、插件等资源版权归其原作者所有，与本项目无关；请在使用前确认其授权与合法性。
6. **配置安全**：请在官方设置中核对游戏路径正确性。因错误配置（如错误的路径、错误的 AI 密钥等）产生的任何问题，本软件不承担由此造成的一切后果。
7. **未经授权引用**：若您认为本软件引用了您的受版权保护内容，请通过 [Issues](https://github.com/f0lkskill/FaustLauncher/issues) 与我们联系，我们将尽快处理。
8. **版本变更**：本项目仍处于开发阶段，功能与界面可能随时变更、移除或失效，请以各 Release 内的说明为准。

<br>

---

## 📄 许可证

本项目基于 **[MIT 许可证](LICENSE)** 分发。

**部分代码引用自：**
[LCTA (Limbus Company Transfer Auto)](https://github.com/HZBHZB1234/LCTA-Limbus-company-transfer-auto) —— 同样遵循 [MIT 许可证](https://github.com/HZBHZB1234/LCTA-Limbus-company-transfer-auto/blob/main/LICENSE)。

<br>

---

<div align="center">

*Built with ❤️ for Limbus Company players.*  
**© 2025-2026 FaustLauncher Contributors**

</div>