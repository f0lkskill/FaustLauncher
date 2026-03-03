import pystray

self = ADDON_ARG['AddonManager']
func_menu = pystray.Menu(pystray.MenuItem('测试', lambda:print('测试?')))

self.menu_items.append(pystray.MenuItem(ADDON_ARG['AddonName'], action=func_menu))

print('loads')