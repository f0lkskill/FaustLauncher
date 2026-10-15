# -*- coding: utf-8 -*-
"""版本号比较 (更新检查 / 版本卡片共用, 不依赖任何项目内模块)。

背景 —— 为什么需要这个模块:
    早期判定"有没有新版本"只用字符串不等: ``latest_release != current_version``。
    本地自建或尚未发布的版本号 (例如 V0.9.2-release) 只要和云端
    ``latest_release_version`` (V0.9.1-release.fix.1) 不一样, 就会被判定为
    "发现新版本" 并**强制下载安装**, 结果是把用户手上的新版本降级成旧版本,
    同时把 settings 里的 version_info 改写成旧版本号。
    这里用版本号语义比较替代字符串比较: 只有云端版本**确实更高**才算更新。
"""

import re

# 同一数值段下的等级: 预发布 < 正式版 < 正式版之上的热修复
_RANK_PRERELEASE = 0
_RANK_RELEASE = 1
_RANK_FIX = 2

_PRERELEASE_NAMES = ('alpha', 'beta', 'rc', 'pre', 'dev', 'test')


def parse_version_key(version):
    """把版本号解析成可比较的元组 ``(数值段, 等级, 修补序号)``。

    兼容项目里出现过的写法:
        ``V0.9.2-release`` / ``V0.9.1-release.fix.1`` / ``1.2.3`` / ``v1.0.0-beta``

    · 数值段 (0.9.2) 决定主序, 逐段比较 (``(0,9,2) > (0,9)``)
    · 同一数值段下 ``release.fix.N`` 必须比同号 ``release`` 新
      (它是在正式版之上打的热修复), 而 beta/test 之类的预发布比正式版旧
    """
    text = str(version or '').strip().lstrip('vV')
    match = re.match(r'(\d+(?:\.\d+)*)', text)
    nums = tuple(int(x) for x in match.group(1).split('.')) if match else (0,)
    rest = (text[match.end():] if match else text).lower()

    if 'fix' in rest:
        fix = re.search(r'fix[._\-]?(\d+)', rest)
        return (nums, _RANK_FIX, int(fix.group(1)) if fix else 1)
    for name in _PRERELEASE_NAMES:
        if name in rest:
            return (nums, _RANK_PRERELEASE, 0)
    # release / 没有任何标签: 一律按正式版处理
    return (nums, _RANK_RELEASE, 0)


def is_newer_version(candidate, current):
    """``candidate`` 是否比 ``current`` 更新 (相同或更旧都返回 False)"""
    if not str(candidate or '').strip():
        return False
    return parse_version_key(candidate) > parse_version_key(current)
