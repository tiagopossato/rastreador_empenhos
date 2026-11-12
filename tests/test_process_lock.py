import tempfile
import threading
import unittest
from pathlib import Path

from pncp_tracker.process_lock import interprocess_lock


class ProcessLockTests(unittest.TestCase):
    def test_second_thread_waits_until_lock_is_released(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / "job.lock"
            waiting = threading.Event()
            acquired = threading.Event()

            def wait_for_lock():
                waiting.set()
                with interprocess_lock(lock_path):
                    acquired.set()

            with interprocess_lock(lock_path):
                thread = threading.Thread(target=wait_for_lock)
                thread.start()
                self.assertTrue(waiting.wait(1))
                self.assertFalse(acquired.wait(0.05))

            self.assertTrue(acquired.wait(2))
            thread.join(2)
            self.assertFalse(thread.is_alive())

    def test_lock_is_released_when_the_critical_section_raises(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / "job.lock"

            with self.assertRaises(RuntimeError):
                with interprocess_lock(lock_path):
                    raise RuntimeError("falha simulada")

            with interprocess_lock(lock_path):
                pass


if __name__ == "__main__":
    unittest.main()
