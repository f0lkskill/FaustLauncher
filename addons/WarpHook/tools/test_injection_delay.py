"""Offline regression for the WarpHook injection-delay setting."""

import math
import sys
import threading
from pathlib import Path

ADDON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ADDON_ROOT))

from warphook import base, env  # noqa: E402


class FakeManager:
    def __init__(self, settings):
        self.settings = settings

    def get_addon_info(self, _name):
        return {"settings": self.settings}


def use_setting(value, present=True):
    settings = {}
    if present:
        settings[base.INJECT_DELAY_SETTING] = value
    env.ADDON_NAME = "WarpHook"
    env.ADDON_MANAGER = FakeManager(settings)


def check_value(raw, expected):
    use_setting(raw)
    actual = base.injection_delay_seconds()
    assert math.isclose(actual, expected), (raw, actual, expected)


def main():
    env.ADDON_NAME = "WarpHook"
    env.ADDON_MANAGER = None
    assert base.injection_delay_seconds() == base.DEFAULT_INJECT_DELAY_SECONDS

    use_setting(None, present=False)
    assert base.injection_delay_seconds() == base.DEFAULT_INJECT_DELAY_SECONDS

    check_value(3, 3.0)
    check_value("2.5", 2.5)
    check_value(0, 0.0)
    check_value(False, base.DEFAULT_INJECT_DELAY_SECONDS)
    check_value(-1, base.DEFAULT_INJECT_DELAY_SECONDS)
    check_value(base.MAX_INJECT_DELAY_SECONDS + 1,
                base.DEFAULT_INJECT_DELAY_SECONDS)
    check_value("not-a-number", base.DEFAULT_INJECT_DELAY_SECONDS)
    check_value(float("nan"), base.DEFAULT_INJECT_DELAY_SECONDS)
    check_value(float("inf"), base.DEFAULT_INJECT_DELAY_SECONDS)

    use_setting(0)
    called = []
    assert base.wait_for_injection_delay(on_wait=called.append) is True
    assert called == []

    use_setting(0.05)
    stop = threading.Event()
    stop.set()
    assert base.wait_for_injection_delay(stop) is False

    print("PASS injection delay: default, parsing, range and cancellation")


if __name__ == "__main__":
    main()
