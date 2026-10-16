# -*- coding: utf-8 -*-

import re

_RANK_PRERELEASE = 0
_RANK_RELEASE = 1
_RANK_FIX = 2

_PRERELEASE_NAMES = ('alpha', 'beta', 'rc', 'pre', 'dev', 'test')

def parse_version_key(version):
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
    return (nums, _RANK_RELEASE, 0)

def is_newer_version(candidate, current):
    if not str(candidate or '').strip():
        return False
    return parse_version_key(candidate) > parse_version_key(current)
