"""Portable export resolver regressions; only synthetic DLL bytes are read.

Run: python tools/dev/test_il2cpp_exports_portable.py
No pefile installation, game files, Windows APIs or running game are needed.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "functions/base/il2cpp_exports.py"


class PortableExportsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.game = self.root / "synthetic_game"
        self.game.mkdir()
        self.assembly = self.game / "GameAssembly.dll"
        self.player = self.game / "UnityPlayer.dll"
        self.table = self.root / "names.txt"
        self.canonical = ["il2cpp_alpha", "il2cpp_beta", "il2cpp_gamma"]
        self.table.write_text("\n".join(self.canonical), encoding="utf-8")
        self.exports = {}
        self.code = b""
        self.fake_pefile = types.ModuleType("pefile")
        self.fake_pefile.PE = self._pe
        path_utils = types.ModuleType("functions.base.common.path_utils")
        path_utils.get_app_root = lambda **kwargs: str(self.root)
        patches = mock.patch.dict(sys.modules, {
            "pefile": self.fake_pefile,
            "functions.base.common.path_utils": path_utils,
        })
        patches.start()
        self.addCleanup(patches.stop)
        spec = importlib.util.spec_from_file_location("_portable_il2cpp_exports", SOURCE)
        self.ix = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.ix)

    def _pe(self, path, fast_load=True):
        owner = self

        class FakePE:
            def __init__(self):
                self.sections = [types.SimpleNamespace(
                    Name=b".text\0\0\0", VirtualAddress=0x1200,
                    get_data=lambda: owner.code,
                )]
                self.DIRECTORY_ENTRY_EXPORT = types.SimpleNamespace(symbols=[
                    types.SimpleNamespace(name=name.encode("ascii"), address=rva)
                    for name, rva in owner.exports.items()
                ])

            def parse_data_directories(self, **kwargs):
                pass

            def get_rva_from_offset(self, offset):
                return 0x1000 + offset

            def close(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.close()

        return FakePE()

    def fixture(self, aliases=None, *, rex=0x48, repeated=False, tail=b""):
        aliases = aliases or ["a", "Abcdefghijk", "_LongerObfuscatedExport12345"]
        self.exports = {name: 0x3000 + index * 16
                        for index, name in enumerate(aliases)}
        self.assembly.write_bytes(b"synthetic export identity:" + b"|".join(
            name.encode("ascii") for name in aliases))
        data = bytearray(0x200)
        positions = []
        cursor = 0x40
        for name in aliases:
            raw = name.encode("ascii") + b"\0"
            positions.append(0x1000 + cursor)
            data[cursor:cursor + len(raw)] = raw
            cursor += len(raw) + 1
        refs = positions + ([positions[0]] if repeated else [])
        code = bytearray()
        for index, target in enumerate(refs):
            instruction_rva = 0x1200 + len(code)
            modrm = 0x05 | ((index % 8) << 3)
            code += bytes((rex, 0x8D, modrm))
            code += struct.pack("<i", target - instruction_rva - 7)
        code += tail
        self.code = bytes(code)
        data.extend(self.code)
        self.player.write_bytes(data)
        return aliases

    def scan(self):
        return self.ix.scan(str(self.game), names_path=str(self.table))

    def load(self):
        return self.ix.load_cache(str(self.game), names_path=str(self.table))

    def test_variable_length_names(self):
        aliases = self.fixture()
        result = self.scan()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["mapping"], dict(zip(self.canonical, aliases)))

    def test_rex_high_registers_and_negative_displacements(self):
        aliases = self.fixture(rex=0x4C)
        result = self.scan()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["mapping"], dict(zip(self.canonical, aliases)))

    def test_positive_displacements(self):
        aliases = self.fixture()
        # Reuse the same strings but move their synthetic RVA above .text.
        original_pe = self.fake_pefile.PE

        def higher_strings_pe(*args, **kwargs):
            pe = original_pe(*args, **kwargs)
            pe.get_rva_from_offset = lambda offset: 0x4000 + offset
            return pe

        self.fake_pefile.PE = higher_strings_pe
        code = bytearray()
        cursor = 0x40
        for name in aliases:
            code += b"\x48\x8d\x0d" + struct.pack(
                "<i", 0x4000 + cursor - (0x1200 + len(code) + 7))
            cursor += len(name) + 2
        self.code = bytes(code)
        result = self.scan()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["mapping"], dict(zip(self.canonical, aliases)))

    def test_truncated_lea_at_section_end_is_ignored(self):
        self.fixture(tail=b"\x4c\x8d\x05\x01")
        self.assertTrue(self.scan()["ok"])
        self.fixture(tail=b"\x48\x8d\x05")
        self.assertTrue(self.scan()["ok"])

    def test_standard_exports_bypass_reference_order(self):
        self.fixture(self.canonical)
        self.code = b""
        self.player.write_bytes(b"synthetic player without lea references")
        result = self.scan()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["strategy"], "standard")
        self.assertEqual(result["mapping"], {name: name for name in self.canonical})

    def test_duplicate_references_are_rejected(self):
        self.fixture(repeated=True)
        result = self.scan()
        self.assertFalse(result["ok"], result)
        self.assertFalse(result["mapping"])

    def test_same_count_duplicate_references_are_not_zipped(self):
        self.fixture()
        # Three references still match the table count, but one export is missing.
        self.code = self.code[:14] + b"\x48\x8d\x05" + struct.pack(
            "<i", 0x1040 - (0x1200 + 14 + 7))
        result = self.scan()
        self.assertFalse(result["ok"], result)
        self.assertFalse(result["mapping"])

    def test_cache_round_trip_records_complete_identity(self):
        self.fixture()
        result = self.scan()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["schema"], 2)
        for key in ("unityplayer_sha256", "canonical_sha256"):
            self.assertEqual(len(result[key]), 64)
        self.ix.save_cache(result)
        cached = self.load()
        self.assertIsNotNone(cached)
        self.assertTrue(cached["cached"])
        self.assertEqual(cached["mapping"], result["mapping"])

    def test_same_length_changed_canonical_table_invalidates_cache(self):
        self.fixture()
        self.ix.save_cache(self.scan())
        self.table.write_text("\n".join(reversed(self.canonical)), encoding="utf-8")
        self.assertIsNone(self.load())

    def test_renamed_canonical_entry_invalidates_cache(self):
        self.fixture()
        self.ix.save_cache(self.scan())
        names = self.canonical[:-1] + ["il2cpp_replacement"]
        self.table.write_text("\n".join(names), encoding="utf-8")
        self.assertIsNone(self.load())

    def test_changed_unityplayer_invalidates_cache(self):
        self.fixture()
        self.ix.save_cache(self.scan())
        self.player.write_bytes(self.player.read_bytes() + b"changed-player")
        self.assertIsNone(self.load())

    def test_corrupt_cache_is_a_miss(self):
        self.fixture()
        path = Path(self.ix.save_cache(self.scan()))
        for text in ("{broken", "[]", "null", '"not an object"'):
            with self.subTest(payload=text):
                path.write_text(text, encoding="utf-8")
                self.assertIsNone(self.load())

    def test_invalid_mapping_cache_is_a_miss(self):
        self.fixture()
        result = self.scan()
        path = Path(self.ix.save_cache(result))
        malformed = [
            {**result, "schema": 1},
            {**result, "ok": False},
            {**result, "mapping": list(result["mapping"].values())},
            {**result, "mapping": {"il2cpp_wrong_" + str(i): value
                                      for i, value in enumerate(result["mapping"].values())}},
            {**result, "mapping": {name: "" for name in self.canonical}},
            {**result, "mapping": {name: "same_alias" for name in self.canonical}},
        ]
        for payload in malformed:
            with self.subTest(payload=payload):
                path.write_text(json.dumps(payload), encoding="utf-8")
                self.assertIsNone(self.load())


if __name__ == "__main__":
    unittest.main()
