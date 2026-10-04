# 成就插件模板

用插件给启动器加**自定义成就**。整个机制就一句话：把你的成就类放进插件的 `achievements.py`，
启动器加载插件时会把它们登记到和内置成就同一张表里 —— 之后**成就页显示、游戏中判定、解锁弹窗、
写进存档**全部一模一样，不需要改启动器任何代码。

---

## 目录结构

```
addons/我的成就/
├── addon_info.json          # 插件清单（复用启动器现有插件格式）
├── achievements.py          # 成就定义（本模板的核心）
└── assets/
    └── achievement/         # 可选：成就图标 <成就id>.png
```

复制本目录改名即可，例如 `addons/我的成就/`。

> `scr.py` 是**可选**的：它只在插件需要"启用时执行安装动作"时才有用
> （启动器把没有 `scr.py` 的插件视为"仅信息型"）。纯成就插件不需要它。

## addon_info.json

```json
{
    "name": "我的成就",
    "desc": "插件说明（插件页会显示）",
    "authors": { "你的名字": "https://example.com" },
    "achievements": "achievements.py",
    "settings": { "enable": true },
    "version": "1.0.0"
}
```

| 字段 | 说明 |
|---|---|
| `achievements` | 成就模块文件名，**可省略**（默认就是 `achievements.py`） |
| `settings.enable` | `false` 时**整个插件被跳过**（不做成就、也不注册） |

> 改完要**重启启动器**（或托盘菜单「重载插件」）才会生效 —— 成就模块只在加载插件时读一次。

## achievements.py

两种写法，选一种：

```python
# 写法 A（推荐）：模块里定义类，按定义顺序自动实例化
class MyAchievement(SkillUseAchievement):
    def __init__(self):
        super().__init__(ach_id="ach_my_1", name="...", description="...", ...)

# 写法 B：自己给实例和顺序（有 ACHIEVEMENTS 时以它为准）
ACHIEVEMENTS = (MyAchievement(), OtherAchievement())
```

硬性规则：

* `ach_id` **必须全局唯一**（与内置成就重名会被拒绝并跳过，不会覆盖）；
* `name` / `description` 是给玩家看的，写中文；
* `rarity` 取值：`common` / `uncommon` / `rare` / `epic` / `legendary` / `mythic`
  —— 决定成就页徽标的**边框颜色**（由前端自动着色）；
* 复合成就的 `BattleRule(key=...)` 也必须唯一，建议写成 `<ach_id>.条件名`。

## 可用的成就基类（全部来自内置驱动）

| 基类 | 判定内容 | 关键参数 |
|---|---|---|
| `SkillUseAchievement` | 某身份用了某技能 | `skill_ids` / `tiers`+`identity_id` / `any_skill`、`max_round`、`min_round` |
| `SpeedValueAchievement` | 速度达到阈值 | `identity_ids`、`value`、`fields` |
| `MentalThresholdAchievement` | 理智达到阈值（负=恐慌） | `identity_ids`、`threshold` |
| `DamageTakenAchievement` | 单次受击掉血比例 | `identity_ids`、`ratio`（0.5 = 50%） |
| `BuffPresentAchievement` | 身上带着某 buff | `identity_ids`、`buffs`（**buf 名是字符串 id**）、`max_round` |
| `FieldPresenceAchievement` | 某身份在场上 | `identity_ids`、`max_round`、`min_round` |
| `CompositeAchievement` | 多条件组合（与/或/非 + 先后顺序） | `conditions`、`require`、`chain`、`implied` |

它们的实现都在 `functions/achievement/battle_achievements.py`，想深度定制可以直接继承
`BattleRuleAchievement` 自己拼 `battle_watch.BattleRule`。

## 数据怎么查

| 要什么 | 去哪找 | 例子 |
|---|---|---|
| 身份 id | 5 位：`<罪人2位><人格2位>` | `10101` 李箱 LCB、`10916` 罗佳 拇指 父辈 |
| buff 名 | 游戏 `LimbusCompany_Data/Lang/LLC_zh-CN/Bufs.json` 的 `id` 字段 | `HanafudaTwo` = 组札-芒上月 |
| 技能 id | 7 位：`<身份5位><槽位2位>` | `1010103` = 李箱 LCB 三技能 |
| 速度/理智/血量 | 直接给阈值 | 理智 = 界面 SP，范围 ±45 |

写错了不会崩：判定不成立就一直不解锁而已。想看驱动实际看到了什么，
可以看游戏运行时生成的 `logs/battle_watch.log`（全量事件流）。

## 图标（可选）

把图片放在 `addons/我的成就/assets/achievement/<成就id>.png`（也支持 `webp/jpg/svg`），
启动时会同步到前端素材目录，成就页自动使用；同名文件不会被覆盖。

* **别在图片里画边框** —— 边框由前端按 `rarity` 自动着色；
* 建议正方形、透明底、≥128px。

## 排错

| 现象 | 原因 |
|---|---|
| 成就页看不到你的成就 | `addon_info.json` 里 `settings.enable` 还是 `false`；或 `ach_id` 与内置重名被拒 |
| 改完没生效 | 没重启启动器（成就模块只在加载插件时读一次） |
| 永远不解锁 | 参数（身份/buff/技能 id）写错了，或回合窗口 `max_round` 太紧 |
| 想看日志 | 启动器日志里会有 `[成就] 插件自定义成就: N 个（ach_xxx, ...）` |
