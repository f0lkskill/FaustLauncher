r"""VDF 文本级读写工具（保格式 / 保注释 / 保键顺序）。

为什么不"解析成 dict 再整体重新序列化"：
    Steam 的 localconfig.vdf 动辄七万行，缩进、键序、`\t\t` 分隔习惯、注释都是
    Steam 自己写出来的。整文件重新序列化会把差异放大成几十万字节的 diff，
    一旦某处语法猜错就整份配置报废，回滚也无从下手。
    这里只解析出"每个键/值在原文里的字节区间"，然后在目标区间上做定点替换或插入，
    目标以外的字节一律原样保留。

支持的 API：
    tokenize(text)                -> list[Token]
    parse(text)                   -> list[Node]（带区间信息的轻量语法树）
    find_path(nodes, path)        -> Node | None
    get_string(text, path, d=None)-> str | None
    set_string(text, path, value) -> (new_text, changed)
    remove_key(text, path)        -> (new_text, changed)
    has_path(text, path)          -> bool
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

__all__ = [
    "VdfTextError",
    "Token",
    "Node",
    "tokenize",
    "parse",
    "find_path",
    "get_string",
    "set_string",
    "remove_key",
    "has_path",
    "escape",
    "detect_newline",
]

TAB = "\t"
DEFAULT_SEP = "\t\t"          # Steam 自己的 key<->value 分隔习惯
_WS = " \t\r\n"
_BARE_STOP = ' \t\r\n"{}'


class VdfTextError(ValueError):
    """VDF 文本无法按预期定位/修改时抛出。"""


# --------------------------------------------------------------------------- #
# 词法
# --------------------------------------------------------------------------- #
@dataclass
class Token:
    kind: str                 # 'string' | 'open' | 'close'
    start: int                # 含引号的起点
    end: int                  # 含引号的终点（开区间）
    value: str | None = None  # 字符串内容（已反转义）
    vstart: int = 0           # 内容区间（不含引号）
    vend: int = 0


def tokenize(text: str) -> list[Token]:
    """切成 string / { / } 三类 token，跳过空白与 // 注释。"""
    out: list[Token] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in _WS:
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] not in "\r\n":
                i += 1
            continue
        if c in "{}":
            out.append(Token("open" if c == "{" else "close", i, i + 1))
            i += 1
            continue
        if c == '"':
            j = i + 1
            buf: list[str] = []
            while j < n:
                ch = text[j]
                if ch == '"':
                    break
                if ch == "\\" and j + 1 < n:
                    buf.append(text[j + 1])
                    j += 2
                    continue
                buf.append(ch)
                j += 1
            out.append(Token("string", i, j + 1, "".join(buf), i + 1, j))
            i = j + 1
            continue
        # 未加引号的裸字（Steam 偶尔会写，容错处理）
        j = i
        while j < n and text[j] not in _BARE_STOP:
            j += 1
        out.append(Token("string", i, j, text[i:j], i, j))
        i = j if j > i else i + 1
    return out


# --------------------------------------------------------------------------- #
# 语法树（每个节点记录自己在原文里的位置）
# --------------------------------------------------------------------------- #
@dataclass
class Node:
    key: str
    key_start: int
    key_end: int
    value: str | None = None
    value_span: tuple[int, int] | None = None   # 字符串值的内容区间
    value_end: int = 0                          # 值 token 的结束位置（含收尾引号）
    block: list["Node"] | None = None
    block_open: int = -1                        # '{' 的位置
    block_span: tuple[int, int] | None = None   # ('{', '}' 之后)

    @property
    def is_block(self) -> bool:
        return self.block is not None


def parse(text: str) -> list[Node]:
    """把 VDF 文本解析成带区间的节点列表；容错，不抛异常。"""
    tokens = tokenize(text)
    roots: list[Node] = []
    stack: list[Node] = []
    current: list[Node] = roots
    i, n = 0, len(tokens)
    while i < n:
        tk = tokens[i]
        if tk.kind == "close":
            if stack:
                node = stack.pop()
                node.block_span = (node.block_open, tk.end)
                current = stack[-1].block if stack else roots
            i += 1
            continue
        if tk.kind == "open":
            i += 1                      # 无主句的 '{'，跳过
            continue
        key = tk.value or ""
        nxt = tokens[i + 1] if i + 1 < n else None
        if nxt is not None and nxt.kind == "open":
            node = Node(key=key, key_start=tk.start, key_end=tk.end,
                        block=[], block_open=nxt.start)
            current.append(node)
            stack.append(node)
            current = node.block
            i += 2
            continue
        if nxt is not None and nxt.kind == "string":
            current.append(Node(key=key, key_start=tk.start, key_end=tk.end,
                                value=nxt.value,
                                value_span=(nxt.vstart, nxt.vend),
                                value_end=nxt.end))
            i += 2
            continue
        i += 1                          # 键后面什么都没跟，忽略
    return roots


def find_path(nodes: Sequence[Node], path: Sequence[str]) -> Node | None:
    """按路径找节点；路径为空返回 None。中途遇到字符串值则判为不存在。"""
    if not path:
        return None
    cur: Sequence[Node] = nodes
    node: Node | None = None
    for idx, key in enumerate(path):
        hit = None
        for cand in cur:
            if cand.key == key:
                hit = cand
                break
        if hit is None:
            return None
        node = hit
        if idx == len(path) - 1:
            return hit
        if hit.block is None:
            return None
        cur = hit.block
    return node


