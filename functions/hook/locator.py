
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass

from . import pe as pe_mod
from .memory import ProcessMemoryReader
from .targets import ChainTarget

IL2CPP_OBJECT_KLASS = 0x00
IL2CPP_CLASS_IMAGE = 0x00
IL2CPP_CLASS_NAME = 0x10
IL2CPP_CLASS_NAMESPACE = 0x18

_MAX_NAME_LEN = 96
_MAX_CANDIDATES = 200

@dataclass
class Candidate:

    mode: str
    slot_rva: int
    slot_address: int
    class_name: str
    namespace: str = ""
    value: int | None = None
    step_classes: tuple[str, ...] = ()
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "slot_rva": self.slot_rva,
            "slot_address": self.slot_address,
            "root_class": self.class_name,
            "namespace": self.namespace,
            "value": self.value,
            "step_classes": list(self.step_classes),
            "note": self.note,
        }

class _Ranges:

    def __init__(self, ranges) -> None:
        self._starts: list[int] = []
        self._ends: list[int] = []
        for start, size in sorted(ranges):
            self._starts.append(start)
            self._ends.append(start + size)

    def __contains__(self, value: int) -> bool:
        index = bisect_right(self._starts, value) - 1
        return index >= 0 and value < self._ends[index]

    def __bool__(self) -> bool:
        return bool(self._starts)

def _is_plausible_name(text: str) -> bool:
    if not text or len(text) > _MAX_NAME_LEN - 1:
        return False
    if not (text[0].isalpha() or text[0] in "_<"):
        return False
    return all(ch.isalnum() or ch in "_.<>`$@+=-" for ch in text)

def read_class_name(reader: ProcessMemoryReader, class_ptr: int) -> tuple[str, str]:
    name_ptr = reader.read_u64(class_ptr + IL2CPP_CLASS_NAME)
    name = reader.read_cstring(name_ptr, _MAX_NAME_LEN) if name_ptr else ""
    ns_ptr = reader.read_u64(class_ptr + IL2CPP_CLASS_NAMESPACE)
    ns = reader.read_cstring(ns_ptr, _MAX_NAME_LEN) if ns_ptr else ""
    return (name if _is_plausible_name(name) else ""), (ns if _is_plausible_name(ns) else "")

def read_object_class(reader: ProcessMemoryReader, object_ptr: int) -> tuple[str, str]:
    klass = reader.read_u64(object_ptr + IL2CPP_OBJECT_KLASS)
    if not klass:
        return "", ""
    return read_class_name(reader, klass)

def walk_chain(reader: ProcessMemoryReader, start_address: int, offsets,
               value_type: str = "int32") -> tuple[int | float | None, list[int], list[str]]:
    address = int(start_address)
    pointers: list[int] = []
    classes: list[str] = []
    for offset in offsets:
        pointer = reader.read_u64(address)
        if not pointer:
            return None, pointers, classes
        address = pointer + int(offset)
        pointers.append(address)
        name, _ns = read_object_class(reader, pointer)
        classes.append(name)
    return reader.read_value(address, value_type), pointers, classes

def module_data_ranges(reader: ProcessMemoryReader, module_name: str = "GameAssembly.dll",
                       local_path: str = "", on_log=None):
    log = on_log or (lambda _m: None)
    module = reader.module(module_name)
    if module is None:
        return []
    if local_path:
        try:
            pe = pe_mod.PeFile(local_path)
            ranges = []
            for va, size in pe.data_ranges(writable_only=True):
                if size <= 0 or va >= module.size:
                    continue
                ranges.append((module.base + va, min(size, module.size - va)))
            if ranges:
                total = sum(size for _b, size in ranges) / 1048576
                log(f"[locator] 可写数据节 {len(ranges)} 段，共 {total:.1f} MB")
                return ranges
        except Exception as exc:  # noqa: BLE001
            log(f"[locator] 节表解析失败（改用整模块扫描）: {exc}")
    return [(module.base, module.size)]

def _in_range(module, low: int, high: int) -> bool:
    return low <= module.base < module.base + module.size

@dataclass
class ScanContext:

    module_base: int
    module_size: int
    ranges: list[tuple[int, int]]
    roots: "_Ranges"

    @property
    def module_end(self) -> int:
        return self.module_base + self.module_size

    def in_module(self, address: int) -> bool:
        return self.module_base <= address < self.module_end

def build_context(reader: ProcessMemoryReader, module_name: str = "GameAssembly.dll",
                  local_path: str = "", on_log=None) -> "ScanContext | None":
    log = on_log or (lambda _m: None)
    module = reader.module(module_name)
    if module is None:
        log(f"[locator] 目标模块 {module_name} 未加载")
        return None
    ranges = module_data_ranges(reader, module_name, local_path, on_log=log)
    if not ranges:
        return None
    roots = _Ranges((r.base, r.size) for r in reader.regions(include_images=False))
    return ScanContext(module.base, module.size, ranges, roots)

