# TODO：把成就钩子从「RVA + prologue」迁移到 il2cpp 元数据定位

> 状态：**待开工**（可行性已验证，见第三节）
> 相关代码：`functions/achievement/battle_watch.py`、`functions/achievement/hook_dll/battle_watch.c`、
> `functions/base/cheat_offsets.py`、`functions/base/il2cpp_exports.py`

## 零、一句话结论

可行。而且这条路不只是「换个定位方式」——它能顺手修掉现有 RVA 方案**一直在漏钩**的问题：
`BattleUnitModel::OnRoundStart_Before` 在 dump 里有 **33 处子类 override**，而现在的 RVA 钩子只钩了父类那一份。

---

## 一、现状：成就钩子怎么活的

`battle_watch.py:289` 的 `FALLBACK_HOOKS` 里躺着 27 个观测点，格式是 `键 → (类名::方法名, RVA, 调用约定)`：

| 键 | 符号 | RVA（硬编码兜底） |
| --- | --- | --- |
| `unit_refresh_speed` | `BattleUnitModel::RefreshSpeed` | `0x11C89D0` |
| `unit_set_random_speed` | `BattleUnitModel::SetRandomSpeed` | `0x11C8490` |
| `unit_set_speed` | `BattleUnitModel::SetSpeed` | `0x11C7970` |
| `manager_on_round_start_before` | `BattleActionModelManager::OnRoundStart_Before` | `0xB63FA0` |
| `skv_end` | `BattleSkillViewBase::Skill_End` | `0x9475C0` |
| …（共 27 个） | | |

`battle_watch.py:322` 的 `FALLBACK_FIELDS` 另有 40 个结构体字段偏移（`unit_instance_id: 0x60` 等）。

运行时链路：`cheat_offsets.get_offsets()` → 本地 `config/cheat_offsets.json` → 远端接口 → 拿到 `{rva, prologue}` → 写进 `BWConfig.hook_rva[]` / `hook_prologue[]` → DLL 按 RVA `MH_CreateHook`，并用 16 字节 prologue 自检「跳的地方还是不是那个函数」。

**这套的成本**：游戏每次更新，所有 RVA 和字段偏移全部作废，必须等云端出新数据；prologue 校验只能告诉你「错了」，不能自己恢复。

---

## 二、目标形态

### 2.1 钩子：认名字，不认地址

```
现有：云端/本地给 RVA → MH_CreateHook(RVA)
目标：il2cpp_thread_attach → il2cpp_domain_get → il2cpp_domain_get_assemblies
      → il2cpp_class_from_name("", "BattleUnitModel")
      → il2cpp_class_get_method_from_name(klass, "RefreshSpeed", 0)
      → 得 MethodInfo* → il2cpp_method_get_pointer → MH_CreateHook(指针)
```

好处：方法指针是**运行时算出来的**，游戏发新版自动指向新代码，不需要任何版本数据。

### 2.2 字段：从偏移改成字段名

```
现有：BWConfig.off_state_hp = 0x148（写死）
目标：il2cpp_class_get_field_from_name(klass, "_state") → il2cpp_field_get_offset(field)
      → 运行时得到 0x148，写进同一份 BWConfig
```

DLL 侧读内存的代码**一行都不用改** —— 它读的还是 `off_*`，只是这些值改成运行时填的。

### 2.3 虚方法：遍历所有实现

```
il2cpp_class_get_methods(klass)  → 逐个比对方法名
再对每个派生类（il2cpp_class_get_children 或 domain 全类扫描）同样枚举
把所有「同名同参」的实现全部挂上
```

这是现有方案做不到、而元数据方案能做好的部分。

### 2.4 缓存

解析结果落到 `config/il2cpp_offsets/<GameAssembly sha256 前16位>.json`，结构：

```json
{
  "sha256": "…",
  "hooks": { "unit_refresh_speed": {"klass": "BattleUnitModel", "method": "RefreshSpeed",
                                    "ptrs": [4891232, 4891240]}, … },
  "fields": { "unit_instance_id": 96, "unit_origin_speed": 204, … },
  "resolved_at": "2026-10-26T21:00:00"
}
```

同一版本游戏只解析一次（和 `il2cpp_exports` 同一套缓存约定）。游戏一更新 sha256 变，自动重算。

---

## 三、可行性证据

