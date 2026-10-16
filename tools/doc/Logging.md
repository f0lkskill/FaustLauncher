# 日志系统

启动器的每一行输出都走同一套布局：时间戳、区域、级别、来源、正文。

```
[2026-10-11 11:21:28.291] [hook] [ERROR] [updater.py:314]: 偏移索引更新失败
```

## 各出口的分工

| 出口 | 模块 | 职责 |
| --- | --- | --- |
| 控制台（cmd） | `functions/base/console_log.py` | 包装 `sys.stdout` / `sys.stderr`，给每行补前缀 |
| 日志文件 | `functions/base/log_manager.py` | 运行日志 `logs/日期_时间.log` + 按级别归档 |
| 显式级别 API | `functions/base/logger.py` | `debug` / `info` / `warn` / `error` |
| 行渲染与级别定义 | `functions/base/log_format.py` | `build_line()`、`LEVELS`、配色、来源推断 |
| Web 终端 | `web/app/js/ui/terminal.js` | 读行里的 `[LEVEL]` 标记上色 |
| Tk 终端 | `functions/pages/terminal/terminal_redirect.py` | 同上，映射到控件颜色标签 |

**渲染只发生一次**：`log_format.build_line()` 产出整行后，控制台、日志文件、两个 UI
终端拿到的都是这一份文本。任何出口都不许自己补时间戳或二次判定级别——否则同一个
事件在四个地方会显示得不一样。

## 级别

`DEBUG < INFO < WARN < ERROR`（`log_format.LEVEL_ORDER`）。

新代码用显式 API，级别由记录方给出：

```python
from functions.base import logger

logger.debug("偏移索引命中缓存 %d 条", n)
logger.info("启动游戏流水线作业开始")
logger.warn("插件 %s 被禁用, 跳过载入", name)
logger.error("复制汉化文件失败: %s", exc)
```

- `print()` 依然可用，它会被记为 **INFO**。
- 没有显式级别的调用点（例如历史遗留的 `print`）会由 `log_format.LEVEL_RULES` 按正文
  关键词做一次兜底判定（`失败` → ERROR、`跳过` → WARN）。**这只是兼容层**，不要把真正
  的错误藏在普通句子里指望它被识别出来。
- 级别走带内信号：`logger` 在写入前把级别放进 `console_log` 的线程局部通道，正文本身
  不夹杂任何级别标记，因此日志里读到的正文永远是干净的。

## 来源（`[文件:行号]`）

来源由调用栈推断。只负责转发的模块必须登记在 `log_format.SKIP_FRAMES` 里，否则整行会
被算到转发器头上（历史上就是因此让所有回溯行都指向 `traceback.py`）。**新增转发层时要
同步补进去。**

## 日志文件

- 运行日志：`logs/YYYY-MM-DD_HH-MM-SS.log`，每次运行一个，保留全部级别。
- 按级别归档：`logs/DEBUG/`、`logs/WARN/`、`logs/ERROR/` 里是同名副本，只收录对应级别。
  排查时先看 `logs/ERROR/`，再回运行日志按时间顺序读上下文。
- 保留策略对两者统一生效：超过 3 天的删除，每个自然日最多留 7 个。

## 多行输出

一次写入里包含多行的，按"自带排版的整块"放行：不加前缀、原文进日志与 UI。启动横幅、
ASCII 图、异常回溯都靠自己的缩进排版，逐行加前缀会把图案拼不回去。含 `\r` 的写入
（进度条）原样转发。