def _value_ok(value, value_range) -> bool:
    if value is None:
        return False
    low, high = value_range or (None, None)
    if low is not None and value < low:
        return False
    if high is not None and value > high:
        return False
    return True

def discover_candidates(reader: ProcessMemoryReader, target: ChainTarget,
                        module_name: str = "", local_path: str = "",
                        on_log=None, limit: int = _MAX_CANDIDATES,
                        context: "ScanContext | None" = None) -> list[Candidate]:
    log = on_log or (lambda _m: None)
    context = context or build_context(reader, module_name or target.module, local_path, log)
    if context is None:
        return []
    offsets = tuple(target.offsets)

    out: list[Candidate] = []
    scanned = rejected = 0
    for address, ptr in reader.iter_pointers(context.ranges):
        scanned += 1
        if ptr not in context.roots:
            rejected += 1
            continue
        image = reader.read_u64(ptr + IL2CPP_CLASS_IMAGE)
        if not image or not context.in_module(image):
            rejected += 1
            continue
        name, ns = read_class_name(reader, ptr)
        if not name:
            rejected += 1
            continue
        value, _pointers, classes = walk_chain(reader, address, offsets, target.value_type)
        if not _value_ok(value, target.value_range):
            rejected += 1
            continue
        out.append(Candidate(mode="class", slot_rva=address - context.module_base,
                             slot_address=address, class_name=name, namespace=ns,
                             value=value, step_classes=tuple(classes),
                             note=f"已扫 {scanned} 个槽位"))
        log(f"[locator] 候选[class] {ns + '.' if ns else ''}{name} "
            f"slot=0x{address - context.module_base:X} value={value}")
        if len(out) >= limit:
            log(f"[locator] 候选达到上限 {limit}，停止扫描")
            break
    log(f"[locator] 结构性扫描结束：扫 {scanned} 个槽位，"
        f"因指针/类名/值域被排除 {rejected} 个，命中 {len(out)} 个")
    return out

def find_class_slot(reader: ProcessMemoryReader, class_name: str,
                    module_name: str = "GameAssembly.dll", local_path: str = "",
                    offsets: tuple[int, ...] | None = None,
                    value_type: str = "int32",
                    value_range: tuple[int | None, int | None] = (None, None),
                    on_log=None, context: "ScanContext | None" = None) -> list[Candidate]:
    log = on_log or (lambda _m: None)
    context = context or build_context(reader, module_name, local_path, log)
    if context is None:
        return []
    wanted = str(class_name).split("::")[-1].split(".")[-1]
    out: list[Candidate] = []
    scanned = matched = 0
    for address, ptr in reader.iter_pointers(context.ranges):
        scanned += 1
        if ptr not in context.roots:
            continue
        image = reader.read_u64(ptr + IL2CPP_CLASS_IMAGE)
        if not image or not context.in_module(image):
            continue
        name, ns = read_class_name(reader, ptr)
        if not name or (name != wanted and wanted not in name):
            continue
        matched += 1
        value = None
        classes: tuple[str, ...] = ()
        if offsets:
            raw, _p, names = walk_chain(reader, address, offsets, value_type)
            if _value_ok(raw, value_range):
                value = raw
            classes = tuple(names)
        out.append(Candidate(mode="class", slot_rva=address - context.module_base,
                             slot_address=address, class_name=name, namespace=ns,
                             value=value, step_classes=classes,
                             note="类名匹配"))
    log(f"[locator] 按类名 {class_name} 扫 {scanned} 个槽位：同名命中 {matched} 个，"
        f"可用（链校验通过）{len([c for c in out if c.value is not None])} 个")
    return out

def validate_chain(reader: ProcessMemoryReader, base_offset: int, target: ChainTarget,
                   module_name: str = "") -> dict:
    module = reader.module(module_name or target.module)
    if module is None:
        return {"ok": False, "reason": f"模块 {module_name or target.module} 未加载"}
    value, pointers, classes = walk_chain(
        reader, module.base + int(base_offset), tuple(target.offsets), target.value_type)
    if value is None:
        return {"ok": False, "reason": "链上任一步读取失败", "value": None}
    low, high = (target.value_range or (None, None))
    if low is not None and value < low:
        return {"ok": False, "reason": f"值 {value} 低于下界 {low}", "value": value}
    if high is not None and value > high:
        return {"ok": False, "reason": f"值 {value} 高于上界 {high}", "value": value}
    return {"ok": True, "reason": "值在合理区间", "value": value,
            "classes": classes, "pointers": pointers}