### 3.1 字段偏移与 dump 完全对得上

拿 `dump.cs` 里 `public abstract class BattleUnitModel`（`TypeDefIndex: 20669`）的字段注释逐项比对：

| `FALLBACK_FIELDS` 键 | 现值 | dump.cs 字段 | dump 注释 | 一致 |
| --- | --- | --- | --- | --- |
| `unit_instance_id` | `0x60` | `_instanceID` | `// 0x60` | ✅ |
| `unit_origin_id` | `0x64` | `_originID` | `// 0x64` | ✅ |
| `unit_origin_speed` | `0xCC` | `_originSpeed` | `// 0xCC` | ✅ |
| `unit_overwrited_speed` | `0xD0` | `_overwritedSpeed` | `// 0xD0` | ✅ |
| `unit_buff_detail` | `0xE0` | `_buffDetail` | `// 0xE0` | ✅ |

即：**字段名是稳定的，偏移是它的函数**。`il2cpp_field_get_offset` 返回的就是 dump 注释里那个数字。

### 3.2 需要的 il2cpp API 全部在基准表里

`il2cpp-api-names.txt`（234 行）已确认含：

- `il2cpp_class_from_name`、`il2cpp_class_get_method_from_name`、`il2cpp_class_get_methods`
- `il2cpp_class_get_field_from_name`、`il2cpp_class_get_fields`、`il2cpp_field_get_offset`
- `il2cpp_field_get_value`、`il2cpp_field_static_get_value`、`il2cpp_method_get_pointer`
- `il2cpp_domain_get_assemblies`、`il2cpp_assembly_get_image`
- `il2cpp_thread_attach`、`il2cpp_thread_detach`

不需要新增基准表条目，**导出名映射那套直接复用**。

### 3.3 虚方法覆盖：现有方案的已知漏点

| 方法 | 定义 | 子类 override 次数 |
| --- | --- | --- |
| `BattleUnitModel::RefreshSpeed` | `public virtual void` | 1 |
| `BattleUnitModel::OnRoundStart_Before` | `public virtual void` | **33** |
| `BattleUnitModel::GetTakeAttackDmgMultiplier` | `public virtual float` | 134（多为同名不同签名的 Buff 版本） |
| `BattleActionModelManager::OnRoundStart_Before` | `public void`（非虚） | 0 |

现在只钩父类那一份，就意味着**33 个 override 的子类单位在回合开始时不会被观测到**。迁移之后可以全挂上，顺带修掉。

---

## 四、分阶段任务

### P0 离线验证（不需要游戏跑起来）

- [ ] 写 `tools/analysis/dump_index.py`：解析 `dump.cs`，产出 `类名 → {方法名: [签名]}`、`类名 → {字段名: 偏移}`
- [ ] 写一次性校验脚本：把 `FALLBACK_FIELDS` 的 40 项逐个去 dump 索引里查，输出「对得上 / 查不到 / 对不上」三张表
- [ ] 把 `FALLBACK_HOOKS` 的 27 个 `类名::方法名` 逐个查虚方法标记与 override 数量，产出「需要挂几份」的清单
- [ ] 产出 `config/il2cpp_offsets/SOURCE.json`：`语义键 → {类名, 字段名}` 与 `语义键 → {类名, 方法名, 参数个数}` 的人工映射表（这一步是人工活，一次性）

### P1 DLL 侧：字段偏移改成运行时解析

- [ ] `battle_watch.c` 增加元数据解析模块（复用 `battle_snark.c` 的 `find_class` / `find_method_in` 写法）
- [ ] `il2cpp_field_get_offset` 填 `BWConfig.off_*`；解析失败时**回退**到 Python 传进来的值（保持现有行为）
- [ ] 新增 `BWConfig.field_source`（0=硬编码回退，1=运行时解析），写进状态 json 便于排查
- [ ] 自检：同一版本游戏上，运行时解析出来的偏移必须和现有硬编码**逐项相等**，不等就报错退出

### P2 DLL 侧：钩子改成方法指针

- [ ] `il2cpp_class_get_method_from_name` 取 `MethodInfo*`，`il2cpp_method_get_pointer` 得绝对地址
- [ ] 虚方法：`il2cpp_class_get_methods` 遍历父类 + 所有派生类，同名同参全部入列
- [ ] `hook_rva` 语义改为「已是绝对地址」——或者干脆新增 `hook_ptr[]`，保留 `hook_rva[]` 给回退路径
- [ ] prologue 自检保留但**降级为可选**（元数据解析成功时不校验，因为指针天然正确）

