"""云端公告读取与本地已读状态管理。

公告正文保存在云端笔记中，已读 ID 单独写入用户 APPDATA 目录，避免修改
登录态或启动器设置文件。
"""

from __future__ import annotations

import json
import os
import threading

from functions.base.common import get_launcher_user_dir, md_to_html
from functions.base.common.json_io import try_read_json, write_json
from functions.base.web_config import get_webnote
from functions.webFunc.Webnote import Note

_READ_FILE_NAME = "notice_reads.json"
_READ_LOCK = threading.RLock()
_MAX_READ_IDS = 10000


def notice_reads_file() -> str:
    """返回公告已读记录文件路径。"""
    return os.path.join(get_launcher_user_dir(), _READ_FILE_NAME)


def _load_read_ids() -> set[str]:
    data = try_read_json(notice_reads_file(), [])
    values = data.get("ids") if isinstance(data, dict) else data
    if not isinstance(values, list):
        return set()

    result: set[str] = set()
    for raw in values:
        if not isinstance(raw, str):
            continue
        notice_id = raw.strip()
        if notice_id and len(notice_id) <= 256:
            result.add(notice_id)
        if len(result) >= _MAX_READ_IDS:
            break
    return result


def _save_read_ids(read_ids: set[str]) -> None:
    path = notice_reads_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_json(path, sorted(read_ids), indent=2, fsync=True)


class AppNoticeManager:
    """读取并规范化云端公告，同时维护本地已读状态。"""

    def __init__(self, base_id: str = "notice") -> None:
        self.notice_note = Note(
            base_id, get_webnote(base_id)[0])
        self.notice_data: list[dict] = []
        self.last_load_error = ""

        self.load_data()

    @staticmethod
    def _normalize(data) -> list[dict]:
        if not isinstance(data, list):
            return []

        notices: list[dict] = []
        seen: set[str] = set()
        for raw in data:
            if not isinstance(raw, dict):
                continue
            notice_id = str(raw.get("id") or "").strip()
            title = str(raw.get("title") or "").strip()
            if not notice_id or not title or notice_id in seen:
                continue
            seen.add(notice_id)
            notices.append({
                "id": notice_id,
                "title": title,
                "content": str(raw.get("content") or ""),
                "timeline": str(raw.get("timeline") or "").strip(),
            })
        return notices

    def load_data(self, allow_refresh: bool = False) -> None:
        """载入公告数据。

        云端不可用、JSON 损坏或字段不符合协议时保留空公告列表，不影响
        启动器其他功能。

        Args:
            allow_refresh: 是否跳过本地短期缓存并重新请求云端。
        """
        self.last_load_error = ""
        try:
            self.notice_note.fetch_note_info(bool(allow_refresh))
            content = str(self.notice_note.note_content or "").lstrip("\ufeff")
            if not content.strip():
                self.notice_data = []
                self.last_load_error = self.notice_note.last_fetch_error
                return
            parsed = json.loads(content)
            self.notice_data = self._normalize(parsed)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self.notice_data = []
            self.last_load_error = f"{type(exc).__name__}: {exc}"
            print(f"[Notice] 公告数据解析失败: {self.last_load_error}")
        except Exception as exc:  # noqa: BLE001 - 云端异常不能中断启动
            self.notice_data = []
            self.last_load_error = f"{type(exc).__name__}: {exc}"
            print(f"[Notice] 公告数据读取失败: {self.last_load_error}")

    def get_notices(self) -> list[dict]:
        """返回供前端渲染的公告列表，保留服务端顺序。"""
        with _READ_LOCK:
            read_ids = _load_read_ids()
        result = []
        for item in self.notice_data:
            result.append({
                **item,
                "html": md_to_html(item["content"]),
                "is_read": item["id"] in read_ids,
            })
        return result

    def unread_count(self) -> int:
        with _READ_LOCK:
            read_ids = _load_read_ids()
        return sum(1 for item in self.notice_data if item["id"] not in read_ids)

    def mark_read(self, notice_id: str) -> bool:
        """将一个已展示的公告 ID 持久化为已读。"""
        clean_id = str(notice_id or "").strip()
        if not clean_id or not any(
            item["id"] == clean_id for item in self.notice_data
        ):
            return False
        try:
            with _READ_LOCK:
                read_ids = _load_read_ids()
                if clean_id not in read_ids:
                    read_ids.add(clean_id)
                    _save_read_ids(read_ids)
            return True
        except Exception as exc:  # noqa: BLE001 - 已读记录失败不应打断阅读
            print(f"[Notice] 保存已读状态失败: {type(exc).__name__}: {exc}")
            return False

    def get_newest_notice(self) -> dict | None:
        """返回最新公告，保留给旧调用方使用。

        Returns:
            最新公告；没有有效公告时返回 ``None``。
        """
        if not self.notice_data:
            print("[Notice] 公告数据为空")
            return None
        return dict(self.notice_data[0])
