"""M2 lifecycle admission and shutdown behavior."""
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from railwatch_bridge import RailWatchBridge
from railwatch_orders import OrderIntent, OrderResult
from railwatch_task import MonitorTask


class LifecycleGateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.bridge = RailWatchBridge(data_dir=self.directory.name)

    def test_install_rejects_active_task_and_pending_order(self):
        task = MonitorTask({})
        self.bridge._task = task
        result = self.bridge.prepare_shutdown("install")
        self.assertFalse(result["ready"])
        self.assertEqual(result["activity"]["run_id"], task.run_id)
        self.assertFalse(self.bridge._admission_closed)
        task.done.set()

        intent = OrderIntent("regular", "G101", "2026-09-24", "北京", "上海", "二等座", ("张三",), "18:00")
        self.bridge.order_journal.begin("run", intent, {})
        self.bridge.order_journal.record(intent, OrderResult("pending_payment", order_id="TEST123", evidence={"matched": True}))
        result = self.bridge.prepare_shutdown("install")
        self.assertFalse(result["ready"])
        self.assertTrue(result["activity"]["unresolved_order"])

    def test_quit_blocks_new_browser_work_until_stopped_and_flushed(self):
        task = MonitorTask({})
        self.bridge._task = task
        result = {}
        thread = threading.Thread(target=lambda: result.update(self.bridge.prepare_shutdown("quit")))
        thread.start()
        self.assertTrue(task.cancel.wait(2))
        with self.assertRaises(RuntimeError):
            self.bridge.open_login()
        task.done.set()
        thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertTrue(result["ready"])
        self.assertTrue(self.bridge._admission_closed)
        self.bridge.cancel_shutdown()
        self.assertFalse(self.bridge._admission_closed)

    def test_install_gate_is_atomic_with_browser_admission(self):
        result = self.bridge.prepare_shutdown("install")
        self.assertTrue(result["ready"])
        with self.assertRaises(RuntimeError):
            self.bridge.open_login()
        self.bridge.cancel_shutdown()

    def test_quit_releases_controlled_browser(self):
        driver = Mock()
        self.bridge.driver = driver
        result = self.bridge.prepare_shutdown("quit")
        self.assertTrue(result["ready"])
        self.assertIsNone(self.bridge.driver)
        driver.quit.assert_called_once()

    def test_stop_timeout_reopens_admission(self):
        task = MonitorTask({})
        self.bridge._task = task
        with patch.object(task.done, "wait", return_value=False):
            result = self.bridge.prepare_shutdown("quit")
        self.assertFalse(result["ready"])
        self.assertIn("超时", result["reason"])
        self.assertFalse(self.bridge._admission_closed)


if __name__ == "__main__":
    unittest.main()
