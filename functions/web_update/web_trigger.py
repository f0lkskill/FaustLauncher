from functions.webFunc import Note
from json import loads, dumps

class WebTrigger:
    """Web触发器，负责获取来自Web的插件和mod信息"""
    
    def __init__(self, ):
        self.addon_info = Note("FaustLauncher.addons.info")
        self.mod_info = Note("FaustLauncher.mod.info")
        self.sort_info_by_download_number()

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
                        
        self.sort_info_by_download_number()

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
        
        self.sort_info_by_download_number()
    
    def sort_info_by_download_number(self):
        """按下载次数排序插件和mod信息"""
        # 排序插件信息
        try:
            pages = self.get_note_info_addon()
            for page in pages[1:]:  # 跳过第一页的总页数信息
                addons: list[dict] = loads(page['content'])
                # 按下载次数降序排序，被禁用插件默认排序在最后
                addons.sort(key=lambda x: (x.get('disabled', False), -x.get('download_count', 0)))
                page['content'] = dumps(addons, indent=4, ensure_ascii=False)
            # 更新排序后的插件信息
            self.addon_info.update_note_content(dumps(pages, indent=4, ensure_ascii=False))
            print("插件信息按下载次数排序完成")
        except Exception as e:
            print(f"排序插件信息时出错: {e}")

        # 排序mod信息
        try:
            pages = self.get_note_info_mod()
            mods: list[dict] = []
            for page in pages[1:]:  # 跳过第一页的总页数信息
                for m in loads(page['content']):
                    mods.append(m)

            # 按下载次数降序排序，被禁用mod默认排序在最后
            mods.sort(key=lambda x: (x.get('disabled', False), -x.get('download_count', 0)))

            new_pages = []
            # 五个五个分页，每五个放在一个list中
            total_page = len(mods) // 5 + (1 if len(mods) % 5 != 0 else 0)
            for i in range(total_page):
                new_pages.append(mods[i * 5:(i + 1) * 5])

            # 用 enumerate 安全地按索引分配内容，避免 index() 查找导致的错误
            for idx, page in enumerate(pages[1:], start=0):
                if idx < len(new_pages):
                    page['content'] = dumps(new_pages[idx], indent=4, ensure_ascii=False)

            # 更新排序后的mod信息
            self.mod_info.update_note_content(dumps(pages, indent=4, ensure_ascii=False))
            print("Mod信息按下载次数排序完成")
        except Exception as e:
            print(f"排序Mod信息时出错: {e}")