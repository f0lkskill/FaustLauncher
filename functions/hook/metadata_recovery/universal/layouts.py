#!/usr/bin/env python3

from __future__ import annotations

import itertools
import struct

LAYOUT_NAMES = ["offset", "size", "count"]

LAYOUTS: dict[str, list[str]] = {
    "_".join(perm): list(perm)
    for perm in itertools.permutations(LAYOUT_NAMES)
}

UINT64_MASK = (1 << 64) - 1

def next_xorshift64(state: int) -> int:
    state ^= state << 13 & UINT64_MASK
    state ^= state >> 7
    state ^= state << 17 & UINT64_MASK
    return state & UINT64_MASK

def decrypt_bytes(data: bytes, seed: int, table: bytes) -> bytes:
    output = bytearray(data)
    state = seed
    for index in range(len(output)):
        state = next_xorshift64(state)
        table_index = (state ^ (state >> 8) ^ (state >> 16) ^ (state >> 24)) & 0xFF
        output[index] ^= table[table_index]
    return bytes(output)

def parse_triplets(header: bytes, layout: list[str]) -> list[dict]:
    entries = []
    for index, offset in enumerate(range(0, len(header) - len(header) % 12, 12)):
        fields = dict(zip(layout, struct.unpack_from("<iii", header, offset)))
        entries.append({
            "index": index,
            "header_offset": offset,
            "size": fields["size"],
            "count": fields["count"],
            "offset": fields["offset"],
        })
    return entries

def score_layout(entries: list[dict], file_size: int) -> float:
    if not entries:
        return 0.0
    score = 0.0
    for e in entries:
        ok = 0.0
        if e["offset"] >= 0 and e["size"] >= 0:
            ok += 0.35
            end = e["offset"] + e["size"]
            if end <= file_size:
                ok += 0.3
            else:
                ok += 0.1
        if e["count"] > 0 and e["size"] % e["count"] == 0:
            ok += 0.35
        elif e["size"] == 0:
            ok += 0.35
        score += ok
    return score / len(entries)

def detect_layout(header: bytes, file_size: int) -> tuple[str, list[dict], dict[str, float]]:
    scores = {name: score_layout(parse_triplets(header, layout), file_size)
              for name, layout in LAYOUTS.items()}
    best = max(scores, key=scores.get)
    return best, parse_triplets(header, LAYOUTS[best]), scores
