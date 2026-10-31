# WarpHook 会话总结：立绘修复 + 生态自检 + 规范化准备

> 生成时间：2026-10-31 · 承接 v0.9.6（成就全通）之后的收尾轮

---

## 一、本轮修复：毒舌插件立绘淡出失效

**症状**：成就全部正常了，但 battle_snark 立绘不再淡出淡入；"之前的版本一直正常"。

**根因**：v0.9.6 把共享内存协议从 version=4 升到 version=5（尾部追加 buff 关注哈希表段），而 `addons/BattleSnark/battle_snark.c:968` 的 tick 注册校验写死了 `hdr[1] != 4` —— 注册被静默拒绝 → `sk_ui_tick` 失去每帧驱动（warp 泵代跑的 objects[30]/[31] 通道没挂上）→ 立绘永不淡出。

**修复**：校验放宽为下限 `hdr[1] < 4`（v4 起才有 tick 共享槽协议），注释记录本次教训。`battle_snark.dll` 重编 45056B 零警告。**注意：addons/* 被 .gitignore:173 忽略，此修复无版本管理、只在本地生效。**

---

## 二、生态自检报告

### A 类：协议与接口（规范化重点）

| # | 问题 | 证据 | 规范化方向 |
|---|------|------|-----------|
| A1 | **协议常量三处拷贝** | battle_snark.c 手写 `WH_MAP_NAME`/`WH_OBJ_OFFSET=172416`/objects[30][31]/`WH_TICK_MAGIC`；权威定义在 warp_layout.h（C）与 host.py（PY），双轨靠尺寸自检兜底 | 共享内存 header 自描述（暴露 objects 段偏移），或 WarpHook 导出 C 小头文件；这是本次立绘 bug 的结构性根源 |
| A2 | **Host 获取三种姿势并存** | 成就侧 `warp_source.py:403 namespaces['warp'].plugin.Host`（'warp' 字符串硬编码）；NoGacha `addons/nogacha/scr.py:24` 经 warp_stub 的 Service；battle_snark 是 C 直接摸共享内存 | 统一为一个入口（warp_stub 补运行时 helper，或 AddonManager 挂 get_warphook()） |
| A3 | **版本协商缺失** | battle_snark 校验 version（本次已修为下限兼容）；上游升版本不通知消费者 | 把布局演进纪律"**只追加不挪动**"（v5 buff 段尾部追加即范例）写进 DESIGN.md 成为硬纪律；消费者一律按下限校验 |

### B 类：工程卫生

- **B1** `cache/` 808MB（其中 sess_extract 59MB 是旧 session 解压垃圾）——可清理
- **B2** `test/` 整目录被 .gitignore:19 忽略——64 用例回归基线只在本地，换机即失
- **B3** `addons/*` 被 .gitignore:173 忽略——battle_snark.c（1795 行）/NoGacha 无版本管理
- **B4** NoGacha 的 warp_stub import 未加 TYPE_CHECKING 保护（运行时无害，小事）

### C 类：已良好（点名保持）

- C/PY 布局双轨 + host.py 尺寸自检断言
- diag.py 三层诊断日志（CFG/EVT/ST/DROP，本轮及前几轮排障的功臣）
- 多作者分段协议（成就子进程与 NoGacha 主进程互不覆盖）
- warp_stub.py 类型桩（44 个 Protocol 定义，IDE 补全方案）

---

## 三、成就系统终态（第八轮真机验证通过）

用户反馈："**成就全部内容被证实，可以正常运行，并且获得成就**"。

- 六种规则数据源全部打通：ACT（skill）/SPD（speed）/VAL（mental/hp）/BUF（buff，v0.9.6）/PRESENCE（采样器）/RWT（铁路）
- 剩余 wip：railway6_100t（RWT 真值已验，可关 wip）、story_10_4（STG 明细未迁，SNI 覆盖基本语义，已知暂缓）
- 其他插件（毒舌/NoGacha/提取）全部正常运行

---

## 四、版本链（git 已由用户同步远端）

| 标签 | 提交 | 内容 |
|------|------|------|
| warphook/v0.8.0 | 0c3cf2f | P5 收官：读返回值/容器值类型/12 格事件，老链路下线 |
| warphook/v0.9.0 | ddcf22 | P6 对象构造：make/call/str-arr/GC 持有 |
| warphook/v0.9.1 | 47ec62b | 钩子表 16→32 槽（协议 v4）+ 同目标双钩防御 |
| warphook/v0.9.2 | 053487b | 多作者分段 + tick 泵代跑（两插件进程互踩根修） |
| warphook/v0.9.3 | c1b35a6 | thunk 表 32 槽补全 + argc 正名 + 命名空间 strrchr |
| warphook/v0.9.4 | 83d99db | 钩点迁移 BattleSystemAbilityDetail + obscured 读链 |
| warphook/v0.9.5 | f435918 | thunk 返回值一律 64 位接 RAX+无条件写回（采光本锁根修） |
| warphook/v0.9.6 | 29b650a | buff 关注哈希表 + BUF 行转发（协议 v5，MAP 172928B） |

当前协议：WARP_VERSION=5 / HOST_VERSION=5，MAP 172928B，钩子 32 槽（主段 27/辅段 5），事件 12 格，读链 128 条。

---

## 五、下一步：规范化统一接口（用户已宣布方向）

优先级建议：A1（header 自描述消灭常量拷贝）> A2（Host 统一入口）> A3（演进纪律入档）> B2/B3（test 与 addons 入库决策）。

**八轮真机排障沉淀的核心经验**（规范化设计必须吸收）：
1. 返回值永远不能靠寄存器透传——必须显式接住并写回（v0.9.5 教训）
2. 消费端协议校验用下限不用等值（本次立绘教训）
3. 多写者共享内存必须分段、各清各写各（v0.9.2 教训）
4. 布局只追加不挪动；改动必须 C/PY 双侧同步+尺寸自检
5. 装钩失败的每条路径都要有日志（v0.9.3 教训：静默跳过浪费两轮排查）
6. thunk 实例数与表槽数必须一致（v0.9.3 教训：扩槽漏补实例）
7. argc 用 dump.cs 真实签名，不用老 thunk 取格数；虚方法 override 拦不到要找实现类
8. ObscuredInt 字段（key^hidden）读链必须按 obscured kind 读，裸读拿到的是 key
9. 每个事件钩子改动后跑一轮 diag 三层日志再交付
