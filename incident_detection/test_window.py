import unittest

from incident_detection.models import LogEntry
from incident_detection.window import MerchantWindow


class MerchantWindowTest(unittest.TestCase):
    def test_accumulates_counts_per_status_code(self):
        window = MerchantWindow(30)
        window.add(LogEntry(0, "m1", 500, 2))
        window.add(LogEntry(1, "m1", 500, 3))
        window.add(LogEntry(2, "m1", 200, 10))
        self.assertEqual(window.count(500), 5)
        self.assertEqual(window.success_count, 10)
        self.assertEqual(window.failure_codes(), {500})

    def test_keeps_entries_at_t_minus_29_and_evicts_older(self):
        window = MerchantWindow(30)
        window.add(LogEntry(0, "m1", 500, 5))
        window.add(LogEntry(29, "m1", 200, 1))
        self.assertEqual(window.count(500), 5)
        window.add(LogEntry(30, "m1", 200, 1))
        self.assertEqual(window.count(500), 0)
        self.assertEqual(window.failure_codes(), set())


if __name__ == "__main__":
    unittest.main()
