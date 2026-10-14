import unittest

from incident_detection.detector import detect_incidents, parse_log


class ParseLogTest(unittest.TestCase):
    def test_parses_fields_and_strips_spaces(self):
        self.assertEqual(parse_log("12, m1, 503, 7"), (12, "m1", 503, 7))


class DetectIncidentsTest(unittest.TestCase):
    def test_part1_sample(self):
        logs = [
            "10, merchant1,500,2",
            "10, merchant2,500,1",
            "15, merchant1,500,2",
            "20, merchant1,500,1",
            "20, merchant2,500,4",
        ]
        self.assertEqual(
            detect_incidents(logs),
            ["20,TRIGGER,merchant1,500", "20,TRIGGER,merchant2,500"],
        )

    def test_below_threshold_does_not_alert(self):
        self.assertEqual(detect_incidents(["0, m1, 500, 2", "5, m1, 500, 2"]), [])

    def test_failures_must_share_status_code(self):
        self.assertEqual(detect_incidents(["0, m1, 500, 3", "1, m1, 503, 3"]), [])

    def test_failures_must_share_merchant(self):
        self.assertEqual(detect_incidents(["0, m1, 500, 3", "1, m2, 500, 3"]), [])

    def test_successes_never_alert(self):
        self.assertEqual(detect_incidents(["0, m1, 200, 100"]), [])

    def test_window_is_inclusive_of_t_minus_29(self):
        logs = ["0, m1, 500, 5", "29, m1, 200, 1", "30, m1, 200, 1"]
        self.assertEqual(detect_incidents(logs), ["0,TRIGGER,m1,500", "30,RESOLVE,m1,500"])

    def test_failures_older_than_window_do_not_count(self):
        self.assertEqual(detect_incidents(["0, m1, 500, 4", "30, m1, 500, 1"]), [])

    def test_active_alert_is_not_retriggered(self):
        logs = ["0, m1, 500, 5", "1, m1, 500, 5", "2, m1, 500, 5"]
        self.assertEqual(detect_incidents(logs), ["0,TRIGGER,m1,500"])

    def test_alert_stays_active_while_window_has_enough_failures(self):
        logs = ["0, m1, 500, 5", "20, m1, 500, 5", "30, m1, 500, 1"]
        self.assertEqual(detect_incidents(logs), ["0,TRIGGER,m1,500"])

    def test_alert_can_retrigger_after_resolve(self):
        logs = ["0, m1, 500, 5", "30, m1, 200, 1", "31, m1, 500, 5"]
        self.assertEqual(
            detect_incidents(logs),
            ["0,TRIGGER,m1,500", "30,RESOLVE,m1,500", "31,TRIGGER,m1,500"],
        )

    def test_status_codes_alert_independently(self):
        logs = ["0, m1, 500, 5", "1, m1, 404, 5", "2, m1, 429, 1"]
        self.assertEqual(detect_incidents(logs), ["0,TRIGGER,m1,500", "1,TRIGGER,m1,404"])

    def test_eviction_resolves_alerts_of_other_merchants(self):
        logs = ["0, a, 500, 5", "40, b, 200, 1"]
        self.assertEqual(detect_incidents(logs), ["0,TRIGGER,a,500", "40,RESOLVE,a,500"])

    def test_same_second_resolve_sorts_before_trigger(self):
        logs = ["0, m1, 500, 5", "30, a, 200, 1", "30, m1, 500, 5"]
        self.assertEqual(
            detect_incidents(logs),
            ["0,TRIGGER,m1,500", "30,RESOLVE,m1,500", "30,TRIGGER,m1,500"],
        )

    def test_output_sorted_by_timestamp_merchant_status(self):
        logs = ["0, b, 500, 5", "0, a, 503, 5", "0, a, 500, 5"]
        self.assertEqual(
            detect_incidents(logs),
            ["0,TRIGGER,a,500", "0,TRIGGER,a,503", "0,TRIGGER,b,500"],
        )


if __name__ == "__main__":
    unittest.main()
