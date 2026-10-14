import unittest

from incident_detection.detector import detect_incidents, parse_log


def at_least(threshold):
    return lambda status_code, code_count, merchant_total: code_count >= threshold


def error_rate_at_least(rate):
    return lambda status_code, code_count, merchant_total: code_count / merchant_total >= rate


class ParseLogTest(unittest.TestCase):
    def test_parses_fields_and_strips_spaces(self):
        self.assertEqual(parse_log("12, m1, 503, 7"), (12, "m1", 503, 7))


class DetectIncidentsTest(unittest.TestCase):
    def test_window_is_inclusive_of_t_minus_29(self):
        logs = ["0, m1, 500, 5", "29, m1, 200, 1", "30, m1, 200, 1"]
        self.assertEqual(
            detect_incidents(logs, at_least(5)),
            ["0,TRIGGER,m1,500", "30,RESOLVE,m1,500"],
        )

    def test_active_alert_is_not_retriggered(self):
        logs = ["0, m1, 500, 5", "1, m1, 500, 5", "2, m1, 500, 5"]
        self.assertEqual(detect_incidents(logs, at_least(5)), ["0,TRIGGER,m1,500"])

    def test_alert_can_retrigger_after_resolve(self):
        logs = ["0, m1, 500, 5", "30, m1, 200, 1", "31, m1, 500, 5"]
        self.assertEqual(
            detect_incidents(logs, at_least(5)),
            ["0,TRIGGER,m1,500", "30,RESOLVE,m1,500", "31,TRIGGER,m1,500"],
        )

    def test_status_codes_alert_independently(self):
        logs = ["0, m1, 500, 5", "1, m1, 404, 5", "2, m1, 429, 1"]
        self.assertEqual(
            detect_incidents(logs, at_least(5)),
            ["0,TRIGGER,m1,500", "1,TRIGGER,m1,404"],
        )

    def test_success_status_never_alerts(self):
        self.assertEqual(detect_incidents(["0, m1, 200, 100"], at_least(1)), [])

    def test_eviction_resolves_alerts_of_other_merchants(self):
        logs = ["0, a, 500, 5", "40, b, 200, 1"]
        self.assertEqual(
            detect_incidents(logs, at_least(5)),
            ["0,TRIGGER,a,500", "40,RESOLVE,a,500"],
        )

    def test_evicting_successes_can_trigger(self):
        logs = ["0, m1, 200, 10", "20, m1, 500, 1", "30, m1, 500, 1"]
        self.assertEqual(detect_incidents(logs, error_rate_at_least(0.5)), ["30,TRIGGER,m1,500"])

    def test_same_second_flip_sorts_resolve_before_trigger(self):
        logs = ["10, m1, 500, 1", "10, m1, 200, 3"]
        self.assertEqual(
            detect_incidents(logs, error_rate_at_least(0.5)),
            ["10,RESOLVE,m1,500", "10,TRIGGER,m1,500"],
        )

    def test_output_sorted_by_timestamp_merchant_status(self):
        logs = ["0, b, 500, 5", "0, a, 503, 5", "0, a, 500, 5"]
        self.assertEqual(
            detect_incidents(logs, at_least(5)),
            ["0,TRIGGER,a,500", "0,TRIGGER,a,503", "0,TRIGGER,b,500"],
        )


if __name__ == "__main__":
    unittest.main()
