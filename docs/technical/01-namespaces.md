# 01 命名空间机制

插件之间不直接 import 对方的代码，而是通过启动器提供的**命名空间容器**互相提供能力。
WarpHook 注册的东西全部挂在 `warp` 下，别的插件要用就 `space('warp')`。

## 取能力

```python
_NS = ADDON_ARG.get('Namespaces')

warp   = _NS.space('warp')          # 顶级：拿到整个 WarpHook
game   = _NS.space('warp.game')     # 扁平取：直接拿子分区
game2  = warp.game                  # 嵌套取：等价写法
```

两种写法完全等价。根上只出现 `warp` 一个名字，所以别的插件也能注册自己的
`il2cpp`、`flash` 之类，不会互相覆盖。

## 查看有哪些

```python
_NS.spaces()        # ['warp', 'warp.game', 'warp.object', ...]
```

## 提供能力（想让别的插件用你的功能）

```python
mine = _NS.provide('myaddon', name=ADDON_NAME, version='0.1.0',
                   description='我的插件提供的能力',
                   do_something=my_function,   # 任意键值，都会成为属性
                   MAX_ITEMS=16)

sub = _NS.provide('myaddon.extra', helper=some_helper)
mine.expose('extra', sub)          # 嵌套暴露：NS.space('myaddon').extra
```

`provide` 的返回值既是一个 space 对象，也可以当字典用。

## 元信息

每个 space 上都有三个固定字段：

| 字段 | 说明 |
| --- | --- |
| `name` | 提供方插件名 |
| `version` | 提供方版本 |
| `description` | 一句话说明（`spaces()` 查看时也可见） |

判断依赖版本：

```python
if warp.version.split('.') < ['0', '9', '9']:
    print('WarpHook 太旧，请更新')
```

!!! warning "别用字符串大小比较版本号"
    `'0.9.10' < '0.9.9'` 在字符串比较下成立。要严格比较就拆成 `int` 元组。

## 一个插件能注册多个命名空间

`provide` 可以调多次，名字不同即可：

```python
_NS.provide('myaddon.core', ...)
_NS.provide('myaddon.ui', ...)
```

但通常一个够了——子功能用 `expose` 挂在同一个 space 下面更好找。
