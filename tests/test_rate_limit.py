import threading
import unittest
from unittest.mock import patch

from pncp_tracker.rate_limit import RateLimiter


class RateLimiterTests(unittest.TestCase):
    def test_spacing_is_applied_between_calls(self):
        limiter = RateLimiter(600)
        with (
            patch("pncp_tracker.rate_limit.time.monotonic", side_effect=[10.0, 10.0, 10.02, 10.2]),
            patch("pncp_tracker.rate_limit.time.sleep") as dormir,
        ):
            limiter.aguardar()
            limiter.aguardar()

        dormir.assert_called_once()
        self.assertAlmostEqual(dormir.call_args.args[0], 0.08)

    def test_limit_is_shared_between_threads(self):
        limiter = RateLimiter(600)
        chamadas = []

        def registrar():
            limiter.aguardar()
            chamadas.append(threading.current_thread().name)

        with patch("pncp_tracker.rate_limit.time.sleep") as dormir:
            threads = [threading.Thread(target=registrar) for _ in range(5)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.assertEqual(len(chamadas), 5)
        self.assertEqual(dormir.call_count, 4)

    def test_disabled_limiter_does_not_wait(self):
        limiter = RateLimiter(1)
        limiter.desativar()
        with patch("pncp_tracker.rate_limit.time.sleep") as dormir:
            limiter.aguardar()
            limiter.aguardar()

        dormir.assert_not_called()

    def test_invalid_limit_is_rejected(self):
        with self.assertRaises(ValueError):
            RateLimiter(0)

    def test_interval_matches_the_configured_rate(self):
        self.assertAlmostEqual(RateLimiter(600).intervalo, 0.1)
        self.assertAlmostEqual(RateLimiter(240).intervalo, 0.25)


if __name__ == "__main__":
    unittest.main()
