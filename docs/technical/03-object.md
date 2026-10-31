# 03 warp.object —— 对象门面

`Unit` / `Buff` / `Access` 三个类，以及一组需要自己传 `Host` 的底层函数。

```python
obj = _NS.space('warp').object
u = obj.unit(host, 0)          # 底层：自己要给 host
u = game.units()[0]            # 门面：同一批对象，host 帮你管好了
```

两种拿到的都是同一个 `Unit` 类，差别只在谁负责创建 `Host`。

## 对象槽常量

| 常量 | 值 | 用途 |
| --- | --- | --- |
| `SLOT_MANAGER` | `28` | 全局管理器 `BattleObjectManager` |
| `SLOT_SCENE` | `29` | 场景根对象 `GlobalGameManager`（命令泵每帧自动缓存） |
| `SLOT_SCRATCH` | `27` | 临时用（抓单个对象、探针） |

!!! warning "0..23 是成就观测的主段，24..26 谁都能用，27..29 见上表，30/31 是每帧回调保留位"

## `Unit` —— 一个战场单位

### 属性

| 属性 | 类型 | 含义 |
| --- | --- | --- |
| `u.id` | `int` | 战斗内编号（1、2、3…） |
| `u.identity` / `u.origin_id` | `int` | 人格 ID（角色静态 ID，浮士德魁首 = 10212） |
| `u.hp` | `int` | 当前血量（已解混淆） |
| `u.max_hp` | `int` | 最大血量 |
| `u.sp` | `int` | 理智，负数表示恐慌计数 |
| `u.speed` | `float` | 速度（已从 ×1000 定点数除回） |
| `u.hp_ratio` | `float\|None` | 血量比例 0..1 |
| `u.alive` | `bool\|None` | 还活着（优先看 `_isDead`） |
| `u.is_dead` | `bool\|None` | 已阵亡 |
| `u.is_break` | `bool\|None` | 混乱 |
| `u.is_panic` | `bool\|None` | 恐慌 |
| `u.is_low_morale` | `bool\|None` | 士气低落 |
| `u.index` | `int` | 在字典活跃项里的序号（不是 `id`） |
| `u.slot` / `u.host` | — | 内部用的宿主与槽号 |

布尔属性读不到时是 `None`，**不是 `False`**。

### 方法

| 方法 | 返回 | 说明 |
| --- | --- | --- |
| `u.get_pro(key, default=None)` | 任意 | 按字段名取值，支持 `hp` / `_hp` / `CharacterState._hp` / `_state._hp` |
| `u.read(*chain, kind="int", default=None, timeout=2.0)` | 任意 | 从这个单位出发自己拼读链 |
| `u.props(timeout=1.0)` | `dict` | `BattleUnitModel` + `CharacterState` 全字段（60 多个，慢） |
| `u.scan(classes=("BattleUnitModel","CharacterState"), timeout=1.0)` | `dict` | 同上，可挑类 |
| `u.state()` | `dict` | 11 个常用字段一次拿齐 |
| `u.buff_count()` | `int` | 身上几个 buff |
| `u.buffs` | `list[Buff]` | 全部 buff |
| `u.buff(key, default=None)` | `Buff\|None` | 按序号 / 英文 ID / 中文名找 |
| `u.has_buff(key)` | `bool` | 有没有 |
| `u.buff_id(i)` | `int` | 第 i 个 buff 的英文 ID 指纹（数字，快） |
| `u.buff_ids()` | `list[int]` | 全部指纹 |

```python
u = game.player()
print(u.id, u.identity, u.hp, u.max_hp, u.sp, u.speed)
print(u.get_pro('_totalTakeDamageInThisBattle'))
print(u.has_buff('Breath'), u.buff('Breath').stack)
```

### 自己拼链

`u.read()` 的链写法与钩子的 `reads=` 完全一致：

```python
u.read({'off': 0x10, 'deref': True}, {'off': 0x60, 'deref': False}, kind='int')
```

| 步 | 写法 | 含义 |
| --- | --- | --- |
| 加偏移 | `{'off': 0x10}` | 默认 `deref=True`：加完偏移再解引用 |
| 只加偏移 | `{'off': 0x60, 'deref': False}` | 落在字段本身（读 int/float 时用） |
| List 第 i 项 | `{'list': 0}` | 进 `List<T>` 取第 0 个 |
| Array 第 i 项 | `{'array': 0}` | 进 `T[]` |
| List 值 | `{'list_val': 0}` | 直接取第 i 个 4 字节值（值类型容器） |
| Dictionary 第 k 个 | `{'dict': 0}` | `Dictionary<K,V>` 第 0 个活跃 value |
| Dictionary 值 | `{'dict_val': 0, 'value_off': 16, 'stride': 24}` | 值直出，可自定义布局 |
| 遍历 | `{'dict': 'iter'}` | 一次命中展开 N 条（批量） |

### 落点 `kind`

