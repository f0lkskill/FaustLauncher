"""Offline regression tests for automatic launcher log severity classification."""

import unittest

from functions.base.log_format import build_line, level_of


class LogClassificationTests(unittest.TestCase):
    def test_monitoring_zero_errors_is_info(self):
        message = "monitoring ... hooks=24/4 error=0 tail=command claimed"
        self.assertEqual(level_of(message), "INFO")
        line = build_line(
            "[WarpHook] " + message,
            site=("host.py", 1, "addons"),
            stamp="2026-01-01 00:00:00.000",
        )
        self.assertIn("[WarpHook] [INFO]", line)
        self.assertNotIn("[ERROR]", line)

    def test_zero_counter_separators_remain_supported(self):
        for message in (
            "error=0", "ERROR = 0", "error:0", "error：0", "error 0",
            "错误：0次", "失败0项", "WARN: 0",
        ):
            with self.subTest(message=message):
                self.assertEqual(level_of(message), "INFO")

    def test_nonzero_and_malformed_counters_are_errors(self):
        for value in ("1", "24", "01", "0.1", "0x1", "0e1", "-1", "unknown"):
            for separator in ("=", ":", "：", " "):
                message = "error" + separator + value
                with self.subTest(message=message):
                    self.assertEqual(level_of(message), "ERROR")

    def test_real_failure_after_zero_counter_is_error(self):
        for message in (
            "monitoring hooks=24/4 error=0 tail=command failed",
            "error=0; error=1", "error:0; ERROR: connection lost",
            "error=0 连接失败", "error=0 无法连接", "error=0 Traceback (most recent call last):",
        ):
            with self.subTest(message=message):
                self.assertEqual(level_of(message), "ERROR")

    def test_other_severities_are_preserved(self):
        for message, expected in (
            ("error=0 warning: fallback", "WARN"),
            ("error=0 debug details", "DEBUG"),
            ("连接失败", "ERROR"),
            ("ERROR: connection lost", "ERROR"),
            ("command failed", "ERROR"),
        ):
            with self.subTest(message=message):
                self.assertEqual(level_of(message), expected)

    def test_explicit_error_level_is_not_downgraded(self):
        line = build_line(
            "error=0", site=("host.py", 1, "addons"), level="ERROR",
            stamp="2026-01-01 00:00:00.000",
        )
        self.assertIn("[ERROR]", line)


if __name__ == "__main__":
    unittest.main()
