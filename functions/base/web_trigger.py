from functions.webFunc import Note
from json import loads, dumps

class WebTrigger:
    """Web触发器，负责获取来自Web的插件和mod信息"""
    
    def __init__(self, ):
        self.addon_info = Note("FaustLauncher.addons.info")
        self.mod_info = Note("FaustLauncher.mod.info")

    def refersh_note_info(self):
        """刷新插件和mod信息"""
        self.addon_info._fetch_note_info_write()
        self.mod_info._fetch_note_info_write()

    def get_note_info_mod(self):
        self.mod_info._fetch_note_info_write()
        return loads(self.mod_info.note_content)
    
    def get_note_info_addon(self):
        self.addon_info._fetch_note_info_write()
        return loads(self.addon_info.note_content)

    def get_addon_info(self, page: int = 0):
        """获取插件信息"""
        self.addon_info._fetch_note_info_write()
        return loads(loads(self.addon_info.note_content)[page]['content'])
    
    def get_mod_info(self, page: int = 0):
        """获取mod信息"""
        self.mod_info._fetch_note_info_write()
        return loads(loads(self.mod_info.note_content)[page]['content'])
    
    def fectch_all_addon_info(self) -> list[dict]:
        """获取所有插件信息"""
        total_page = self.get_addon_info(0)['total_page']
        addon_info_list = []
        for page in range(1, total_page + 1):
            addon_info_list.append(self.get_addon_info(page))
        return addon_info_list
    
    def fectch_all_mod_info(self) -> list[dict]:
        """获取所有mod信息"""
        total_page = self.get_mod_info(0)['total_page']
        mod_info_list = []
        for page in range(1, total_page + 1):
            mod_info_list.append(self.get_mod_info(page))
        return mod_info_list
    
    def add_download_nummber_addon(self, addon_name: str):
        """增加指定插件的下载次数"""
        if not addon_name:
            return

        pages = self.get_note_info_addon()
        for page in pages[1:]:  # 跳过第一页的总页数信息
                addons = loads(page['content'])
                for addon in addons:
                    if addon['name'] == addon_name:
                        addon['download_count'] += 1
                        page['content'] = dumps(addons, indent=4, ensure_ascii=False)
                        self.addon_info.update_note_content(dumps(pages, indent=4, ensure_ascii=False))
                        break

    def add_download_nummber_mod(self, mod_name: str):
        """增加指定mod的下载次数"""
        if not mod_name:
            return
        
        pages = self.get_note_info_mod()
        for page in pages[1:]:  # 跳过第一页的总页数信息
            mods = loads(page['content'])
            for mod in mods:
                if mod['name'] == mod_name:
                    mod['download_count'] += 1
                    page['content'] = dumps(mods, indent=4, ensure_ascii=False)
                    self.mod_info.update_note_content(dumps(pages, indent=4, ensure_ascii=False))
                    break