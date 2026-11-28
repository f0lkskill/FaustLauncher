"""云端公告读取与本地已读状态管理。

公告正文保存在云端笔记里（列表 JSON，每项含 id/title/content/timeline）；
已读 ID 单独写到 ``%APPDATA%/FaustLauncher/user/notice_reads.json``，避免
改动登录态或启动器设置文件。

读取分成两步：:class:`AppNoticeManager` 负责拉取并规范化云端列表，再和本地
已读表做差集得到未读数。云端失败或 JSON 损坏时宁可展示空公告，也不影响
启动器其他功能；同理，只有确认内容来自云端时才会清理本地已过期的已读 ID。
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
    """从用户目录读已读 ID，兼容旧的裸数组格式和新的 ``{"ids": [...]}``。

    非字符串、超长 ID 会被丢掉；最多保留 :data:`_MAX_READ_IDS` 条，
    防止损坏文件把内存撑爆。

    Returns:
        set[str]: 合法的已读公告 ID 集合。
    """
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
    """把已读 ID 排序后写回用户目录（原子写 + fsync）。

    Args:
        read_ids: 要持久化的 ID 集合；调用方负责先加/删再做差集。
    """
    path = notice_reads_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_json(path, sorted(read_ids), indent=2, fsync=True)


class AppNoticeManager:
    """读取并规范化云端公告，同时维护本地已读状态。"""

    def __init__(self, base_id: str = "notice") -> None:
        """构造云端笔记客户端并立即载入一次公告列表。

        Args:
            base_id: 云端笔记名/内嵌配置键，默认 ``notice``。
        """
        self.notice_note = Note(
            base_id, get_webnote(base_id)[0])
        self.notice_data: list[dict] = []
        self.last_load_error = ""
        # 最近一次内容是否确实来自云端（而不是断网时的本地缓存）。只有在
        # 云端内容有效时才允许清理本地已读 ID，见 _prune_read_ids。
        self._cloud_fresh = False

        self.load_data()

    @staticmethod
    def _normalize(data) -> list[dict]:
        """把云端 JSON 数组规整成公告列表，丢弃缺 id/title 或重复的项。"""
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
        self._cloud_fresh = False
        try:
            self.notice_note.fetch_note_info(bool(allow_refresh))
            content = str(self.notice_note.note_content or "").lstrip("\ufeff")
            if not content.strip():
                self.notice_data = []
                self.last_load_error = self.notice_note.last_fetch_error
                return
            parsed = json.loads(content)
            self.notice_data = self._normalize(parsed)
            # 缓存兜底拿到的旧列表不代表“云端现在有什么”，不能据此清理。
            self._cloud_fresh = not getattr(self.notice_note, "used_cache", False)
            self._prune_read_ids()
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self.notice_data = []
            self.last_load_error = f"{type(exc).__name__}: {exc}"
            print(f"[Notice] 公告数据解析失败: {self.last_load_error}")
        except Exception as exc:  # noqa: BLE001 - 云端异常不能中断启动
            self.notice_data = []
            self.last_load_error = f"{type(exc).__name__}: {exc}"
            print(f"[Notice] 公告数据读取失败: {self.last_load_error}")

    def _prune_read_ids(self) -> None:
        """删除本地已读记录里云端已经不存在的历史公告 ID。

        只在云端内容**成功解析且不是本地缓存兜底**时调用：网络失败或 JSON
        损坏时绝不能清理，否则一次断网就会把用户积攒的已读状态抹掉。
        云端列表为空（公告全部撤下）属于有效结果，此时会清空已读记录。
        """
        if not self._cloud_fresh:
            return
        cloud_ids = {item["id"] for item in self.notice_data}
        try:
            with _READ_LOCK:
                read_ids = _load_read_ids()
                stale = read_ids - cloud_ids
                if not stale:
                    return
                _save_read_ids(read_ids & cloud_ids)
            print(f"[Notice] 清理 {len(stale)} 个云端已不存在的已读公告 ID")
        except Exception as exc:  # noqa: BLE001 - 清理失败不应影响公告展示
            print(f"[Notice] 清理已读记录失败: {type(exc).__name__}: {exc}")

    def get_notices(self) -> list[dict]:
        """返回供前端渲染的公告列表，保留服务端顺序。

        Returns:
            list[dict]: 每项在原字段基础上追加 ``html``（Markdown 渲染结果）
            和 ``is_read``（本地已读状态）。
        """
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
        """当前公告里未读的条数；列表为空时返回 0。"""
        with _READ_LOCK:
            read_ids = _load_read_ids()
        return sum(1 for item in self.notice_data if item["id"] not in read_ids)

    def mark_read(self, notice_id: str) -> bool:
        """将一个已展示的公告 ID 持久化为已读。

        Args:
            notice_id: 公告 ID；不在当前云端列表里的 ID 不会被记录。

        Returns:
            bool: 是否成功写入（已是已读也返回 True）。
        """
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
