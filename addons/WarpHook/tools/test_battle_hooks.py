"""Offline regressions for the post-update battle hook entry points."""

import ast
import importlib.util
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
LIVE = ROOT / "warphook" / "live.py"
OBJECTS = ROOT / "warphook" / "objects.py"
FIELDS = ROOT / "warphook" / "fields.py"


def parse(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def method(tree, class_name, method_name):
    cls = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    return next(
        node for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == method_name
    )


def strings(node):
    return {
        item.value for item in ast.walk(node)
        if isinstance(item, ast.Constant) and isinstance(item.value, str)
    }


def ints(node):
    return {
        item.value for item in ast.walk(node)
        if isinstance(item, ast.Constant) and isinstance(item.value, int)
    }


def call_target(node):
    if not isinstance(node, ast.Call) or not node.args:
        return set()
    return {
        item.value for item in ast.walk(node.args[0])
        if isinstance(item, ast.Constant) and isinstance(item.value, str)
    }


class BattleHookTests(unittest.TestCase):
    def test_round_hook_uses_stage_controller_post(self):
        tree = parse(LIVE)
        live_hooks = method(tree, "Live", "_live_hooks")
        hooks = [
            node for node in ast.walk(live_hooks)
            if isinstance(node, ast.Dict)
        ]
        round_hook = next(
            hook for hook in hooks
            if "StageController" in strings(hook)
        )
        keys = {
            key.value: value
            for key, value in zip(round_hook.keys, round_hook.values)
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }

        self.assertEqual(keys["klass"].value, "StageController")
        self.assertEqual(keys["method"].value, "StartRound")
        self.assertEqual(keys["argc"].value, 0)
        self.assertEqual(keys["event"].value, 34)
        self.assertEqual(keys["when"].value, 1)
        self.assertNotIn("cache", keys)
        self.assertNotIn("OnRoundStart_Model", strings(live_hooks))

    def test_poll_round_queries_new_hit_key(self):
        poll = method(parse(LIVE), "Live", "_poll_round")
        calls = [
            node for node in ast.walk(poll)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "hits"
        ]
        self.assertEqual(len(calls), 1)
        method_kw = next(
            keyword for keyword in calls[0].keywords
            if keyword.arg == "method"
        )
        self.assertEqual(method_kw.value.value, "StartRound")

    def test_manager_uses_non_generic_static_accessor(self):
        tree = parse(OBJECTS)
        bind = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "bind_manager"
        )
        defaults = {
            arg.arg: default
            for arg, default in zip(bind.args.args[-len(bind.args.defaults):],
                                    bind.args.defaults)
        }

        self.assertIsInstance(defaults["klass"], ast.Constant)
        self.assertIsNone(defaults["klass"].value)
        self.assertIsInstance(defaults["method"], ast.Constant)
        self.assertIsNone(defaults["method"].value)
        self.assertIn(
            "SingletonBehaviorCollector::get_BattleObjectManager",
            strings(tree),
        )
        for path in (OBJECTS, LIVE):
            calls = [
                node for node in ast.walk(parse(path))
                if isinstance(node, ast.Call)
            ]
            targets = set().union(*(call_target(call) for call in calls))
            self.assertNotIn("BattleObjectManager::get_Instance", targets)

    def test_battle_unit_model_offsets_match_current_dump(self):
        spec = importlib.util.spec_from_file_location("warphook_fields", FIELDS)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        table = module.FIELD_TABLE["BattleUnitModel"]
        expected = {
            "_instanceID": 0x70,
            "_originID": 0x74,
            "_actionList": 0xB0,
            "_buffDetail": 0x100,
            "_formationPos": 0x110,
            "_state": 0x168,
            "_changeStat": 0x180,
            "_thisTurnIntSpeedOnCmdPhase": 0x1A4,
        }

        for name, offset in expected.items():
            self.assertEqual(table[name]["off"], offset, name)
        self.assertEqual(module.FIELD_TABLE["CharacterState"]["_hp"]["off"], 0x148)
        self.assertEqual(
            module.FIELD_TABLE["BuffDetail"]["_grantedBuffList"]["off"], 0x10)
        self.assertEqual(
            module.FIELD_TABLE["BuffModel"]["_buffData"]["off"], 0x68)


if __name__ == "__main__":
    unittest.main()
