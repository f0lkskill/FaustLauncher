"""Standard/encrypted IL2CPP metadata unpack workflow.

This is the weekly refresh entry point for WarpHook.  It accepts the current
standard metadata v39 directly, and still falls back to the older static or
memory recovery path if a future build encrypts global-metadata.dat again.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from functions.hook import dumper as dumper_mod
from functions.hook import metadata_source, paths as paths_mod

TYPE_RE = re.compile(
    r"^(?:public|private|protected|internal|sealed|abstract|static|partial|\s)*"
    r"(?:class|struct|interface|enum)\s+([A-Za-z_0-9`.]+)", re.M)
METHOD_RE = re.compile(r"^\s*// RVA: 0x[0-9A-Fa-f]+", re.M)
FIELD_RE = re.compile(
    r"^\s*(?:public|private|protected|internal|static|readonly|const|volatile|"
    r"unsafe|extern|sealed|override|virtual|abstract|new|fixed|ref|\s)+"
    r"[^;]+; // 0x[0-9A-Fa-f]+", re.M)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _counts(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "types": len(TYPE_RE.findall(text)),
        "methods": len(METHOD_RE.findall(text)),
        "fields": len(FIELD_RE.findall(text)),
    }


def _type_names(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return set(TYPE_RE.findall(text))


def _latest_old_dump(current: Path) -> Path | None:
    root = current.parents[2] if current.name == "dump.cs" and current.parent.name == "out" else current.parents[1]
    skip = {current.parent, current.parent.parent}
    candidates = []
    for folder in root.iterdir() if root.exists() else ():
        if not folder.is_dir() or folder in skip:
            continue
        for name in ("dump.cs", "out/dump.cs"):
            candidate = folder / name
            if candidate.is_file() and candidate != current:
                candidates.append(candidate)
    return max(candidates, key=lambda item: item.stat().st_mtime) if candidates else None


def _write_report(report: Path, metadata: Path, dump: Path,
                  old_dump: Path | None) -> None:
    new_counts = _counts(dump)
    lines = [
        f"# Metadata 解包报告（{__import__('datetime').date.today().isoformat()}）",
        "",
        "## 输入",
        "",
        f"- metadata：`{metadata}`",
        f"- metadata 大小：{metadata.stat().st_size:,} 字节",
        f"- metadata SHA-256：`{_sha256(metadata)}`",
        f"- dump：`{dump}`",
        f"- dump 大小：{dump.stat().st_size:,} 字节",
        "",
        "## 统计",
        "",
        f"- 类型：{new_counts['types']:,}",
        f"- 方法：{new_counts['methods']:,}",
        f"- 字段：{new_counts['fields']:,}",
    ]
    if old_dump and old_dump.is_file():
        old_counts = _counts(old_dump)
        old_types, new_types = _type_names(old_dump), _type_names(dump)
        added = sorted(new_types - old_types)
        removed = sorted(old_types - new_types)
        lines += [
            "",
            f"## 对比 `{old_dump}`",
            "",
            "| 对象 | 旧 | 新 | 变化 |",
            "| --- | ---: | ---: | ---: |",
        ]
        for key, label in (("types", "类型"), ("methods", "方法"), ("fields", "字段")):
            lines.append(
                f"| {label} | {old_counts[key]:,} | {new_counts[key]:,} | "
                f"{new_counts[key] - old_counts[key]:+,} |")
        lines += ["", f"- 新增类型：{len(added):,}", f"- 删除类型：{len(removed):,}"]
        if added:
            lines += ["", "新增类型示例：", *[f"- `{name}`" for name in added[:30]]]
        if removed:
            lines += ["", "删除类型示例：", *[f"- `{name}`" for name in removed[:30]]]
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="解包 IL2CPP metadata 并生成 dump.cs")
    parser.add_argument("--game", default="", help="游戏目录；默认自动定位")
    parser.add_argument("--out", default="", help="输出目录")
    parser.add_argument("--report", default="", help="报告路径")
    parser.add_argument("--no-download", action="store_true", help="禁止自动下载 Il2CppDumper")
    parser.add_argument("--compare", default="", help="对比的旧 dump.cs")
    args = parser.parse_args(argv)

    paths = paths_mod.game_paths(args.game)
    if not paths.ok:
        print(f"游戏文件缺失: {paths.missing()}", flush=True)
        return 1

    out_dir = Path(args.out) if args.out else Path(paths_mod.cache_path(
        "dump", __import__("time").strftime("%Y%m%d_%H%M%S") + "_standard"))
    out_dir.mkdir(parents=True, exist_ok=True)

    metadata = Path(paths.metadata)
    header = metadata_source.header_from_file(str(metadata))
    if header is not None and metadata_source.is_standard_metadata(str(metadata)):
        print(f"[metadata] 标准 metadata v{header.version}，直接使用磁盘文件", flush=True)
    else:
        print("[metadata] 非标准 metadata，进入静态/内存恢复流程", flush=True)
        recovered = metadata_source.obtain_metadata(
            paths.metadata, paths.gameassembly, on_log=print,
            allow_static=True, allow_memory=True, dump_dir=str(out_dir))
        if not recovered.ok:
            print(f"[metadata] 恢复失败: {recovered.detail}", flush=True)
            return 1
        metadata = Path(recovered.path)
        header = metadata_source.header_from_file(str(metadata))
        print(f"[metadata] 恢复结果: {recovered.describe()}", flush=True)

    exe = dumper_mod.ensure_dumper(on_log=print,
                                    allow_download=not args.no_download)
    if not exe:
        print("找不到 Il2CppDumper.exe", flush=True)
        return 1
    result = dumper_mod.run_dumper(
        exe, paths.gameassembly, str(metadata), str(out_dir / "out"),
        on_log=print)
    print(result.detail, flush=True)
    if not result.ok:
        return 1

    dump = Path(result.dump_cs)
    old_dump = Path(args.compare) if args.compare else _latest_old_dump(dump)
    report = Path(args.report) if args.report else out_dir / "run-report.md"
    _write_report(report, metadata, dump, old_dump)
    print(f"[metadata] dump.cs: {dump}", flush=True)
    print(f"[metadata] report: {report}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

