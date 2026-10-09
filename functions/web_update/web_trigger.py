from functions.webFunc import Note
from functions.base.web_config import get_webnote
import re
from json import loads, dumps

class WebTrigger:
    """Web触发器，负责获取来自Web的插件和mod信息"""
    
    def __init__(self):
        """初始化 WebTrigger 实例"""
        self.addon_info = Note("addon_info", get_webnote('addon_info')[0])
        self.mod_info = Note("mod_info", get_webnote('mod_info')[0])

    def _get_note_info(self, note:Note, allow_refresh=False):
        """获取指定笔记的分页信息

        Args:
            note (Note): 笔记实例
        Args:
            allow_refresh (bool, optional): 是否允许刷新，默认值为 False

        Returns:
            _type_: _description_
        """
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
        """获取所有分页信息

        Args:
            get_page (_type_): 获取指定分页信息的函数
        Args:
            allow_refresh (bool, optional): 是否允许刷新，默认值为 False

        Returns:
            list[dict]: 所有分页信息的列表
        Args:
            allow_refresh (bool, optional): 是否允许刷新，默认值为 False
        """
        
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
    
    # 注: 原来的 ``_add_download_number``（下载整份笔记 → 本地 +1 → 重排 → 整份写回）
    # 已随"取消 mod/插件写回机制"一起删除。下载次数现在完全由服务端维护，
    # 客户端只调 ``POST /api/download`` 报一次（见下面两个方法），不再回写笔记。

    def add_download_number_addon(self, addon_name: str):
        """插件下载次数 +1 —— **交给服务端**（``POST /api/download``）。

        旧做法是"下载整份插件数据库 → 本地 +1 → 重新排序 → 整份写回 ``/update/``"：
        多个客户端并发必然互相覆盖（丢数据的经典模式）。服务端那套在锁内完成
        +1 → 重排 → 重新分页 → 原子写回，客户端只报"谁被下载了"就够。
        """
        self._report_download(addon_name, "addon")

    def add_download_number_mod(self, mod_name: str):
        """mod 下载次数 +1 —— 同上，交给服务端，客户端不再写回笔记。"""
        self._report_download(mod_name, "mod")

    @staticmethod
    def _report_download(name: str, kind: str) -> dict:
        """把"谁被下载了"报给服务端；失败只打日志（下载本身已经完成了）。"""
        clean = str(name or "").strip()
        if not clean:
            return {"ok": False, "error": "名字为空"}
        try:
            from functions.base import user_api
            result = user_api.report_download(clean, kind)
        except Exception as exc:  # noqa: BLE001
            print(f"[云端] 下载上报失败({kind}:{clean}): {type(exc).__name__}: {exc}")
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if result.get("ok"):
            # user_api._request() 返回信封 {"ok","data",...}，下载次数/名次在 data 里
            payload = result.get("data") if isinstance(result.get("data"), dict) else {}
            print(f"[云端] {kind}「{clean}」下载次数 +1 → "
                  f"{payload.get('download_count')}（第 {payload.get('rank', '?')} 名）")
        else:
            print(f"[云端] {kind}「{clean}」下载上报失败: {result.get('error')}")
        return result

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

    def sort_mod_info_by_download_number(self):
        """按mod下载次数排序"""
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

            # 更新排序后的mod信息
            self.mod_info.update_note_content(dumps(new_pages, indent=4, ensure_ascii=False))
            print("Mod信息按下载次数排序完成")
        except Exception as e:
            print(f"排序Mod信息时出错: {e}")
    
    def sort_info_by_download_number(self, mode: str = "all"):
        """按下载次数排序插件和mod信息"""
        if mode == "all":
            self.sort_addon_info_by_download_number()
            self.sort_mod_info_by_download_number()
        elif mode == "addon":
            self.sort_addon_info_by_download_number()
        elif mode == "mod":
            self.sort_mod_info_by_download_number()
        else:
            raise ValueError(f"未知的排序模式: {mode}")