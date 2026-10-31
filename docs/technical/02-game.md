# 02 warp.game —— 游戏门面

日常插件用的就是这一层。**一句话一个动作**，不需要认识类名、方法名、偏移。

```python
game = _NS.space('warp').game
```

## 模块级函数

全部是薄包装，内部共用一个按插件名记账的 `Live` 实例。

| 函数 | 返回 | 说明 |
| --- | --- | --- |
| `start(menu=())` | `Live` | 启动后台心跳 + 注册托盘菜单。插件里调一次 |
| `popup(text, timeout=2.0, wait=True, wait_timeout=120.0)` | `str` | 让游戏弹一句话，返回回执（`已执行` / `共享内存不可用` / …） |
| `status()` | `dict` | 宿主状态字典，见下表 |
| `describe()` | `str` | 一行人类可读的状态文本 |
| `scene(timeout=1.0)` | `dict` | `{'value','name','time_scale','entries'}` |
| `battle(timeout=1.0)` | `Battle\|None` | 当前战斗快照；拿不到返回 `None` |
| `units(limit=None)` | `list[Unit]` | 场上全部单位 |
| `count()` | `int` | 场上单位数 |
| `unit(id=None, identity=None, index=None)` | `Unit\|None` | 三种找法任选一个 |
| `player()` | `Unit\|None` | 我方第一个单位 |
| `on_round_start(handler)` | `None` | 每回合开始调 `handler(battle)` |
| `on_scene_changed(handler)` | `None` | 切场景调 `handler(scene_dict)` |
| `on_battle_start(handler)` | `None` | 进战斗调 `handler(battle)` |
| `on_battle_end(handler)` | `None` | 出战斗调 `handler(scene_dict)` |
| `close()` | `None` | 停心跳、注销回调、关映射。`on_unload` 里调 |
| `live(owner=None, host=None)` | `Live` | 拿/建实例（模块级函数都走它） |

`status()` 返回的键：

| 键 | 含义 |
| --- | --- |
| `ready` | 共享内存可用 |
| `enabled` | 宿主已启用 |
| `hooked` | 钩子已装上（可以开始读数据） |
| `status` / `status_text` | 宿主状态码 / 文本 |
| `evt_count` | 事件环累计产出（涨=游戏在跑） |
| `fired` | 动作触发次数 |
| `hook_installed` / `hook_total` | 已装钩子数 / 总钩子数 |
| `ga_found` | 找到 GameAssembly.dll |
| `popup_ok` | 弹窗能力可用 |
| `standalone` | 启动器已退出、DLL 独立存活 |
| `log_tail` | 宿主日志尾部 |

## `Live` 类

模块级函数背后是它。需要**多个独立通道**（比如一个插件管两个不同的游戏场景监听）时才自己
`Live(...)`：

```python
live = game.Live(owner='我的插件')
live.on_round_start(handler)
live.start(menu=(('看状态', lambda: print(live.describe())),))
```

| 成员 | 说明 |
| --- | --- |
| `Live(owner=None, host=None, auto=True)` | `auto=True` 表示游戏启动时自动注入 |
| `.host()` | 拿底层 `Host`（要写钩子时用） |
| `.start(menu=())` | 起心跳线程 + 注册菜单 |
| `.close()` | 收尾（幂等） |
| `.status()` / `.describe()` | 同上 |
| `.scene(timeout)` / `.battle(timeout)` | 同上 |
| `.units()` / `.count()` / `.unit()` / `.player()` | 同上 |
| `.popup(text, timeout, wait, wait_timeout)` | 同上 |
| `.log(message)` | 带插件名前缀打日志 |
| `.on_round_start` / `.on_scene_changed` / `.on_battle_start` / `.on_battle_end` | 注册回调 |

## `Battle` 对象

回调参数，一次战斗快照。

| 成员 | 说明 |
| --- | --- |
| `.units` | `Unit` 列表 |
| `.count` | 单位数 |
| `.alive` | 还活着的单位列表 |
| `.scene` / `.scene_name` | 场景编号 / 中文名 |
| `.by_id(n)` | 按战斗内编号找 |
| `.by_identity(n)` / `.ally(n)` | 按人格 ID 找 |
| `len(battle)` / `for u in battle` | 当列表用 |

```python
def _on_round(battle):
    boss = battle.by_identity(8732)
    if boss:
        print('BOSS 血量', boss.hp)
game.on_round_start(_on_round)
```

## `SCENES` 常量

```python
game.SCENES   # {0:'登录', 1:'战斗', 2:'主界面', 3:'剧情', 4:'地牢',
              #  5:'镜像地牢', 6:'铁路', 7:'剧情镜像', 8:'ProjectGS', 9:'Rpg'}
```

## 抽卡：`gacha`

`warp.game` 里还挂着一套专门处理抽卡的语义层（NoGacha 插件就靠它）。

### `gacha.on_buy(handler, allow_paid=True, interval=0.25, host=None)`

```python
def handle_gacha(bill):
    if bill.is_paid:
        print('拦下一单付费抽卡')

game.gacha.on_buy(handle_gacha, allow_paid=False)
```

| 参数 | 说明 |
| --- | --- |
| `handler(bill)` | 被拦下时调，`bill` 是 `GachaBill` |
| `allow_paid` | `False` = 付费单抽也拦；`True` = 放行付费 |
| `interval` | 轮询间隔（秒） |

### `GachaBill` 属性

| 属性 | 类型 | 说明 |
| --- | --- | --- |
| `.type_id` | `int` | 抽卡类型编号 |
| `.type_name` | `str` | 类型中文名 |
| `.is_paid` | `bool` | 是付费单抽 |
| `.is_free` | `bool` | 是免费 |
| `.gacha_id` / `.payment_id` | `int` | 卡池 / 支付方式编号 |

`GACHA_TYPE_NAMES = {0:'普通', 1:'付费单抽', 2:'不能用狂气', 3:'免费'}`。

### 其他

| 成员 | 说明 |
| --- | --- |
| `gacha.hooks(allow_paid=True)` | 返回那两条底层钩子（想自己装配时用） |
| `gacha.bill(host)` | 读当前这一单 |
| `gacha.blocked(host)` | 累计拦下次数 |
| `gacha.stop(owner=None)` / `gacha.stop_all()` | 停掉监视线程 |
| `GachaWatcher` | 监视线程的句柄（`.stop()` / `.running`），插件一般不用管 |

!!! note "`on_buy` 和 `game.units()` 是两套餐"
    抽卡这套是**最早的语义层**（v0.4 时代），写法是「传一个 handler 进来，框架起线程」；
    `game.*` 是后来的门面，写法是「模块级函数直接调」。两者并存，不冲突。