### P3 双轨灰度

- [ ] `cheat_offsets.get_offsets()` 仍保留，但只在元数据解析失败时启用
- [ ] 日志里明确写出本次用的是哪条路：`[BattleWatch] 定位方式：il2cpp 元数据（32 个实现）/ 硬编码 RVA`
- [ ] 跑 `test/battle_watch_test.py` 全绿，且成就判定结果与迁移前**逐条一致**

### P4 收尾

- [ ] 移除 `FALLBACK_HOOKS` 里的 RVA 列（保留符号列）
- [ ] 更新 `functions/achievement/hook_dll/README.md` 与 `functions/hook/README.md`
- [ ] 评估 `cheat_offsets.py` 是否只剩 DamageMultiplier 在用（该插件已废弃 → 可整体下线）

---

## 五、风险与坑

| 坑 | 说明 | 对策 |
| --- | --- | --- |
| **虚方法多实现** | `OnRoundStart_Before` 有 33 个 override，全挂会让一次回合开始触发 33 次 | 按方法指针去重；同一个 `sk_on_round` 已有 800ms 去重窗口，可复用 |
| **空方法被内联** | `BattleActionModelManager::OnRoundStart_Before` 的 RVA 和下一个方法只差 `0x10`，实测钩上了但永不触发 | P0 阶段把「方法体疑似为空」的挑出来，这些改用同族的非空方法 |
| **重载歧义** | `il2cpp_class_get_method_from_name` 只按名字 + 参数个数匹配，同参数个数的重载会取第一个 | 拿到 `MethodInfo*` 后用 `il2cpp_method_get_param` 校验参数类型，或改用遍历 + 签名比对 |
| **抽象方法** | `BattleUnitModel` 是 abstract，某些方法可能在它上面只有声明无实现 | 遍历时跳过 `il2cpp_method_get_pointer` 为 0 的项 |
| **泛型方法** | `get_method_from_name` 拿不到泛型实例化后的方法 | 暂不处理；若某个观测点必须用泛型，单独标记走 RVA 回退 |
| **性能** | 战斗里每帧读几十个字段，若每次都走 `il2cpp_field_get_value` 会拖慢 | 只在初始化时解析一次偏移，之后仍按偏移直读内存（现有代码不变） |
| **线程** | il2cpp 的 API 要求线程已 attach | 沿用 `il2cpp_thread_attach`，且解析只在 watcher 线程做一次 |
| **`.ctor` 定位** | `StageStatisticPopupData::.ctor` 这类在元数据里名字就是 `.ctor` | `il2cpp_class_get_method_from_name(klass, ".ctor", argc)` 可用，但要注意与静态构造 `.cctor` 区分 |

---

## 六、验收标准

1. **一致性**：同一版本游戏上，元数据解析出的 40 个字段偏移与旧硬编码逐项相等（P1 自检项）。
2. **覆盖率**：27 个钩子全部解析成功，且 `OnRoundStart_Before` 这类虚方法的实现数 ≥ 父类那 1 份。
3. **版本无关性**：把 `config/cheat_offsets.json` 删掉、断网，成就钩子仍能完整工作。
4. **回归**：`test/battle_watch_test.py` 全绿，成就判定与迁移前逐条一致。
5. **可观测**：状态 json 里能看到「定位方式 / 每个钩子的实现数 / 字段来源」。

---

## 七、和插件生态的关系

迁移完成后，成就钩子就变成了「插件同款」的定位方式：

| | 现在 | 迁移后 |
| --- | --- | --- |
| 定位 | RVA + prologue | 类名/方法名/字段名 |
| 版本数据 | 云端 + 本地缓存 | 无 |
| 失效时机 | 游戏每次更新 | 仅 Unity/il2cpp 大版本升级 |
| 发布 | DLL 随启动器发到 `_internal/hook_dll` | 不变 |
| 覆盖虚方法 | 只能钩父类一份 | 全部实现 |

差别只剩一条：成就钩子仍然**随启动器发布**（因为它服务于内置功能，不是可选插件），而插件是用户目录里的独立包。
