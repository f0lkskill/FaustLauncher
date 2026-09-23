"""偏移索引（HookIndex）：内存里的模型 + 本地缓存 + 云端笔记 ``FaustLauncher.hook_index``。

**这份 JSON 是整个 hook 子系统的契约**：桌面脚本（``test/damage_log.py``）、DLL、
成就模块、以及将来的其它插件都只认它的字段。所以：

- 顶层保留 ``cheat_damage`` 兼容块（与 ``web.lcta.top/cheat_damage.json`` 同字段名），
  这样 ``test/damage_log.py --api-url <笔记地址>`` 可以无缝切过来；
- ``hooks`` 给代码钩子用（``rva`` + ``prologue``，prologue 用于版本自检）；
- ``targets`` 给外部进程读内存用（多级指针链）；
- ``symbols`` 是"名字 → 偏移"的速查表（只保留 focus 范围，避免笔记过大）。

读写分两条链路（沿用 ``functions/webFunc/Webnote.py`` 的约定）：
读 ``/note/{key}``、写 ``/update/``；网络失败时回退本地
``cache/hook/hook_index.json``。成就模块只读本地缓存（不阻塞），
刷新由 ``updater``/CLI 负责。
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field

from . import paths as paths_mod
from . import targets as targets_mod

SCHEMA = 1
DEFAULT_NOTE_KEY = "FaustLauncher.hook_index"
CONFIG_NOTE_ID = "hook_index"          # config/web_config.json → webnote.hook_index
# 发布到云端时对符号表做的裁剪（本地缓存保留完整版）
MAX_PUBLISH_METHODS = 1500
MAX_PUBLISH_FIELDS = 800
# 笔记服务的 body 限制（实测 155 KB 的 JSON 会被 openresty 以 413 拒掉，
# 而且 POST 走表单编码后体积还会涨——所以发布前按预算逐级裁剪，最后才会丢符号表）。
NOTE_BUDGET_BYTES = 48_000
_SYMBOL_BUDGET_STEPS = ((MAX_PUBLISH_METHODS, MAX_PUBLISH_FIELDS),
                        (300, 200), (120, 80), (40, 30), (0, 0))


def note_key() -> str:
    """云端笔记名：优先 config/web_config.json → webnote.hook_index。"""
    try:
        from functions.base.web_config import get_webnote
        address, _pwd = get_webnote(CONFIG_NOTE_ID)
        if address:
            return str(address)
    except Exception:
        pass
    return DEFAULT_NOTE_KEY


@dataclass
class HookIndex:
    """偏移索引。"""

    schema: int = SCHEMA
    kind: str = DEFAULT_NOTE_KEY
    generated_at: str = ""
    game: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    dumper: dict = field(default_factory=dict)
    hooks: dict = field(default_factory=dict)
    targets: dict = field(default_factory=dict)
    symbols: dict = field(default_factory=dict)
    cheat_damage: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    # ---------------------------------------------------------------- 序列化
    def to_dict(self, compact: bool = False, caps: tuple[int, int] | None = None) -> dict:
        payload = {
            "schema": self.schema,
            "kind": self.kind,
            "generated_at": self.generated_at,
            "game": self.game,
            "metadata": self.metadata,
            "dumper": self.dumper,
            "cheat_damage": self.cheat_damage,
            "hooks": self.hooks,
            "targets": self.targets,
            "symbols": (_compact_symbols(self.symbols, self.hooks, caps)
                        if compact else self.symbols),
            "warnings": self.warnings,
        }
        return payload

    def to_json(self, compact: bool = False, indent: int = 1) -> str:
        return json.dumps(self.to_dict(compact=compact), ensure_ascii=False, indent=indent)

    def to_publish_dict(self, budget: int = NOTE_BUDGET_BYTES) -> dict:
        """生成适合写进云端笔记的载荷（按体积预算逐级裁掉符号表）。

        无论怎么裁，``hooks`` / ``targets`` / ``cheat_damage`` 都会完整保留。
        """
        payload = None
        for caps in _SYMBOL_BUDGET_STEPS:
            payload = self.to_dict(compact=True, caps=caps)
            size = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            if size <= budget:
                return payload
        return payload if payload is not None else self.to_dict(compact=True)

    def to_publish_json(self, budget: int = NOTE_BUDGET_BYTES, indent: int = 1) -> str:
        return json.dumps(self.to_publish_dict(budget), ensure_ascii=False, indent=indent)

    @staticmethod
    def from_json(text: str) -> "HookIndex | None":
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            return None
        if not isinstance(data, dict) or "hooks" not in data and "targets" not in data:
            # 允许"只有 targets"的极简手写笔记
            if not isinstance(data, dict):
                return None
        return HookIndex(
            schema=int(data.get("schema") or SCHEMA),
            kind=str(data.get("kind") or DEFAULT_NOTE_KEY),
            generated_at=str(data.get("generated_at") or ""),
            game=dict(data.get("game") or {}),
            metadata=dict(data.get("metadata") or {}),
            dumper=dict(data.get("dumper") or {}),
            hooks=dict(data.get("hooks") or {}),
            targets=dict(data.get("targets") or {}),
            symbols=dict(data.get("symbols") or {}),
            cheat_damage=dict(data.get("cheat_damage") or {}),
            warnings=list(data.get("warnings") or []),
        )

    # ---------------------------------------------------------------- 查询
    def fingerprint(self) -> tuple:
        """游戏指纹（判断索引是否匹配当前游戏文件）。"""
        return (int(self.game.get("gameassembly_size") or 0),
                str(self.game.get("gameassembly_sha256") or "").upper())

    def matches(self, size: int, sha256: str) -> bool:
        return self.fingerprint() == (int(size), str(sha256).upper())

    def target(self, key: str) -> dict:
        return dict(self.targets.get(key) or {})

    def hook(self, key: str) -> dict:
        return dict(self.hooks.get(key) or {})

    def symbol_offset(self, name: str) -> int | None:
        """按 ``类::字段``（或 ``类$$字段``）查字段偏移。"""
        fields = self.symbols.get("fields") or {}
        for candidate in _name_variants(name):
            value = fields.get(candidate)
            if isinstance(value, int):
                return value
            if isinstance(value, dict) and "offset" in value:
                return int(value["offset"])
        return None

    def symbol_rva(self, name: str) -> int | None:
        """按 ``类::方法``（或 ``类$$方法``）查方法 RVA。"""
        methods = self.symbols.get("methods") or {}
        for candidate in _name_variants(name):
            value = methods.get(candidate)
            if isinstance(value, int):
                return value
            if isinstance(value, dict) and "rva" in value:
                return int(value["rva"])
        return None

    def describe(self) -> str:
        size, sha = self.fingerprint()
        lines = [
            f"索引: {self.kind} schema={self.schema} 生成于 {self.generated_at}",
            f"游戏: size={size} sha256={sha[:16] or '(空)'}",
            f"元数据: {self.metadata.get('source', '?')} version={self.metadata.get('version', '?')}",
            f"钩子 {len(self.hooks)} 个: " + ", ".join(
                f"{k}(0x{int(v.get('rva') or 0):X})" for k, v in list(self.hooks.items())[:6]),
            f"数据链 {len(self.targets)} 条: " + ", ".join(self.targets.keys()),
            f"符号: {len(self.symbols.get('methods') or {})} 方法 / "
            f"{len(self.symbols.get('fields') or {})} 字段",
        ]
        if self.warnings:
            lines.append("警告: " + "；".join(self.warnings[:4]))
        return "\n".join(lines)


    def render_c_header(self, prefix: str = "LIMBUS_") -> str:
        """渲染 C 头文件（转发到模块级 ``render_c_header``）。"""
        return render_c_header(self, prefix=prefix)


def _name_variants(name: str) -> list[str]:
    raw = str(name or "").strip()
    out = [raw, raw.replace("$$", "::"), raw.replace("::", "$$")]
    if "." in raw:
        out.append(raw.split(".")[-1])
    seen = []
    for item in out:
        if item and item not in seen:
            seen.append(item)
    return seen


def _compact_symbols(symbols: dict, hooks: dict,
                     caps: tuple[int, int] | None = None) -> dict:
    """发布用裁剪：方法只留 rva，按“是否 hook 目标”优先排序。"""
    max_methods, max_fields = caps or (MAX_PUBLISH_METHODS, MAX_PUBLISH_FIELDS)
    methods = dict(symbols.get("methods") or {})
    fields = dict(symbols.get("fields") or {})
    if not max_methods and not max_fields:
        return {}
    wanted = set()
    for item in (hooks or {}).values():
        symbol = str(item.get("symbol") or "")
        if symbol:
            wanted.add(symbol)
            wanted.add(symbol.replace("::", "$$"))
    ordered = sorted(methods.items(), key=lambda kv: 0 if kv[0] in wanted else 1)
    trimmed_methods = {}
    for key, value in ordered[:max_methods]:
        trimmed_methods[key] = int(value.get("rva") or 0) if isinstance(value, dict) else int(value)
    trimmed_fields = {}
    for key, value in list(fields.items())[:max_fields]:
        trimmed_fields[key] = int(value.get("offset") or 0) if isinstance(value, dict) else int(value)
    return {"methods": trimmed_methods, "fields": trimmed_fields}


# --------------------------------------------------------------------------- 本地缓存


def marker_path() -> str:
    """已发布标记文件（避免每次启动都重复上传同一份内容）。"""
    return paths_mod.cache_path("published.json")


def payload_hash(payload: str) -> str:
    """发布载荷的 sha1（用于判断“本地这份有没有上传过”）。"""
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def load_marker() -> dict:
    try:
        with open(marker_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def mark_published(index: HookIndex) -> None:
    """记下“这份索引已经成功写进云端”。"""
    size, sha256 = index.fingerprint()
    data = {"size": size, "sha256": sha256,
            "payload_sha1": payload_hash(index.to_publish_json()),
            "at": paths_mod.now_iso()}
    try:
        with open(marker_path(), "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=1)
    except OSError:
        pass


def already_published(index: HookIndex) -> bool:
    """本地这份索引与云端是否已经完全一致（指纹 + 发布载荷哈希）。"""
    marker = load_marker()
    size, sha256 = index.fingerprint()
    return (int(marker.get("size") or 0) == size
            and str(marker.get("sha256") or "").upper() == sha256
            and marker.get("payload_sha1") == payload_hash(index.to_publish_json()))


def save_local(index: HookIndex) -> str:
    """写本地缓存（完整版，含 sig 等细节）。"""
    path = paths_mod.local_index_path()
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(index.to_json(compact=False))
    return path


def load_local() -> HookIndex | None:
    """读本地缓存；不存在/损坏返回 None。"""
    path = paths_mod.local_index_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return HookIndex.from_json(fh.read())
    except (OSError, ValueError):
        return None


# --------------------------------------------------------------------------- 云端笔记


def pull_cloud(allow_refresh: bool = False, on_log=None) -> HookIndex | None:
    """从云端笔记读取索引。"""
    log = on_log or (lambda _m: None)
    try:
        from functions.webFunc.Webnote import Note
    except Exception as exc:  # noqa: BLE001
        log(f"[hook_index] 云端笔记模块不可用: {exc}")
        return None
    key = note_key()
    note = Note(CONFIG_NOTE_ID, key)
    try:
        note.fetch_note_info(allow_refresh=allow_refresh)
    except Exception as exc:  # noqa: BLE001
        log(f"[hook_index] 读取云端笔记失败: {exc}")
        return None
    text = (note.note_content or "").strip()
    if not text:
        log(f"[hook_index] 云端笔记 {key} 为空（首次使用属正常）")
        return None
    index = HookIndex.from_json(text)
    if index is None:
        log(f"[hook_index] 云端笔记 {key} 不是合法 JSON")
        return None
    log(f"[hook_index] 已从云端读取 {key}（{len(text)} 字节）")
    return index


def push_cloud(index: HookIndex, on_log=None) -> dict:
    """把索引写回云端笔记（先按体积预算裁剪再上传）。"""
    log = on_log or (lambda _m: None)
    try:
        from functions.webFunc.Webnote import Note
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"云端笔记模块不可用: {exc}"}
    payload = index.to_publish_json()
    if len(payload.encode("utf-8")) > NOTE_BUDGET_BYTES:
        log(f"[hook_index] 发布体积 {len(payload)} 字节仍偏大（预算 {NOTE_BUDGET_BYTES}），"
            f"笔记服务可能以 413 拒绝")
    key = note_key()
    note = Note(CONFIG_NOTE_ID, key)
    try:
        result = note.update_note_content(payload)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    ok = int(result.get("status") or 0) == 1
    if ok:
        mark_published(index)
    log(f"[hook_index] 写回云端 {key}: {'成功' if ok else '失败 ' + str(result.get('error'))}"
        f"（{len(payload)} 字节, {result.get('method')}）")
    return {"ok": ok, "error": result.get("error"), "bytes": len(payload), "key": key}


def refresh_local_from_cloud(allow_refresh: bool = True, on_log=None) -> HookIndex | None:
    """从云端拉一次并落到本地缓存（供启动/定时任务用）。"""
    index = pull_cloud(allow_refresh=allow_refresh, on_log=on_log)
    if index is not None:
        save_local(index)
    return index


# --------------------------------------------------------------------------- 读取（热路径用）

_MEMO: HookIndex | None = None
_MEMO_SOURCE = ""


def clear_memo() -> None:
    global _MEMO, _MEMO_SOURCE
    _MEMO = None
    _MEMO_SOURCE = ""


def get_index(allow_cloud: bool = False, allow_refresh: bool = False,
              on_log=None) -> tuple[HookIndex | None, str]:
    """取索引（进程内记忆 → 本地缓存 → 可选云端）。返回 ``(index, 来源)``。

    默认**不联网**：成就监测这类热路径不应该等网络（云端刷新交给 updater / CLI）。
    """
    global _MEMO, _MEMO_SOURCE
    if _MEMO is not None:
        return _MEMO, _MEMO_SOURCE
    local = load_local()
    if local is not None:
        _MEMO, _MEMO_SOURCE = local, "cache"
        return _MEMO, _MEMO_SOURCE
    if allow_cloud:
        cloud = pull_cloud(allow_refresh=allow_refresh, on_log=on_log)
        if cloud is not None:
            save_local(cloud)
            _MEMO, _MEMO_SOURCE = cloud, "cloud"
            return _MEMO, _MEMO_SOURCE
    return None, ""


def get_target_chain(key: str, on_log=None) -> tuple[dict, str]:
    """取某条数据链的可用参数（索引优先，回退 targets.py 内置默认值）。

    返回 ``({"base_offset","offsets","value_type","module"}, 来源)``。
    """
    index, source = get_index()
    if index is not None:
        item = index.target(key)
        if item.get("base_offset") is not None and item.get("offsets"):
            return item, source or "index"
    default = next((t for t in targets_mod.CHAIN_TARGETS if t.key == key), None)
    if default is None:
        return {}, ""
    return default.as_dict(), "builtin"


def default_index(launcher_version: str = "") -> HookIndex:
    """内置默认索引（没有任何缓存/云端数据时的兜底）。"""
    index = HookIndex(generated_at=paths_mod.now_iso(),
                      game={"launcher_version": launcher_version},
                      metadata={"source": "builtin"})
    for chain in targets_mod.CHAIN_TARGETS:
        index.targets[chain.key] = chain.as_dict(source="builtin")
    return index


# --------------------------------------------------------------------------- C 头文件


def render_c_header(index: HookIndex, prefix: str = "LIMBUS_") -> str:
    """把索引渲染成 C 头文件（给自编译的注入 DLL 用）。

    只含"常量"：RVA、prologue、游戏指纹、版本；多级指针链用宏表达，
    使用者照着 ``#define`` 拼就是了。
    """
    lines = [
        "/* 由 FaustLauncher functions/hook 自动生成，请勿手改。",
        f" * 生成时间: {index.generated_at}",
        f" * 游戏指纹: size={index.game.get('gameassembly_size')} "
        f"sha256={str(index.game.get('gameassembly_sha256') or '')[:32]}...",
        " */",
        "#ifndef FAUST_HOOK_INDEX_H",
        "#define FAUST_HOOK_INDEX_H",
        "",
        "#include <stddef.h>",
        "#include <stdint.h>",
        "",
        f"#define {prefix}GA_SHA256        \"{index.game.get('gameassembly_sha256', '')}\"",
        f"#define {prefix}GA_SIZE          {int(index.game.get('gameassembly_size') or 0)}ULL",
        f"#define {prefix}METADATA_VERSION {int(index.metadata.get('version') or 0)}",
        "",
    ]
    for key, item in index.hooks.items():
        macro = f"{prefix}{key.upper()}"
        rva = int(item.get("rva") or 0)
        lines += [
            f"/* {item.get('description', '')} */",
            f"/* symbol: {item.get('symbol', '')} */",
            f"#define {macro}_RVA      {rva}ULL",
            f"#define {macro}_RVA_HEX  0x{rva:X}ULL",
        ]
        prologue = item.get("prologue") or ""
        if prologue:
            values = ", ".join(f"0x{byte:02X}" for byte in bytes.fromhex(prologue.replace(" ", "")))
            lines.append(f"static const unsigned char {macro}_PROLOGUE[16] = {{ {values} }};")
        lines.append("")
    for key, item in index.targets.items():
        macro = f"{prefix}{key.upper()}"
        offsets = ", ".join(f"0x{int(off):X}" for off in (item.get("offsets") or []))
        lines += [
            f"/* 数据链: {item.get('description', '')} */",
            f"#define {macro}_BASE_OFFSET  0x{int(item.get('base_offset') or 0):X}ULL",
            f"#define {macro}_OFFSETS      {{ {offsets} }}",
            f"#define {macro}_OFFSET_COUNT {len(item.get('offsets') or [])}",
            "",
        ]
    lines.append("#endif /* FAUST_HOOK_INDEX_H */")
    return "\n".join(lines)