def has_path(text: str, path: Sequence[str]) -> bool:
    return find_path(parse(text), path) is not None


def get_string(text: str, path: Sequence[str], default: str | None = None) -> str | None:
    node = find_path(parse(text), path)
    if node is None or node.block is not None:
        return default
    return default if node.value is None else node.value


# --------------------------------------------------------------------------- #
# 排版辅助
# --------------------------------------------------------------------------- #
def detect_newline(text: str) -> str:
    head = text[:8192]
    return "\r\n" if "\r\n" in head else "\n"


def escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _line_start(text: str, pos: int) -> int:
    i = pos
    while i > 0 and text[i - 1] not in "\r\n":
        i -= 1
    return i


def _line_indent(text: str, pos: int) -> str:
    i = _line_start(text, pos)
    j = i
    while j < len(text) and text[j] in " \t":
        j += 1
    return text[i:j]


def _child_indent(text: str, node: Node) -> str:
    if node.block:
        return _line_indent(text, node.block[0].key_start)
    return _line_indent(text, node.block_span[0]) + TAB


def _render(keys: Sequence[str], value: str, indent: str, nl: str,
            unit: str = TAB) -> str:
    """把 keys[0] ..= value 渲染成 VDF 文本（相对缩进已由 indent 给出）。"""
    key = escape(keys[0])
    if len(keys) == 1:
        return f'{indent}"{key}"{DEFAULT_SEP}"{escape(value)}"{nl}'
    inner = indent + unit
    body = _render(keys[1:], value, inner, nl, unit)
    return f'{indent}"{key}"{nl}{indent}{{{nl}{body}{indent}}}{nl}'


def _insert_into(text: str, parent: Node | None, keys: Sequence[str],
                 value: str) -> str:
    """把 keys->value 插进 parent 块（parent=None 表示文件根）末尾。"""
    nl = detect_newline(text)
    if parent is None:
        at = len(text)
        prefix = "" if text.endswith(("\n", "\r")) or not text else nl
        return text + prefix + _render(keys, value, "", nl)
    if parent.block_span is None:
        raise VdfTextError(f'"{parent.key}" 不是块，无法插入子键')
    open_pos, close_end = parent.block_span
    close_pos = close_end - 1
    unit = _child_indent(text, parent)
    line_start = _line_start(text, close_pos)
    payload = _render(keys, value, unit, nl)
    if line_start > open_pos and not text[line_start:close_pos].strip():
        # 闭合括号独占一行：插在那一行的行首
        return text[:line_start] + payload + text[line_start:]
    # 单行块或畸形块：补一个换行再插
    return text[:close_pos] + nl + payload + text[close_pos:]


def set_string(text: str, path: Sequence[str], value) -> tuple[str, bool]:
    """把 path 指向的字符串值设为 value；不存在则创建（含缺失的父块）。

    返回 (新文本, 是否改动)。值已经相同时原样返回，changed=False。
    """
    if not path:
        raise VdfTextError("path 不能为空")
    want = "" if value is None else str(value)
    roots = parse(text)
    parent_path = tuple(path[:-1])
    leaf_key = str(path[-1])

    parent: Node | None = None
    if parent_path:
        parent = find_path(roots, parent_path)
        if parent is None or parent.block is None:
            # 父链不存在：找到最深的已存在前缀，一次性补齐剩余块
            return _create_chain(text, roots, parent_path, leaf_key, want), True

    siblings = parent.block if parent is not None else roots
    leaf = None
    for cand in siblings:
        if cand.key == leaf_key:
            leaf = cand
            break

    if leaf is not None:
        if leaf.block is not None:
            raise VdfTextError(f'"{leaf_key}" 是一个块，不能用字符串覆盖')
        if leaf.value_span is None:
            raise VdfTextError(f'"{leaf_key}" 没有可替换的值区间')
        s, e = leaf.value_span
        if text[s:e] == escape(want):
            return text, False
        return text[:s] + escape(want) + text[e:], True

    return _insert_into(text, parent, [leaf_key], want), True


def _create_chain(text: str, roots: Sequence[Node], parent_path: Sequence[str],
                  leaf_key: str, value: str) -> str:
    depth = 0
    for k in range(len(parent_path), 0, -1):
        if find_path(roots, parent_path[:k]) is not None:
            depth = k
            break
    container = find_path(roots, parent_path[:depth]) if depth else None
    if depth and (container is None or container.block is None):
        raise VdfTextError("父链定位到了字符串值，无法继续创建子块")
    rest = list(parent_path[depth:]) + [leaf_key]
    return _insert_into(text, container, rest, value)


def remove_key(text: str, path: Sequence[str]) -> tuple[str, bool]:
    """删除 path 指向的键（整行，含所属块）。不存在时原样返回。"""
    if not path:
        raise VdfTextError("path 不能为空")
    node = find_path(parse(text), path)
    if node is None:
        return text, False
    start = _line_start(text, node.key_start)
    if node.block_span is not None:
        end = node.block_span[1]
    elif node.value_span is not None:
        end = node.value_end or node.value_span[1]
    else:
        end = node.key_end
    while end < len(text) and text[end] in " \t":
        end += 1
    if text.startswith("\r\n", end):
        end += 2
    elif end < len(text) and text[end] == "\n":
        end += 1
    return text[:start] + text[end:], True
