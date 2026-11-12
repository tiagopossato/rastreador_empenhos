import tempfile
import threading
import unittest
from pathlib import Path

from pncp_tracker.process_lock import (
    DEFAULT_LOCK_TIMEOUT,
    interprocess_lock,
    lock_path_for,
)


class ProcessLockTests(unittest.TestCase):
    def test_lock_path_is_shared_in_private_directory(self):
        index_path = Path("reports") / "indice_relatorios.json"

        self.assertEqual(
            lock_path_for(index_path),
            Path("reports").parent / ".private" / "report_update.lock",
        )

    def test_default_timeout_is_finite(self):
        self.assertEqual(DEFAULT_LOCK_TIMEOUT, 300.0)

    def test_negative_timeout_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "não pode ser negativo"):
                with interprocess_lock(Path(temp_dir) / "job.lock", timeout=-1):
                    pass

    def test_lock_timeout_is_reported_when_another_operation_holds_the_lock(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / "job.lock"

            with interprocess_lock(lock_path):
                with self.assertRaisesRegex(TimeoutError, "timeout do lock"):
                    with interprocess_lock(lock_path, timeout=0):
                        pass

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
