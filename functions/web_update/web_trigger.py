from functions.webFunc import Note
from functions.base.web_config import get_webnote
import re
from json import loads, dumps

class WebTrigger:
    """Web触发器，负责获取来自Web的插件和mod信息"""
    
    def __init__(self, ):
        self.addon_info = Note("addon_info", get_webnote('addon_info')[0])
        self.mod_info = Note("mod_info", get_webnote('mod_info')[0])

        # 取消初始化排序
        # sort_thread = Thread(target=self.sort_info_by_download_number)
        # sort_thread.start()

    def _get_note_info(self, note:Note, allow_refresh=False):
        note.fetch_note_info(allow_refresh)
        if not note.note_content.strip():
            return {}
        return loads(note.note_content)

    def get_note_info_mod(self, allow_refresh=False):
        return self._get_note_info(self.mod_info, allow_refresh)
    
    def get_note_info_addon(self, allow_refresh=False):
        return self._get_note_info(self.addon_info, allow_refresh)

    def get_addon_info(self, page: int = 0, allow_refresh=False):
        """获取插件信息"""
        return self._get_note_info(self.addon_info, allow_refresh)[page]

    def get_mod_info(self, page: int = 0, allow_refresh=False):
        """获取mod信息"""
        return self._get_note_info(self.mod_info, allow_refresh)[page]
    
    def _fetch_all(self, get_page, allow_refresh=False) -> list[dict]:
        """获取所有分页信息"""
        total_page = get_page(0, allow_refresh=allow_refresh)['total_page']
        info_list = []
        for page in range(1, total_page + 1):
            info_list.append(get_page(page))
        return info_list
    
    def fetch_all_addon_info(self, allow_refresh=False) -> list[dict]:
        """获取所有插件信息"""
        return self._fetch_all(self.get_addon_info, allow_refresh)
    
    def fetch_all_mod_info(self, allow_refresh=False) -> list[dict]:
        """获取所有mod信息"""
        return self._fetch_all(self.get_mod_info, allow_refresh)
    
    def _add_download_number(self, note: Note, name: str):
        """增加指定插件或mod的下载次数"""
        
        if not name:
            return

        # 确认笔记内容不为空
        # 处理确认合法的JSON字符串
        note_content = note.note_content
        note_content = re.sub(r'^[\s\ufeff]+|[\s\ufeff]+$', '', note_content)
        
        pages = loads(note_content)
        for page in pages[1:]:  # 跳过第一页的总页数信息
            for item in page:
                if item['name'] == name:
                    item['download_count'] += 1
                    # note.update_note_content(dumps(pages, indent=4, ensure_ascii=False))
                    break

        # 实现更新下载次数
        if note.note_id == "addon_info":
            note.note_content = dumps(pages, indent=4, ensure_ascii=False)
        elif note.note_id == "mod_info":
            note.note_content = dumps(pages, indent=4, ensure_ascii=False)

        # 进行统一排序
        self.sort_info_by_download_number()

    def add_download_number_addon(self, addon_name: str):
        """增加指定插件的下载次数"""
        self.fetch_all_addon_info(True)
        self._add_download_number(self.addon_info, addon_name)

    def add_download_number_mod(self, mod_name: str):
        """增加指定mod的下载次数"""
        self.fetch_all_mod_info(True)
        self._add_download_number(self.mod_info, mod_name)

    def sort_addon_info_by_download_number(self):
        """按插件下载次数排序"""
        # 排序插件信息
        try:
            pages = self.get_note_info_addon()
            for page in pages[1:]:  # 跳过第一页的总页数信息
                addons: list[dict] = page
                # 按下载次数降序排序，被禁用插件默认排序在最后 
                for addon in addons:
                    # 排序key的顺序
                    sorted(addon.keys(),reverse=True)
                addons.sort(key=lambda x: (
                    -x.get('is_new', False),  # True（1）排前面，False（0）排后面
                    x.get('disabled', False),  # False（0）排前面，True（1）排后面
                    -x.get('download_count', 0)  # 下载量从高到低
                ))
            # 更新排序后的插件信息
            self.addon_info.update_note_content(dumps(pages, indent=4, ensure_ascii=False))
            print("插件信息按下载次数排序完成")
        except Exception as e:
            print(f"排序插件信息时出错: {e}")
    
    def sort_info_by_download_number(self, kind: str = "all"):
        """按下载次数排序插件和mod信息"""

        # 排序mod信息
        try:
            pages = self.get_note_info_mod()
            mods: list[dict] = []
            for page in pages[1:]:  # 跳过第一页的总页数信息
                for m in page:
                    mods.append(m)
            # print(mods)
            # 按下载次数降序排序，被禁用mod默认排序在最后
            mods.sort(key=lambda x: (
                -x.get('is_new', False),  # True（1）排前面，False（0）排后面
                x.get('disabled', False),  # False（0）排前面，True（1）排后面
                -x.get('download_count', 0)  # 下载量从高到低
            ))

            # print('lists base:\n',dumps(mods, indent=4, ensure_ascii=False))

            new_pages = []
            page_count = 0
            # 五个五个分页，每五个放在一个list中
            total_page = len(mods) // 5 + (1 if len(mods) % 5 != 0 else 0)
            for i in range(total_page):
                page_count += 1
                new_pages.append(mods[i * 5:(i + 1) * 5])

            # 插入总页数和总mod数
            new_pages.insert(0, {'total_page': page_count, 'total_mods': len(mods)})

            # # 用 enumerate 安全地按索引分配内容，避免 index() 查找导致的错误
            # for idx, page in enumerate(pages[1:], start=0):
            #     if idx < len(new_pages):
            #         page = dumps(new_pages[idx], indent=4, ensure_ascii=False)


            # 更新排序后的mod信息
            # print('lists updated:\n',dumps(new_pages, indent=4, ensure_ascii=False))
            self.mod_info.update_note_content(dumps(new_pages, indent=4, ensure_ascii=False))
            print("Mod信息按下载次数排序完成")
        except Exception as e:
            print(f"排序Mod信息时出错: {e}")
