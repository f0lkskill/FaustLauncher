# -*- coding: utf-8 -*-
"""生成 PyInstaller 用的 exe 版本资源（Windows VERSIONINFO）。

打包出来的 FaustLauncher.exe 过去**没有任何版本资源**（FileVersion / CompanyName /
ProductName 全空），这正是杀软把 PyInstaller 产物判为可疑的经典特征之一：
无厂商、无版本、无描述的可执行文件，Defender 与第三方杀软的启发式评分会明显偏高。

本脚本从 config/settings.json 的 version_info 生成 tools/build/version_info.txt，
在 PyInstaller 打包前跑一次即可；生成的 version_info.txt 不入库（构建中间产物）。

用法：
    python tools/build/version_info_gen.py
"""

import json
import os
import re

_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

SETTINGS_PATH = os.path.join(_ROOT, "config", "settings.json")
OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "version_info.txt")

FILE_DESCRIPTION = "FaustLauncher - Limbus Company launcher and localization tool"
COMPANY_NAME = "folkskill"
PRODUCT_NAME = "FaustLauncher"
LEGAL_COPYRIGHT = "Copyright (c) 2025 folkskill. MIT License."


def read_project_version() -> str:
    """读 config/settings.json 的 version_info。

    该文件是 GBK 编码（老版本写下的中文设置项），直接按 UTF-8 读会炸，
    所以按 utf-8-sig → gbk 顺序试。
    """
    try:
        with open(SETTINGS_PATH, "rb") as fh:
            raw = fh.read()
    except OSError:
        return "0.0.0"

    for enc in ("utf-8-sig", "gbk", "utf-8"):
        try:
            data = json.loads(raw.decode(enc))
        except (UnicodeDecodeError, ValueError):
            continue
        version = _extract_version((data or {}).get("version_info"))
        if version:
            return version
    return "0.0.0"


def _extract_version(raw) -> str:
    """version_info 可能是裸字符串，也可能是 {"value": "V0.9.2-release", ...} 这样的设置项对象。"""
    if isinstance(raw, dict):
        for key in ("value", "default", "name"):
            candidate = str(raw.get(key) or "").strip()
            if candidate and re.search(r"\d", candidate):
                return candidate
        return ""
    return str(raw or "").strip()


def version_tuple(version: str) -> tuple:
    """把 "V0.9.2-release" 这类版本串转成 (0, 9, 2, 0)。

    非正式版（beta / test / fix 等）在第四段留 0；Windows 版本资源的四段必须是
    0..65535 的整数，任何字母段都会让生成的资源在打包时解析失败。
    """
    text = str(version or "").strip().lstrip("vV")
    match = re.match(r"(\d+(?:\.\d+)*)", text)
    if not match:
        return (0, 0, 0, 0)
    nums = []
    for part in match.group(1).split("."):
        try:
            value = int(part)
        except ValueError:
            value = 0
        nums.append(max(0, min(65535, value)))
    nums = (nums + [0, 0, 0, 0])[:4]
    return tuple(nums)


def build_resource(version: str) -> str:
    """产出 VSVersionInfo 的 Python 字面量文本（PyInstaller 的 version 文件格式）。"""
    ver = version_tuple(version)
    ver_text = ".".join(str(x) for x in ver)
    display = str(version or "").strip() or ver_text
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={ver},
    prodvers={ver},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '040904B0',
          [StringStruct('CompanyName', {COMPANY_NAME!r}),
           StringStruct('FileDescription', {FILE_DESCRIPTION!r}),
           StringStruct('FileVersion', {ver_text!r}),
           StringStruct('InternalName', {PRODUCT_NAME!r}),
           StringStruct('LegalCopyright', {LEGAL_COPYRIGHT!r}),
           StringStruct('OriginalFilename', {PRODUCT_NAME + '.exe'!r}),
           StringStruct('ProductName', {PRODUCT_NAME!r}),
           StringStruct('ProductVersion', {display!r})])
      ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main() -> int:
    version = read_project_version()
    text = build_resource(version)
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"version_info.txt 已生成: {OUT_PATH} (version={version}, filevers={version_tuple(version)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
