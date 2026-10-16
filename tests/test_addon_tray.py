"""Headless regression tests using real pystray menu descriptors.
Run: python -m unittest discover -s tests -p 'test_addon_tray.py'
"""
import ast
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

import pystray

ROOT = Path(__file__).resolve().parents[1]


def load_definitions(path, names, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding='utf-8'))
    nodes = [n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name in names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), path, 'exec'), namespace)
    return namespace


class FakeIcon:
    def __init__(self, name, image, title, menu):
        self.menu = menu
        self.update_menu = Mock()
        self.run = Mock()


class AddonTrayTests(unittest.TestCase):
    def setUp(self):
        from typing import Any, Dict, List, Optional
        ns = dict(os=os, sys=sys, json=json, ModuleType=types.ModuleType,
                  Any=Any, Dict=Dict, List=List, Optional=Optional,
                  CustomTranslateSource=object)
        load_definitions('functions/extension/addon/addon_utils.py',
                         ['AddonManager', '_ScratchAddonManager'], ns)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        with patch.object(ns['AddonManager'], 'scan_addons'):
            self.manager = ns['AddonManager'](app=types.SimpleNamespace())
        self.manager.get_all_addons = lambda: []
        self.core = types.SimpleNamespace(addon_manager=self.manager, _on_reload_addons=Mock())

    def create_tray(self, kind):
        if kind == 'web':
            ns = dict(os=os, threading=types.SimpleNamespace(Thread=Mock()),
                      _PROJECT_ROOT=self.tmp.name)
            load_definitions('functions/pages/app/app_web.py', ['_start_tray'], ns)
            with patch.object(pystray, 'Icon', FakeIcon), patch.dict(sys.modules, {'winreg': None}), \
                    patch('ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID'):
                return ns['_start_tray'](self.core, None, Mock())
        tree = ast.parse((ROOT / 'functions/pages/app/app_ui.py').read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and any(
            isinstance(m, ast.FunctionDef) and m.name == 'init_tray' for m in n.body))
        method = next(m for m in cls.body if isinstance(m, ast.FunctionDef) and m.name == 'init_tray')
        ns = dict(pystray=pystray, Image=types.SimpleNamespace(open=Mock()), Thread=Mock())
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<init_tray>', 'exec'), ns)
        app = types.SimpleNamespace(core=self.core, root=Mock())
        self.manager.app = app
        with patch.object(pystray, 'Icon', FakeIcon):
            ns['init_tray'](app)
        return app.tray

    def test_both_frontends_expose_dynamic_nested_custom_menu(self):
        for kind in ['web', 'tk']:
            with self.subTest(kind=kind):
                self.manager.clear_custom_tray_items()
                called = []
                nested = pystray.MenuItem('Settings', pystray.Menu(
                    pystray.MenuItem('Toggle', lambda: called.append(True), checked=lambda _: True)))
                self.manager.register_tray_item(nested)
                tray = self.create_tray(kind)
                parent = next(item for item in tray.menu if item.text == '插件')
                self.assertIsInstance(parent.submenu, pystray.Menu)
                self.assertIn(nested, list(parent.submenu))
                child = list(nested.submenu)[0]
                self.assertTrue(child.checked)
                child(None)
                self.assertEqual(called, [True])
                late = pystray.MenuItem('Late registration', lambda: None)
                self.manager.register_tray_item(late)
                tray.update_menu.assert_called()
                self.assertIn(late, list(parent.submenu))
                self.assertEqual(list(parent.submenu).count(late), 1)
                self.manager.clear_custom_tray_items()
                self.assertNotIn(nested, list(parent.submenu))
                self.assertNotIn(late, list(parent.submenu))

    def test_legacy_append_refreshes_after_load_and_reload_removes_items(self):
        folder = Path(self.tmp.name)
        (folder / 'scr.py').write_text("import pystray\nADDON_ARG['AddonManager'].menu_items.append(pystray.MenuItem('Legacy', lambda: None))", encoding='utf-8')
        self.manager.get_addon_info = lambda _: {'settings': {'enable': True}}
        self.manager.get_addon_path = lambda _: str(folder)
        tray = self.create_tray('web')
        self.assertTrue(self.manager.run_addon('example'))
        tray.update_menu.assert_called()
        self.assertEqual(len(self.manager.get_custom_tray_items()), 1)
        self.manager.scan_addons = Mock()
        self.manager.run_all_addon = Mock()
        self.assertTrue(self.manager.reload_all_addons())
        self.assertEqual(self.manager.get_custom_tray_items(), [])
        self.manager.run_all_addon.assert_called_once()


if __name__ == '__main__':
    unittest.main()
