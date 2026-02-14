## FaustLauncher

浮士德启动器，您人生中绝无仅有的完美启动器。
关于使用视频教程，可以在程序中 '关于' 了解更多。

# 插件
0.6.0 之后，允许自己编写插件。
如何制作插件？-> [插件制作指南](https://github.com/f0lkskill/FaustLauncher/blob/main/MakeAnAddon.md)

# 如何使用？

首先，如果直接运行 exe，就会进入主面板。
可以进行手动汉化更新，mod管理。

想要用本启动器启动边狱巴士，只需一步操作：
打开steam -> 打开边狱巴士库页面 -> 选择属性 -> 在高级启动选项 写入下面内容：

<vbs 的路径(launcher.vbs)> %command% 
(不要加‘<‘和’>' )

这样设置好之后，再点击开始游戏，就可以享受浮士德启动器的启动服务了。
如果是第一次使用，启动器会先更新零协会汉化，然后是气泡mod，最后载入mod并启动游戏，整个过程是完全自动的。

# 其他的功能？
## mod管理
可以添加删除mod，或者禁用启用mod

## 气泡渐变色
这是本程序自带的美化功能
实现了给气泡文本增加渐变色的功能

## 设置
在设置里可以选择更多方案
比如用户自定义名称，可以在个人车票处显示。

## 超链接创建器
可以用来解决边狱巴士c盘的逆天占用资源问题。
先把资源文件夹移到其他盘，然后使用这个功能先选择移动之后的文件夹
再选择资源文件夹原来的目录，然后给予程序管理员权限，即可创建超链接

## 自定义汉化
在这里，用户可以自己修改制作个性的汉化包
修改的内容会被记录，且不会与渐变色加载器冲突
（记住要手动保存）

## 渐变色生成器
生成untity渐变色富文本，可以拿来改技能名称？

# 许可证  
本项目使用[MIT](https://github.com/folkskill/FaustLauncher/blob/main/LICENSE)许可证进行分发  

本项目中部分代码来自[LCTA](https://github.com/HZBHZB1234/LCTA-Limbus-company-transfer-auto)，根据[MIT](https://github.com/HZBHZB1234/LCTA-Limbus-company-transfer-auto/blob/main/LICENSE)许可协议使用。
