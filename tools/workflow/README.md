# YisangMirrorFlow

合并前端（两页）：打包工作流把 lunartime `.zip` 与 `.bank` 批量打包成 `.carra2` / `.rebank`；扩展工具负责包装 Mod / 生成插件模板 / 发布 Mod·插件。两页共用顶部常驻标题栏。

## 启动

```bat
tools\run\yisang_workflow.bat
```

或：

```bat
venv\Scripts\python.exe tools\workflow\main.py
```

## 使用

1. 第一次打开时，在顶栏选择游戏目录；`.bank` 需要用它里面的原版 bank 做对照。
   填错层级没关系：直接粘贴 `…\Sound\FMODBuilds\Desktop` 音效目录（或游戏 exe 路径）也能识别。
2. 点“新建包”，然后把 `.zip` / `.bank` 添加进包。
3. 需要查看/处理 zip 内容时，点“解包”；会把包内全部 `.zip` 的第一个顶层目录内容解压到包根目录，重复文件直接覆盖。
4. 点“开始打包”。每个包会单独开一个窗口，包与包之间可以并行。
5. 总览页轮询 `.workflow_job.json`，刷新状态。

## 目录

```
tools/workflow/
├─ main.py          入口（合并前端 / --worker 子进程）
├─ core.py          包管理、游戏路径、任务状态、启动 worker
├─ overview_api.py  合并前端 API（包管理 + 扩展工具）
├─ extension_api.py 扩展工具后端（包装 Mod / 插件模板 / 发布）
├─ worker.py        单个包的打包子进程 + pywebview 窗口
├─ VERSION
└─ mods/            每个包一个文件夹（不入库）
```

> 前端页面在 `web/mod_workflow/`；扩展工具的包装/发布逻辑复用
> `functions/tools/post_extension_tools.py`。启动器不再提供扩展工具入口，也不需要开发者密钥。

## 打包规则

| 输入 | 输出 | 说明 |
|---|---|---|
| `.zip` | `.carra2` | lunartime 压缩 |
| `.bank` | `.rebank` | 需要游戏原版 bank；成功后删除源 `.bank` |
| `.carra2` / `.rebank` | 原样保留 | 已经是成品 |

只打包模式不会启动游戏、不会修改游戏目录、不会备份原版文件。

## 导入与解包（自动）

- 没有单独的“解包”按钮；通过“添加文件”导入 `.zip` / `.7z` / `.rar` 即自动解包并删除原归档。
- 7z/rar 通过系统 7-Zip 解压（找不到会提示安装或设置 `SEVENZIP_PATH`）。
- 按“打包流需求”提取：
  - 含 `Installer.bat` 的完整包目录 → **单独压成一个 zip**（保留顶层目录，如 `播报员头像替换.zip`），打包流只认 zip。
  - 音效 `.bank` / `.rebank` / `.carra2` → 复制到包根（完整包 zip 内的除外）。
  - json / txt / ReadMe 等其它文件一律忽略，不再散落到包根。
- 同名覆盖。

## 信息与发布（融合在打包页）

单页无分区，所有操作都在包卡片上完成：

- **新建包**可选类型：Mod 包（需打包）/ 插件包（自带 `scr.py`、免打包）；创建即写入初始 `mod_info.json` / `addon_info.json`。
- **信息**就地写 `mod_info.json` / `addon_info.json` 与 `icon.png`（先手动包装再发布）；作者用“+ 添加作者”模态填写名字与链接。
- 交互：图标选择后即时预览（后端读成 data URI，避免破图）；删除等操作使用应用内确认模态；列表/信息面板加载时显示转圈动画。
- **发布**：Mod 包需打包完成且无失败；插件包免打包。发布前检查名称 / 版本 / 描述 / 至少一位作者 / 图标 /（Mod 包）至少一个载入文件，不写 tag 标签。
- **版本号**：与上次发布相同则自动 patch+1（记录在包内 `.workflow_publish.json`）。
- **上传日志**：模态窗口，可最小化到右下角浮标，再点开查看详情。
- 发布技术流程：读取 info → 必填校验 → 版本自增 → 只把“真正有用”的文件提取到临时目录 → 压缩成临时 zip → 用该 zip 上传蓝奏云 → 更新云端信息 → 清理临时文件。
  - Mod 白名单：`carra2` / `rebank` / `bank` / `json` / `mod_info.json` / `icon.png` / `Installer.bat` / `Uninstaller.bat` / `changes.json` 及 `Assets/` 资源；源 `.zip`、日志/进度、`.workflow_*` 一律不带。
  - 插件：除源 `.zip` 外的文件全部带上（含 `scr.py`、资源）。
- 单文件 Mod 支持 `.bank` / `.carra2` / `.rebank`；可额外导入不限量 `.json`（仅放根目录，不做处理）。
- 默认目录统一在 `tools/workflow/mods/`；包装/发布复用 `functions/tools/post_extension_tools.py`。

## 环境

- UI / worker：启动器 `venv\Scripts\python.exe`（pywebview）。
- 实际打包：`resources\mod_loader\_internal\venv\Bins\python.exe`（UnityPy / FMOD / FSBank）。

worker 会调用：

```text
mod_loader/_internal/main.py --package-only --work-dir <包目录> --threads <N>
```

工作目录同时也是 `log.txt`、`loader_progress.txt`、`loader_threads.txt` 的位置。
