#!/usr/bin/env python3

from __future__ import annotations

import re

_TEMPLATE = (
    b"\x48\xC1[\xE0-\xE7]\x0D"
    b"\x48[\x31\x33]."
    b"\x48[\x89\x8B]."
    b"\x48\xC1[\xE8-\xEF]\x07"
    b"\x48[\x31\x33]."
    b"\x48[\x89\x8B]."
    b"\x48\xC1[\xE0-\xE7]\x11"
    b"\x48[\x31\x33]."
)

RE_TEMPLATE = re.compile(_TEMPLATE)

def scan(text_bytes: bytes, base_va: int) -> list[int]:
    hits = []
    for m in RE_TEMPLATE.finditer(text_bytes):
        hits.append(base_va + m.start())
    return hits

def scan_pe(image) -> list[int]:
    sec = image.text_section
    if sec is None:
        raise ValueError("PE has no .text section")
    raw = image.data[sec.raw_offset:sec.raw_offset + sec.raw_size]
    return scan(raw, image.image_base + sec.virtual_address)
