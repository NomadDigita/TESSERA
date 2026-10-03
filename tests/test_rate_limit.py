import unittest

from tessera.rate_limit import MemoryRateLimiter


class RateLimitTests(unittest.TestCase):
    def test_fixed_window_enforces_and_resets(self):
        clock = [60]
        limiter = MemoryRateLimiter(clock=lambda: clock[0])
        self.assertTrue(limiter.consume("login:user", 2, 60).allowed)
        self.assertTrue(limiter.consume("login:user", 2, 60).allowed)
        denied = limiter.consume("login:user", 2, 60)
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.remaining, 0)
        clock[0] = 120
        self.assertTrue(limiter.consume("login:user", 2, 60).allowed)


if __name__ == "__main__":
    unittest.main()
