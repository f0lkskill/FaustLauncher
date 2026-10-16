from functions.webFunc import Note
from functions.base.web_config import get_webnote
import re
from json import loads, dumps

class WebTrigger:
    
    def __init__(self):
        self.addon_info = Note("addon_info", get_webnote('addon_info')[0])
        self.mod_info = Note("mod_info", get_webnote('mod_info')[0])

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
        return self._get_note_info(self.addon_info, allow_refresh)[page]

    def get_mod_info(self, page: int = 0, allow_refresh=False):
        return self._get_note_info(self.mod_info, allow_refresh)[page]
    
    def _fetch_all(self, get_page, allow_refresh=False) -> list[dict]:
        
        total_page = get_page(0, allow_refresh=allow_refresh)['total_page']
        info_list = []
        for page in range(1, total_page + 1):
            info_list.append(get_page(page))
        return info_list
    
    def fetch_all_addon_info(self, allow_refresh=False) -> list[dict]:
        return self._fetch_all(self.get_addon_info, allow_refresh)
    
    def fetch_all_mod_info(self, allow_refresh=False) -> list[dict]:
        return self._fetch_all(self.get_mod_info, allow_refresh)
    
    def add_download_number_addon(self, addon_name: str):
        self._report_download(addon_name, "addon")

    def add_download_number_mod(self, mod_name: str):
        self._report_download(mod_name, "mod")

    @staticmethod
    def _report_download(name: str, kind: str) -> dict:
        clean = str(name or "").strip()
        if not clean:
            return {"ok": False, "error": "名字为空"}
        try:
            from functions.base import user_api
            result = user_api.report_download(clean, kind)
        except Exception as exc:  # noqa: BLE001
            print(f"[Cloud] 下载上报失败({kind}:{clean}): {type(exc).__name__}: {exc}")
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if result.get("ok"):
            payload = result.get("data") if isinstance(result.get("data"), dict) else {}
            print(f"[Cloud] {kind}「{clean}」下载次数 +1 → "
                  f"{payload.get('download_count')}（第 {payload.get('rank', '?')} 名）")
        else:
            print(f"[Cloud] {kind}「{clean}」下载上报失败: {result.get('error')}")
        return result

    def sort_addon_info_by_download_number(self):
        try:
            pages = self.get_note_info_addon()
            for page in pages[1:]:
                addons: list[dict] = page
                for addon in addons:
                    sorted(addon.keys(),reverse=True)
                addons.sort(key=lambda x: (
                    -x.get('is_new', False),
                    x.get('disabled', False),
                    -x.get('download_count', 0)
                ))
            self.addon_info.update_note_content(dumps(pages, indent=4, ensure_ascii=False))
            print("插件信息按下载次数排序完成")
        except Exception as e:
            print(f"排序插件信息时出错: {e}")

    def sort_mod_info_by_download_number(self):
        try:
            pages = self.get_note_info_mod()
            mods: list[dict] = []
            for page in pages[1:]:
                for m in page:
                    mods.append(m)
            mods.sort(key=lambda x: (
                -x.get('is_new', False),
                x.get('disabled', False),
                -x.get('download_count', 0)
            ))

            new_pages = []
            page_count = 0
            total_page = len(mods) // 5 + (1 if len(mods) % 5 != 0 else 0)
            for i in range(total_page):
                page_count += 1
                new_pages.append(mods[i * 5:(i + 1) * 5])

            new_pages.insert(0, {'total_page': page_count, 'total_mods': len(mods)})

            self.mod_info.update_note_content(dumps(new_pages, indent=4, ensure_ascii=False))
            print("Mod信息按下载次数排序完成")
        except Exception as e:
            print(f"排序Mod信息时出错: {e}")
    
    def sort_info_by_download_number(self, mode: str = "all"):
        if mode == "all":
            self.sort_addon_info_by_download_number()
            self.sort_mod_info_by_download_number()
        elif mode == "addon":
            self.sort_addon_info_by_download_number()
        elif mode == "mod":
            self.sort_mod_info_by_download_number()
        else:
            raise ValueError(f"未知的排序模式: {mode}")
