# -*- coding: utf-8 -*-
"""给 tools/build/FaustLauncher.spec 打上 exe 版本资源（幂等，可重复执行）。"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
SPEC = os.path.join(ROOT, "tools", "build", "FaustLauncher.spec")

ANCHOR = "_ROOT = _os.path.abspath(_os.path.join(SPECPATH, '..', '..'))"

BLOCK = '''_ROOT = _os.path.abspath(_os.path.join(SPECPATH, '..', '..'))

if SPECPATH not in _sys.path:
    _sys.path.insert(0, SPECPATH)

_VERSION_FILE = _os.path.join(SPECPATH, 'version_info.txt')
try:
    _cwd = _os.getcwd()
    _os.chdir(_ROOT)
    import version_info_gen
    version_info_gen.main()
except Exception as _exc:
    print('[spec] version_info.txt 生成失败: %s' % _exc)
finally:
    try:
        _os.chdir(_cwd)
    except Exception:
        pass
'''

EXE_ANCHOR = "    name='FaustLauncher',\n    debug=False,"
EXE_REPLACEMENT = "    name='FaustLauncher',\n    version=_VERSION_FILE,\n    debug=False,"


def main() -> int:
    src = open(SPEC, encoding="utf-8").read()

    if "version=_VERSION_FILE" in src:
        print("spec 已打过版本资源补丁，跳过")
        return 0

    if src.count(ANCHOR) != 1:
        print("未找到唯一的 _ROOT 锚点，中止")
        return 1
    src = src.replace(ANCHOR, BLOCK, 1)

    if src.count(EXE_ANCHOR) != 1:
        print("未找到唯一的 EXE name 锚点，中止")
        return 1
    src = src.replace(EXE_ANCHOR, EXE_REPLACEMENT, 1)

    with open(SPEC, "w", encoding="utf-8", newline="") as fh:
        fh.write(src)
    print("spec 已写入版本资源补丁")
    return 0


if __name__ == "__main__":
    sys.exit(main())
