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
- 本质上就是 python 脚本。
- 可以像正常的 python 脚本一样编写，比如：
```python
import pystray

self = ADDON_ARG['AddonManager']
func_menu = pystray.Menu(pystray.MenuItem('测试', lambda:print('测试?')))

self.menu_items.append(pystray.MenuItem(ADDON_ARG['AddonName'], action=func_menu))

print('loads')
```
- 这里实现了一个简单的功能，加载的时候实现添加托盘右键功能。
- 至于可以做些什么，可以考虑查看项目源码实现更多的功能。

---

## 发布插件到云端

开发完成后，可以把插件发布到云端插件库，供其他用户下载（与发布 Mod 完全同一套流程）：

1. 打开启动器里的 **扩展工具**（工具箱 → 扩展工具），切到 **🧩 发布插件信息** 页；
2. 选择 `addons/<你的插件名>/` 文件夹（也可以用「从 addons/ 选择」）；
3. 确认预览信息后点 **🚀 上传到云端**。

发布时自动完成：

| 步骤 | 说明 |
|---|---|
| 打包 | 插件文件夹压缩为 `<插件名>.zip`，包内顶层就是 `<插件名>/`，下载解压后正好落在 `addons/<插件名>/` |
| 上传图标 | 蓝奏云 `FaustLauncher.icons` |
| 上传压缩包 | 蓝奏云 **`FaustLauncher.Addons`**（目录名可在 `config/web_config.json` → `lanzou.addons_folder` 改） |
| 云端数据库 | 以直链解析链接填写 `dowload_url`/`icon_url`，写入插件笔记（`config/web_config.json` → `webnote.addon_info`） |

> `dowload_url`/`icon_url` 存的是 `https://lz.qaiu.top/parser?url=<分享链接>` 这类解析链接（兼容旧版启动器）；
> 新版启动器下载前会用 `functions/web_update/lanzou_utils.py` 的 `GetDirectLink` 在**本地**解析成蓝奏云直链
> （含 WAF 挑战求解），解析失败才回退原链接。
> 解析结果按「源 URL → 直链」落盘缓存在 `cache/lanzou_links.json`：蓝奏云直链本身约 30 分钟失效，所以缓存按
> 25 分钟有效（`config/web_config.json` → `lanzou.link_cache_ttl_sec`，设 0 表示不过期）、用前自动重新解析；
> 链接若提前失效，下载会丢掉缓存重解析一次。**改了条目链接（源 URL 变了）就会自动重新解析**，不用手工清缓存；
> 想整体重置可以删掉 `cache/lanzou_links.json` 或调 `lanzou_utils.ClearLinkCache()`。
> 蓝奏云的 downprocess 接口有 IP 频控：请求节流按域名走令牌桶 —— 允许一页图标（`lanzou.burst_requests`，默认 4）
> 并发起步，额度用完才按 `lanzou.min_interval_sec`（默认 1.5 秒）匀速补充；
> 一旦命中限流就进入冷却期（120 秒起、最长 15 分钟，跨重启保留），期间不再撞墙。

数据库更新规则（与 Mod 一致）：

- **同名插件视为更新**：替换描述/版本/链接并**置顶**，`download_count` 保留（不归零）；
- 上传失败（如蓝奏云 cookie 失效）**不会中止发布**：已成功的链接照常写入，缺失的链接沿用云端旧值；
- 新条目 `download_count=0`、`disabled=false`、`is_new=true`，按每页 5 个重新分页并重算 `total_addons`。

> 发布前请确认插件目录里有 **`icon.png`** 和 **`addon_info.json`**（`name` 必填）。
> 版本号云端统一用 `version`（旧文档里的 `addon_version` 也会被自动识别）。
> `settings` 是本地启用状态，**不会**写进云端。
