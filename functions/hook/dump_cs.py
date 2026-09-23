"""dump.cs 解析器 — 从 Il2CppDumper 的输出里取出我们真正需要的符号。

``dump.cs`` 是 Il2CppDumper 生成的 C# 伪代码，单个文件 200 万行 / 80 MB 级别。
本解析器的策略是**一边流式扫描一边过滤**：只有"声明行 / RVA 注释行 /
带偏移的字段行"三种行会被正则处理，其余直接跳过，因此全量扫描只要几十秒，
且内存占用与文件大小无关。

行格式（实测 Il2CppDumper 6.7.x）::

    // Image 0: Assembly-CSharp.dll - 0

    // Namespace:            ← 空命名空间（BattleUnitModel 就是这种）
    public abstract class BattleUnitModel : CombatUnitModel // TypeDefIndex: 19508
    {
    	// Fields
    	public static readonly float _ATK_RESIST_MAX; // 0x0        ← 静态字段（静态区偏移）
    	protected int _instanceID; // 0x60                          ← 实例字段（对象内偏移）

    	// Methods
    	// RVA: 0x9587C0 Offset: 0x956DC0 VA: 0x1809587C0 Slot: 196
    	public virtual float GetTakeAttackDmgMultiplier(BattleUnitModel unit, ...) { }
    }

保留规则（决定 JSON 大小）：只保留

- ``wanted`` 里显式点名的符号（hook 目标 / 指针链涉及的类字段）
- 声明类型命中 ``focus`` 模式（如 ``BattleUnitModel``、``Enkephalin``）的符号

其余只统计数量，不进结果。
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field

TYPE_RE = re.compile(
    r"^\s*(?:\[[^\]]*\]\s*)*"
    r"(?:public|private|protected|internal|sealed|abstract|static|partial|\s)*"
    r"(?P<kind>class|struct|interface|enum)\s+(?P<name>[A-Za-z_0-9`<>.,\[\]@]+)")
FIELD_RE = re.compile(
    r"^(?P<indent>\s*)(?P<decl>[^;]+?);\s*//\s*0x(?P<off>[0-9A-Fa-f]+)\s*$")
RVA_RE = re.compile(
    r"^\s*//\s*RVA:\s*0x(?P<rva>[0-9A-Fa-f]+)\s+Offset:\s*0x(?P<offset>[0-9A-Fa-f]+)"
    r"\s+VA:\s*0x(?P<va>[0-9A-Fa-f]+)(?:\s+Slot:\s*(?P<slot>\d+))?")
NAMESPACE_PREFIX = "// Namespace: "
_MAX_SIG = 220
_MAX_ALT_RVAS = 8


@dataclass
class SymbolIndex:
    """从 dump.cs 提取出的符号表（体积受 focus 控制）。"""

    types: dict[str, str] = field(default_factory=dict)            # 全名 → kind
    methods: dict[str, dict] = field(default_factory=dict)         # 全名 → {rva, offset, va, slot, sig}
    fields: dict[str, dict] = field(default_factory=dict)          # 全名 → {offset, static, type}
    method_aliases: dict[str, str] = field(default_factory=dict)   # Class$$Method → 全名
    stats: dict = field(default_factory=dict)
    dump_path: str = ""
    dump_size: int = 0
    dump_mtime: float = 0.0

    # ---------------------------------------------------------------- 查询
    def find_method(self, name: str) -> dict | None:
        """按多种写法查方法：``Ns.Class::M`` / ``Class::M`` / ``Ns.Class$$M`` / ``Class$$M``。"""
        for key in self._candidates(name, sep="::"):
            item = self.methods.get(key)
            if item:
                return {"key": key, **item}
        alias = self.method_aliases.get(_normalize_alias(name))
        if alias:
            item = self.methods.get(alias)
            if item:
                return {"key": alias, **item}
        # 后缀匹配（同名类在多命名空间时兜底）
        bare = name.split("::")[-1].split("$$")[-1]
        short = name.replace("$$", "::")
        hits = [(k, v) for k, v in self.methods.items()
                if k.endswith("::" + bare) or k == short]
        if len(hits) == 1:
            return {"key": hits[0][0], **hits[0][1]}
        return None

    def find_field(self, class_name: str, field_name: str) -> dict | None:
        """查字段：优先 ``类::字段``，再退回"只在某个类里唯一"的匹配。"""
        if not field_name:
            return None
        for key in self._candidates(f"{class_name}::{field_name}" if class_name else field_name,
                                    sep="::"):
            item = self.fields.get(key)
            if item:
                return {"key": key, **item}
        suffix = "::" + field_name
        hits = [(k, v) for k, v in self.fields.items()
                if k.endswith(suffix) and (not class_name or k.split("::")[0].endswith(class_name))]
        if len(hits) == 1:
            return {"key": hits[0][0], **hits[0][1]}
        return None

    def field_offset(self, class_name: str, field_name: str) -> int | None:
        item = self.find_field(class_name, field_name)
        return item.get("offset") if item else None

    def fields_of(self, class_name: str) -> dict[str, dict]:
        """某类的全部字段（只含被保留的）。"""
        out = {}
        for key, item in self.fields.items():
            owner, _, name = key.partition("::")
            if owner == class_name or owner.endswith("." + class_name):
                out[name] = item
        return out

    @staticmethod
    def _candidates(name: str, sep: str = "::") -> list[str]:
        """名字 → 可能的键列表（去重保序）。"""
        raw = str(name or "").strip().replace("$$", sep)
        out = []
        for candidate in (raw, raw.split(".")[-1] if "." in raw else raw):
            if candidate and candidate not in out:
                out.append(candidate)
        return out


def _normalize_alias(name: str) -> str:
    return str(name or "").strip().replace("::", "$$")


def _split_decl(decl: str) -> tuple[str, str]:
    """字段/方法声明 → (类型, 名字)。"""
    text = decl.strip()
    while text.startswith(("public ", "private ", "protected ", "internal ",
                           "static ", "readonly ", "const ", "volatile ", "unsafe ",
                           "extern ", "sealed ", "override ", "virtual ", "abstract ",
                           "new ", "fixed ", "ref ")):
        text = text.split(" ", 1)[1].strip() if " " in text else text
    if " operator " in text:
        left, right = text.split(" operator ", 1)
        return left.strip(), "operator" + right.split("(")[0].strip()
    head = text.split("(", 1)[0]
    head = head.replace("[]", "").replace("&&", "").replace("**", "").strip()
    parts = head.split()
    if len(parts) < 2:
        name = parts[0] if parts else ""
        return name, name.split("<")[0].strip("!")
    return " ".join(parts[:-1]), parts[-1].split("<")[0].strip("!")


def parse_dump_cs(path: str, focus=(), wanted=(), on_log=None, on_progress=None) -> SymbolIndex:
    """流式解析 dump.cs。

    参数：
        focus:      类名/命名空间包含这些子串（或 fnmatch 模式）时保留其符号
        wanted:     必须保留的符号名（``类::方法`` / ``类::字段`` / ``类$$方法``）
        on_log(msg) 日志回调
        on_progress(done_bytes, total_bytes) 进度回调
    """
    import fnmatch

    log = on_log or (lambda _m: None)
    index = SymbolIndex(dump_path=path)
    wanted_set = {w for w in (wanted or []) if w}
    wanted_bare = {w.split("::")[-1].split("$$")[-1] for w in wanted_set}
    focus_patterns = [str(f) for f in (focus or []) if str(f)]

    def keep_type(full_name: str, bare: str) -> bool:
        if not focus_patterns:
            return False
        for pattern in focus_patterns:
            if any(ch in pattern for ch in "*?["):
                if fnmatch.fnmatch(bare, pattern) or fnmatch.fnmatch(full_name, pattern):
                    return True
            elif pattern in bare or pattern in full_name:
                return True
        return False

    def keep_symbol(full_name: str, bare_name: str, owner: str) -> bool:
        if bare_name in wanted_bare or full_name in wanted_set:
            return True
        alias = _normalize_alias(full_name)
        return alias in wanted_set

    total = 0
    try:
        total = os.path.getsize(path)
    except OSError:
        pass

    ns = ""
    cur_type = ""
    cur_full = ""
    cur_keep = False
    pending_rva: dict | None = None
    n_types = n_methods = n_fields = 0
    kept_methods = kept_fields = 0
    started = time.time()
    done = 0

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            done += len(line)
            if on_progress and (n_types + n_methods + n_fields) % 5000 == 0:
                on_progress(done, total)

            if line.startswith(NAMESPACE_PREFIX):
                ns = line[len(NAMESPACE_PREFIX):].strip()
                continue

            if "// RVA:" in line:
                match = RVA_RE.match(line)
                pending_rva = match.groupdict() if match else None
                continue

            if pending_rva is not None:
                # RVA 注释的下一行就是签名；空行/注释行则丢弃这次 pending
                stripped = line.strip()
                if stripped and not stripped.startswith("//") and "(" in stripped:
                    _, name = _split_decl(stripped.split("(", 1)[0])
                    full = f"{cur_full}::{name}" if cur_full else name
                    n_methods += 1
                    if cur_keep or keep_symbol(full, name, cur_full):
                        kept_methods += 1
                        item = {
                            "rva": _to_int(pending_rva.get("rva")),
                            "offset": _to_int(pending_rva.get("offset")),
                            "va": _to_int(pending_rva.get("va")),
                            "slot": _to_int(pending_rva.get("slot"), 10) if pending_rva.get("slot") else None,
                            "sig": stripped[:_MAX_SIG],
                        }
                        _store_symbol(index, full, cur_type, name, item, is_method=True)
                pending_rva = None
                continue

            if "// 0x" in line:
                match = FIELD_RE.match(line)
                if match:
                    n_fields += 1
                    decl = match.group("decl")
                    _, name = _split_decl(decl)
                    full = f"{cur_full}::{name}" if cur_full else name
                    if cur_keep or keep_symbol(full, name, cur_full):
                        kept_fields += 1
                        _store_symbol(
                            index, full, cur_type, name,
                            {"offset": int(match.group("off"), 16),
                             "static": " static " in f" {decl.strip()} ",
                             "type": _split_decl(decl)[0]},
                            is_method=False)
                continue

            if (" class " in line or " struct " in line or " enum " in line
                    or " interface " in line or line.startswith(("public ", "internal ",
                                                                 "private ", "protected "))):
                match = TYPE_RE.match(line)
                if match:
                    n_types += 1
                    cur_type = match.group("name")
                    cur_full = f"{ns}.{cur_type}" if ns else cur_type
                    cur_keep = keep_type(cur_full, cur_type)
                    if cur_keep:
                        index.types[cur_full] = match.group("kind")

    index.stats = {
        "dump_size": total,
        "types_scanned": n_types,
        "methods_scanned": n_methods,
        "fields_scanned": n_fields,
        "methods_kept": kept_methods,
        "fields_kept": kept_fields,
        "types_kept": len(index.types),
        "elapsed_sec": round(time.time() - started, 1),
    }
    log(f"[dump.cs] 扫描完成: {n_types} 类型 / {n_methods} 方法 / {n_fields} 字段，"
        f"保留 {index.stats['types_kept']} 类型 / {kept_methods} 方法 / {kept_fields} 字段，"
        f"耗时 {index.stats['elapsed_sec']}s")
    index.dump_size = total
    try:
        index.dump_mtime = os.path.getmtime(path)
    except OSError:
        index.dump_mtime = 0.0
    return index


def _to_int(text, base: int = 16) -> int:
    try:
        return int(str(text), base)
    except (TypeError, ValueError):
        return 0


def _store_symbol(index: SymbolIndex, full: str, owner: str, name: str,
                  item: dict, is_method: bool) -> None:
    """写入符号表 + 生成 ``Class$$Method`` 兼容别名。"""
    table = index.methods if is_method else index.fields
    existing = table.get(full)
    if existing is not None:
        # 重载：主条目保留第一个，其余 RVA 收进 alt_rvas（上限 8 个）
        if is_method:
            alt = existing.setdefault("alt_rvas", [])
            if len(alt) < _MAX_ALT_RVAS and item.get("rva") not in alt:
                alt.append(item.get("rva"))
            existing["overloads"] = int(existing.get("overloads", 1)) + 1
        return
    table[full] = item
    if is_method:
        index.method_aliases.setdefault(f"{owner.split('.')[-1]}$${name}", full)
        index.method_aliases.setdefault(_normalize_alias(full), full)


def load_or_parse(dump_path: str, focus=(), wanted=(), on_log=None) -> SymbolIndex:
    """解析 dump.cs（带简单的进程内记忆，避免同一次运行里重复扫 80 MB）。"""
    key = (dump_path, tuple(sorted(focus or ())), tuple(sorted(wanted or ())))
    cached = _PARSE_CACHE.get(key)
    if cached is not None:
        return cached
    index = parse_dump_cs(dump_path, focus=focus, wanted=wanted, on_log=on_log)
    _PARSE_CACHE.clear()
    _PARSE_CACHE[key] = index
    return index


_PARSE_CACHE: dict = {}


def main() -> int:  # 简易自检: python -m functions.hook.dump_cs <dump.cs>
    import sys

    if len(sys.argv) < 2:
        print("用法: python -m functions.hook.dump_cs <dump.cs>")
        return 1
    index = parse_dump_cs(sys.argv[1], focus=["BattleUnitModel"],
                         wanted=["BattleUnitModel::GetOpponentFaction"], on_log=print)
    print("stats:", index.stats)
    print("method:", index.find_method("BattleUnitModel$$GetTakeAttackDmgMultiplier"))
    print("field:", index.find_field("BattleUnitModel", "_instanceID"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
