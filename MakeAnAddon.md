# 如何编写一个插件？

首先，需要制作以下的文件结构...

```
YourAddonName:
|___icon.png
|___addon_info.json
|___scr.py
```

### 让我们来看看这些文件的作用吧...
##### icon.png *插件的图标*
- 没什么好说的，会显示在插件列表的图标。
- 必须为 **png** 格式且名字只能是 **icon**

##### addon_info.json *插件信息*
结构类似于如下：
```json
{
    "name": "示例插件",
    "desc": "这是一个示例插件...",
    "authors": {
        "FolkSkill": "https://space.bilibili.com/599331034"
    },
    "settings": {
        "enable": true
    },
    "addon_version": "0.0.1"
}
```
- **name**    : 插件的名字
- **desc**    : 插件的描述
- **authors** : 作者信息，字典，键为作者名字，值为相关链接
- **settings**: 字典，存贮插件相关的设置，至少包含 *enable* 键，这表示这个插件是否启用了
- **addon_version**: 版本号标识符

##### scr.py *插件的核心功能实现*
-本质上就是 python 脚本。
-可以像正常的 python 脚本一样编写，比如：
```python
import pystray

self = ADDON_ARG['AddonManager']
func_menu = pystray.Menu(pystray.MenuItem('测试', lambda:print('测试?')))

self.menu_items.append(pystray.MenuItem(ADDON_ARG['AddonName'], action=func_menu))

print('loads')
```
-这里实现了一个简单的功能，加载的时候实现添加托盘右键功能。
-至于可以做些什么，可以考虑查看项目源码实现更多的功能。