| `kind` | 得到 | 用途 |
| --- | --- | --- |
| `int` | 有符号 32 位 | 默认 |
| `float` | IEEE754 单精度 | 速度、比例 |
| `bool` | 布尔 | 普通布尔字段 |
| `obscured` | 解混淆后的 int | 游戏里的 `ObscuredInt`（血量、理智） |
| `ptr` | 64 位指针 | 要用低 32 位时 |
| `sum` | 求和 | 容器求和 |
| `count` | 元素数 | `List<T>` / `T[]` |
| `dict_count` | 活跃项数 | `Dictionary<K,V>`（已扣掉死坑） |
| `text` | 字符串指纹 | il2cpp string 的数字换算，**不是原文** |
| `buff_mask` | bitmask | 判断「身上有没有某几个 buff」 |

## `Buff` —— 一个 buff

| 属性 | 类型 | 含义 |
| --- | --- | --- |
| `b.key` | `str\|None` | 英文 ID（`Breath`）——**写逻辑用这个** |
| `b.name` | `str\|None` | 中文名（`呼吸法`）——给玩家看 |
| `b.stack` | `int` | 当前层数 / 强度 |
| `b.turn` | `int` | 剩余次数 / 回合 |
| `b.max_stack` | `int` | 层数上限 |
| `b.max_turn` | `int` | 次数上限 |
| `b.stack_ratio` | `float\|None` | 层数比例 0..1 |
| `b.icon` | `str\|None` | 图标 ID |
| `b.type_id` | `int` | buff 类型编号 |
| `b.index` | `int` | 第几个 |

| 方法 | 说明 |
| --- | --- |
| `b.raw()` | 9 个字段的字典 |
| `b.has(key)` | 这个 buff 是不是 key（等价 `b.key == key`） |

```python
for b in u.buffs:
    print(b.key, b.stack, b.turn, b.max_stack)
```

## `Access` —— 直连管理器的通道

`Unit` 的所有读都要经过「管理器 → 字典 → 第 i 项」。`Access` 就是把这条前缀管起来，
顺便提供几个 Unit 门面没暴露的入口（拿到原始指针）。

```python
acc = obj.access(host)           # 或 game.live(). 的 host
acc.manager()                    # 确保管理器就位，返回槽号
total = acc.count()              # 单位数
units = acc.units(limit=None)    # Unit 列表
u = acc.get_obj(id=1)            # 按编号 / index=0 按序号
scene = acc.scene()              # 场景信息
ptr = acc.unit_ptr(0)            # BattleUnit 原始地址
acc.reader()                     # 跨进程读取器（读字符串用）
acc.close()                      # 释放
```

| 方法 | 说明 |
| --- | --- |
| `manager(timeout=3.0, force=False)` | 调静态方法 `BattleObjectManager::get_Instance` 把管理器抓进槽 28 |
| `count()` | 单位总数（`dict_count`） |
| `units(limit=None)` | `Unit` 列表 |
| `get_obj(id=None, index=None)` | 取一个 |
| `scene(slot=SLOT_SCENE)` | 场景字典 |
| `unit_ptr(index)` | `BattleUnit` 地址 |
| `buff_model_ptr(index, buff_index, unit_ptr=None)` | `BuffModel` 地址 |
| `buff_info_ptr(...)` / `buff_static_ptr(...)` | `BuffInfo` / `BuffStaticData` 地址 |
| `reader()` | `remote.RemoteReader`，懒加载，读 UTF-16 字符串 |
| `close()` | 关掉读取器与其他资源 |

## 模块级函数

都要自己传 `Host`（`host` 是第一个参数）：

| 函数 | 说明 |
| --- | --- |
| `units(host, slot=SLOT_MANAGER, limit=None, acc=None)` | 单位列表 |
| `unit(host, index, slot=SLOT_MANAGER, acc=None)` | 一个单位 |
| `count(host, slot=SLOT_MANAGER)` | 单位数 |
| `snapshot(host, slot=SLOT_MANAGER, limit=None)` | `[{...}]` 简表，每个单位一组常用字段 |
| `access(host, slot=SLOT_MANAGER, **kwargs)` | 建 `Access` |
| `scene(host, slot=SLOT_SCENE)` | 场景编号 |
| `scene_full(host, slot=SLOT_SCENE, timeout=1.0)` | 场景全字段 |
| `scene_name(value)` | 编号 → 中文名 |
| `scan_class(host, slot, cls, timeout=1.0)` | 槽里那个对象按类扫全字段 |
| `scan_object(host, slot, cls, base=(), timeout=1.0)` | 先走一段 base 再扫 |
| `bind_manager(host, klass="BattleObjectManager", method="OnRoundStart_Model", argc=1, slot=SLOT_MANAGER, timeout=180.0, extra_hooks=())` | 装钩子抓管理器（会等） |
| `bind_scene(host, klass="GlobalGameManager", method="FixedUpdate", argc=0, ...)` | 等场景根对象（**只等不钩**，用泵缓存的槽 29） |

```python
host = _W.plugin.Host(ADDON_NAME)
obj.bind_manager(host)                       # 抓管理器
for u in obj.units(host, limit=3):           # 只看前三个
    print(u.id, u.hp)
print(obj.snapshot(host, limit=2))           # 简表
```

!!! note "`bind_scene` 只等不钩"
    `GlobalGameManager.FixedUpdate` 是宿主的**命令泵入口**。钩它会让泵无处落脚，
    日志出现 `pump: no free entry point, cmd channel off`，代读全废。
    槽 29 由泵每帧自动缓存，直接读就行。
