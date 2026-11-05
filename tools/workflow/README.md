# YisangMirrorFlow

把 lunartime `.zip` 与 `.bank` 批量打包成 `.carra2` / `.rebank` 的独立工作流。

## 启动

```bat
tools\run\mod_workflow.bat
```

或：

```bat
venv\Scripts\python.exe tools\workflow\main.py
```

## 使用

1. 第一次打开时，在顶栏选择游戏目录；`.bank` 需要用它里面的原版 bank 做对照。
2. 点“新建包”，然后把 `.zip` / `.bank` 添加进包。
3. 点“开始打包”。每个包会单独开一个窗口，包与包之间可以并行。
4. 总览页轮询 `.workflow_job.json`，刷新状态。

## 目录

```
tools/workflow/
├─ main.py          入口（总览 / --worker 子进程）
├─ core.py          包管理、游戏路径、任务状态、启动 worker
├─ overview_api.py  总览页 API
├─ worker.py        单个包的打包子进程 + pywebview 窗口
├─ VERSION
└─ mods/            每个包一个文件夹（不入库）
```

## 打包规则

| 输入 | 输出 | 说明 |
|---|---|---|
| `.zip` | `.carra2` | lunartime 压缩 |
| `.bank` | `.rebank` | 需要游戏原版 bank；成功后删除源 `.bank` |
| `.carra2` / `.rebank` | 原样保留 | 已经是成品 |

只打包模式不会启动游戏、不会修改游戏目录、不会备份原版文件。

## 环境

- UI / worker：启动器 `venv\Scripts\python.exe`（pywebview）。
- 实际打包：`resources\mod_loader\_internal\venv\Bins\python.exe`（UnityPy / FMOD / FSBank）。

worker 会调用：

```text
mod_loader/_internal/main.py --package-only --work-dir <包目录> --threads <N>
```

工作目录同时也是 `log.txt`、`loader_progress.txt`、`loader_threads.txt` 的位置。