def locate(reader: ProcessMemoryReader, target: ChainTarget, on_log=None,
           local_path: str = "", context: ScanContext | None = None) -> dict:
    log = on_log or (lambda _m: None)
    offsets = tuple(target.offsets)
    floor, high = (target.value_range or (None, None))

    check = validate_chain(reader, target.base_offset, target)
    if check.get("ok"):
        log(f"[locator] {target.key}: 旧偏移仍然有效 "
            f"(base=0x{target.base_offset:X} value={check.get('value')})")
        return {"ok": True, "source": "previous-offset", "base_offset": target.base_offset,
                "root_class": target.root_class, "value": check.get("value"),
                "step_classes": list(check.get("classes") or [])}

    if target.root_class:
        log(f"[locator] {target.key}: 旧偏移失效，按类名重定位 "
            f"root_class={target.root_class} ...")
        for candidate in find_class_slot(reader, target.root_class, target.module,
                                         local_path, offsets, target.value_type,
                                         (floor, high), on_log=log, context=context):
            if candidate.value is None:
                continue
            log(f"[locator] {target.key}: 命中 {candidate.class_name} "
                f"base=0x{candidate.slot_rva:X} value={candidate.value}")
            return {"ok": True, "source": "class-name",
                    "base_offset": candidate.slot_rva,
                    "root_class": candidate.class_name, "namespace": candidate.namespace,
                    "value": candidate.value, "step_classes": list(candidate.step_classes)}

    log(f"[locator] {target.key}: 开始结构性发现"
        f"（扫描模块数据节，视内存大小约 1-3 分钟）...")
    candidates = discover_candidates(reader, target, target.module, local_path,
                                     on_log=log, context=context)
    if candidates:
        chosen = _pick_candidate(candidates)
        log(f"[locator] {target.key}: 发现 {len(candidates)} 个候选，选用 "
            f"{chosen.class_name} base=0x{chosen.slot_rva:X} value={chosen.value}")
        return {"ok": True, "source": "structural", "base_offset": chosen.slot_rva,
                "root_class": chosen.class_name, "namespace": chosen.namespace,
                "value": chosen.value, "step_classes": list(chosen.step_classes),
                "candidates": [c.as_dict() for c in candidates[:8]]}
    return {"ok": False, "source": "", "base_offset": target.base_offset,
            "root_class": target.root_class,
            "reason": "结构性发现没有候选（游戏没进主界面 / 链已失效，需要 CE 复查）"}

def _pick_candidate(candidates: list[Candidate]) -> Candidate:
    def score(item: Candidate) -> tuple:
        return (
            1 if item.namespace else 0,
            1 if item.value else 0,
            len([c for c in item.step_classes if c]),
            -item.slot_rva,
        )
    return max(candidates, key=score)

def attribute_chain(symbols, target: ChainTarget, root_class: str, root_kind: str = "class",
                    on_log=None) -> dict:
    log = on_log or (lambda _m: None)
    offsets = list(target.offsets)
    field_offsets = offsets[1:] if root_kind == "class" else offsets
    refs: list[tuple[str, str]] = []
    step_classes: list[str] = []
    current_class = root_class
    missing = ""
    for index, offset in enumerate(field_offsets):
        if not current_class:
            missing = f"第 {index + 1} 级没有类名可继续"
            break
        fields = symbols.fields_of(current_class) if hasattr(symbols, "fields_of") else {}
        hit = next((n for n, item in fields.items()
                    if int(item.get("offset", -1)) == int(offset)), "")
        if not hit:
            missing = (f"{current_class} 里没有偏移 0x{offset:X} 的字段"
                       f"（该字段可能没被 focus 保留，用 --focus 加上类名）")
            break
        refs.append((current_class, hit))
        next_class = str(fields[hit].get("type", "")).split("<")[0].strip()
        step_classes.append(next_class)
        current_class = next_class if index < len(field_offsets) - 1 else ""
    complete = len(refs) == len(field_offsets)
    log(f"[attribution] {target.key}: 已解析 {len(refs)}/{len(field_offsets)} 级"
        + ("（完整）" if complete else f"（部分：{missing}）")
        + (f" → {refs}" if refs else ""))
    return {"field_refs": refs, "step_classes": step_classes,
            "complete": complete, "detail": "完整" if complete else missing}

def resolve_offsets_from_refs(symbols, target: ChainTarget, on_log=None) -> tuple[int, ...] | None:
    log = on_log or (lambda _m: None)
    if not target.field_refs:
        return None
    resolved: list[int] = []
    for class_name, field_name in target.field_refs:
        offset = symbols.field_offset(class_name, field_name)
        if offset is None:
            log(f"[locator] {target.key}: 字段 {class_name}::{field_name} 在新 dump 里找不到")
            return None
        resolved.append(int(offset))
    if len(resolved) != len(target.offsets) - 1:
        log(f"[locator] {target.key}: 名字解析出的级数（{len(resolved)}）与链长不匹配")
        return None
    new_offsets = (target.offsets[0], *resolved)
    if new_offsets != tuple(target.offsets):
        log(f"[locator] {target.key}: 按名字刷新偏移 "
            f"{[hex(x) for x in target.offsets]} → {[hex(x) for x in new_offsets]}")
    else:
        log(f"[locator] {target.key}: 按名字解析的偏移与旧值一致")
    return new_offsets
