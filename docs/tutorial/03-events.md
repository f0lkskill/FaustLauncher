# 03 事情发生的时候通知我

上一篇是「我主动让游戏做事」。这一篇反过来：**游戏里发生事的时候，让我知道。**

新手最容易想到的写法是「一直循环，发现变化就处理」。但读游戏内存是**跨进程往返**，
一次 20–40 毫秒，一秒看一眼全场就要几百毫秒——卡。所以正确的写法是**让游戏通知你**。

在 `warp.game` 里，这件事被压成了一个函数：

```python
game.on_round_start(_on_round)
```

你只写 `_on_round` 这个函数，什么时候调它是框架的事。

## 示例：战况播报

```python
--8<-- "docs/examples/watch/scr.py"
```

```json
--8<-- "docs/examples/watch/addon_info.json"
```

进战斗、打一个回合，日志里就会出现：

```text
[战况播报] —— 战斗：场上 11 个单位 ——
[战况播报]   #1  人格 10115  HP 245/248  SP 45
[战况播报]   #2  人格 8732   HP 60/526
[战况播报]   #3  人格 0      HP 62/62
...
```

## `Battle` 是什么

回调拿到的参数是那一刻的**全场快照**：

| 属性 | 说明 |
| --- | --- |
| `battle.units` | 单位列表（`Unit` 对象） |
| `battle.count` | 单位数 |
| `battle.alive` | 还活着的单位（列表推导好了） |
| `battle.scene` / `battle.scene_name` | 场景编号 / 中文名 |
| `battle.by_id(1)` | 按界面上那个编号找 |
| `battle.by_identity(10115)` | 按人格 ID 找 |

注意它是**快照**：拿到 `Battle` 的时候单位列表不会变，但单位里的数值每次读都是现读的。
想留一份历史就自己抄一份。

## 三种现成的通知

### 每回合开始

```python
game.on_round_start(lambda battle: print(battle.count))
```

绑的是游戏自己的「回合开始」。一回合一次，频率很低，随便你在这里干什么
（读全场、弹窗、写文件都行）。

### 场景切换

```python
game.on_scene_changed(lambda scene: print(scene['name']))
```

`scene` 是个字典：`{'value': 1, 'name': '战斗', 'time_scale': 1.0, 'entries': 1}`。
场景编号对照：

| 值 | 场景 | 值 | 场景 |
| --- | --- | --- | --- |
| 0 | 登录 | 5 | 镜像地牢 |
| 1 | 战斗 | 6 | 铁路 |
| 2 | 主界面 | 7 | 剧情镜像 |
| 3 | 剧情 | 8 | ProjectGS |
| 4 | 地牢 | 9 | Rpg |

### 进战斗 / 出战斗

```python
game.on_battle_start(lambda battle: print('开打了', battle.count))
game.on_battle_end(lambda scene: print('打完了', scene['name']))
```

这两个是上面那个的语法糖，专门给「只在战斗里干活」的插件用。

## 回调跑在哪个线程

**独立的后台线程**，不是游戏的线程。所以：

- ✅ `time.sleep()` 是安全的
- ✅ 弹窗、读文件、发网络请求都不影响游戏
- ⚠️ 回调 **慢** 会堆积：一次读全场是几十次往返，可能要 1 秒

```python
def _on_round(battle):
    for u in battle.units:   # 11 个单位
        print(u.hp)          # 每次 20–40ms，一圈下来约 0.3 秒
```

0.3 秒对回合级回调完全没问题。但如果你在 `on_scene_changed` 里也这么干，
切场景时会明显卡一下——**按需读**才是对的：

```python
def _on_scene(scene):
    if scene['value'] != 1:      # 不是战斗就什么都不做
        return
    ...
```

## 为什么没有 `on_hp_changed`

你可能会想「血量变了就通知我」。这个能力**故意没做**，原因是成本：

- 血量变化发生在**每一次受击**，一回合几十次；
- 而每次通知都要跨进程往返，真做出来就等于每帧都在读内存，反而卡。

正确的做法是**在回合边界比较**：

```python
_last = {}

def _on_round(battle):
    for u in battle.units:
        old = _last.get(u.id)
        if old is not None and u.hp < old:
            print(f'#{u.id} 掉了 {old - u.hp} 点血')
        _last[u.id] = u.hp
```

需要「掉血的那一帧」再动手的插件，看第 08 篇——那里讲怎么钩住具体的游戏方法。

## 这一篇你该记住的

- 通知 = 你写函数，框架决定何时调
- `on_round_start` / `on_scene_changed` / `on_battle_start` / `on_battle_end`
- 回调参数是快照（`Battle` / `scene` 字典），单位里的数值是现读的
- 回调在后台线程，`sleep` 安全，但**别在回调里无脑遍历全场**
- 想要「变化的那一瞬间」，得自己比较，或者用第 08 篇的钩子

下一篇开始逐个读单位身上的数：编号、人格、血量、速度。
