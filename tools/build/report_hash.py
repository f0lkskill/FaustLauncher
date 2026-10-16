# -*- coding: utf-8 -*-
"""算发布产物的 SHA256，并生成「杀软误报申诉」材料。

用途（D 项：向微软 / 杀软厂商申诉误报，把产物拉进白名单）：

  构建或发布之后跑一次，脚本会：

  1. 找到待申诉的产物（默认取最近的 ``build_<版本>/`` 目录，或命令行的 zip/exe 路径）；
  2. 算 **发布 zip 的 SHA256**（用户在浏览器里下载的正是它）与 **exe 的 SHA256**；
  3. 写成 ``<产物目录>/defender-appeal.txt``，内容按微软「提交误报分析」表单逐项排好，
     直接复制粘贴即可，不必再回来翻哈希。

用法：

    python tools/build/report_hash.py
    python tools/build/report_hash.py FaustLauncher-0.9.2.zip
"""

import hashlib
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def read_project_version() -> str:
    """读 config/settings.json 的 version_info（可能是裸字符串，也可能是设置项对象）。"""
    import json

    path = os.path.join(_ROOT, "config", "settings.json")
    try:
        raw = open(path, "rb").read()
    except OSError:
        return ""
    for enc in ("utf-8-sig", "gbk", "utf-8"):
        try:
            data = json.loads(raw.decode(enc))
        except (UnicodeDecodeError, ValueError):
            continue
        value = (data or {}).get("version_info")
        if isinstance(value, dict):
            value = value.get("value") or value.get("default") or ""
        text = str(value or "").strip()
        if text:
            return text
    return ""


def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def newest_build_dir() -> str:
    candidates = []
    for name in os.listdir(_ROOT):
        full = os.path.join(_ROOT, name)
        if name.startswith("build_") and os.path.isdir(full):
            candidates.append(full)
    if not candidates:
        return ""
    return max(candidates, key=lambda p: os.path.getmtime(p))


def pick_targets(argv) -> dict:
    result = {"zip": "", "exe": ""}
    if argv:
        for item in argv:
            path = item if os.path.isabs(item) else os.path.join(_ROOT, item)
            if os.path.isfile(path):
                result["zip" if path.lower().endswith(".zip") else "exe"] = path
        return result

    version = read_project_version().lstrip("vV")
    if version:
        guess = os.path.join(_ROOT, "FaustLauncher-" + version + ".zip")
        if os.path.isfile(guess):
            result["zip"] = guess

    build_dir = newest_build_dir()
    if build_dir:
        exe = os.path.join(build_dir, "FaustLauncher.exe")
        if os.path.isfile(exe):
            result["exe"] = exe
        for name in os.listdir(build_dir):
            if name.lower().endswith(".zip"):
                result["zip"] = result["zip"] or os.path.join(build_dir, name)
    return result


def main() -> int:
    targets = pick_targets(sys.argv[1:])
    if not targets["zip"] and not targets["exe"]:
        print("没找到要申诉的产物（zip/exe），请显式传路径")
        return 1

    version = read_project_version() or "unknown"
    lines = [
        "FaustLauncher 误报申诉材料",
        "=" * 40,
        "",
        "提交入口: https://www.microsoft.com/en-us/wdsi/filesubmission",
        "提交类型: 选择 “Software developer” 提交误报 (false positive)",
        "",
        "Application name: FaustLauncher",
        "Application version: " + version,
        "Publisher: folk.skill (未签名 / 无代码签名证书)",
        "Download URL: (填发布页 / 网盘直链)",
        "",
    ]
    for label, key in (("发布包 zip", "zip"), ("主程序 exe", "exe")):
        path = targets.get(key) or ""
        if not path:
            continue
        lines.append(f"{label}:")
        lines.append("  file   = " + os.path.basename(path))
        lines.append("  size   = %d bytes" % os.path.getsize(path))
        lines.append("  sha256 = " + sha256_of(path))
        lines.append("")

    lines += [
        "Use / purpose:",
        "  这是《Limbus Company》(Steam 单机游戏) 的第三方启动器与汉化工具，仅在本机读写游戏目录下的",
        "  汉化 / Mod / 配置文件，不修改系统设置、不加载内核驱动、不在用户不知情时联网执行代码。",
        "  它由开源仓库 Python 源码经 PyInstaller 打包（onedir），未加壳、未混淆。",
        "",
        "项目源码: https://github.com/f0lkskill/FaustLauncher",
        "",
        "Detection name (若已被查杀, 填 Defender 历史里的威胁名, 例如 Trojan:Win32/Wacatac.B!ml):",
        "",
    ]

    text = "\n".join(lines) + "\n"
    out_dir = _ROOT
    for key in ("zip", "exe"):
        if targets.get(key):
            out_dir = os.path.dirname(targets[key])
            break
    out_path = os.path.join(out_dir, "defender-appeal.txt")
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(text)
    print("已写入: " + out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
