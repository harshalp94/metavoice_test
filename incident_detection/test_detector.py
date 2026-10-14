import unittest
from collections import defaultdict, deque

from incident_detection.detector import (
    add_to_window, all_of, any_of, detect_incidents, impact_rule, negate, parse_log, split_logs,
    volume_rule,
)


class SampleTest(unittest.TestCase):
    def test_part1_sample(self):
        logs = """
            10, merchant1,500,2
            10, merchant2,500,1
            15, merchant1,500,2
            20, merchant1,500,1
            20, merchant2,500,4
        """
        self.assertEqual(
            detect_incidents(logs),
            ["20,TRIGGER,merchant1,500", "20,TRIGGER,merchant2,500"],
        )

    def test_part2_sample(self):
        logs = """
            10, merchant1,200,600
            12, merchant1,500,6
            15, merchant2,200,599
            16, merchant2,500,6
        """
        self.assertEqual(detect_incidents(logs), ["16,TRIGGER,merchant2,500"])

    def test_part3_sample(self):
        logs = """
            10, merchant1,500,6
            16, merchant2,500,6
            45, merchant1,200,1
            45, merchant2,200,1
        """
        self.assertEqual(
            detect_incidents(logs),
            ["10,TRIGGER,merchant1,500", "16,TRIGGER,merchant2,500", "45,RESOLVE,merchant1,500"],
        )


class ParsingTest(unittest.TestCase):
    def test_parses_comma_separated_record(self):
        self.assertEqual(parse_log("12, m1,503,7"), (12, "m1", 503, 7))

    def test_parses_space_separated_record(self):
        self.assertEqual(parse_log("12 m1 503 7"), (12, "m1", 503, 7))

    def test_splits_multiline_string_and_skips_blank_lines(self):
        self.assertEqual(split_logs("\n  1, a,500,1\n\n2, b,200,3\n"), ["  1, a,500,1", "2, b,200,3"])

    def test_accepts_list_of_records(self):
        logs = ["10, merchant1,500,6", "16, merchant2,500,6"]
        self.assertEqual(
            detect_incidents(logs),
            ["10,TRIGGER,merchant1,500", "16,TRIGGER,merchant2,500"],
        )

    def test_empty_input(self):
        self.assertEqual(detect_incidents(""), [])


class WindowTest(unittest.TestCase):
    def test_keeps_records_at_t_minus_29_and_evicts_older(self):
        window, counts = deque(), defaultdict(int)
        add_to_window(window, counts, 0, 500, 5)
        add_to_window(window, counts, 29, 200, 1)
        self.assertEqual(dict(counts), {500: 5, 200: 1})
        add_to_window(window, counts, 30, 200, 1)
        self.assertEqual(dict(counts), {200: 2})


def counts_with(failures, successes):
    return {500: failures, 200: successes}


class RuleTest(unittest.TestCase):
    def test_volume_threshold_is_inclusive(self):
        self.assertFalse(volume_rule(5)(counts_with(4, 0), 500))
        self.assertTrue(volume_rule(5)(counts_with(5, 0), 500))

    def test_impact_threshold_is_exclusive(self):
        self.assertFalse(impact_rule(1)(counts_with(6, 600), 500))
        self.assertTrue(impact_rule(1)(counts_with(6, 599), 500))

    def test_no_successes_is_full_impact(self):
        self.assertTrue(impact_rule(1)(counts_with(1, 0), 500))

    def test_all_of_requires_both(self):
        rule = all_of(volume_rule(5), impact_rule(1))
        self.assertFalse(rule(counts_with(4, 0), 500))
        self.assertFalse(rule(counts_with(6, 600), 500))
        self.assertTrue(rule(counts_with(6, 599), 500))

    def test_any_of_requires_either(self):
        rule = any_of(volume_rule(100), impact_rule(1))
        self.assertTrue(rule(counts_with(6, 0), 500))
        self.assertFalse(rule(counts_with(6, 600), 500))

    def test_negate(self):
        self.assertTrue(negate(volume_rule(5))(counts_with(4, 0), 500))


class TriggerTest(unittest.TestCase):
    def test_below_volume_does_not_alert(self):
        self.assertEqual(detect_incidents("0, m1,500,2\n5, m1,500,2"), [])

    def test_failures_must_share_status_code(self):
        self.assertEqual(detect_incidents("0, m1,500,3\n1, m1,503,3"), [])

    def test_failures_must_share_merchant(self):
        self.assertEqual(detect_incidents("0, m1,500,3\n1, m2,500,3"), [])

    def test_successes_never_alert(self):
        self.assertEqual(detect_incidents("0, m1,200,100"), [])

    def test_impact_of_exactly_one_percent_does_not_alert(self):
        self.assertEqual(detect_incidents("0, m1,200,500\n1, m1,500,5"), [])

    def test_impact_counts_only_successes_in_window(self):
        self.assertEqual(detect_incidents("0, m1,200,1000\n30, m1,500,5"), ["30,TRIGGER,m1,500"])

    def test_failures_older_than_window_do_not_count(self):
        self.assertEqual(detect_incidents("0, m1,500,4\n30, m1,500,1"), [])

    def test_successes_leaving_window_trigger_on_next_merchant_log(self):
        logs = """
            0, m1,200,1000
            20, m1,500,5
            25, m2,200,1
            30, m1,404,1
        """
        self.assertEqual(detect_incidents(logs), ["30,TRIGGER,m1,500"])

    def test_active_alert_is_not_retriggered(self):
        logs = "0, m1,500,5\n1, m1,500,5\n2, m1,500,5"
        self.assertEqual(detect_incidents(logs), ["0,TRIGGER,m1,500"])

    def test_status_codes_alert_independently(self):
        logs = "0, m1,500,5\n1, m1,404,5\n2, m1,429,1"
        self.assertEqual(detect_incidents(logs), ["0,TRIGGER,m1,500", "1,TRIGGER,m1,404"])


class ResolveTest(unittest.TestCase):
    def test_window_is_inclusive_of_t_minus_29(self):
        logs = "0, m1,500,5\n29, m1,200,1\n30, m1,200,1"
        self.assertEqual(detect_incidents(logs), ["0,TRIGGER,m1,500", "30,RESOLVE,m1,500"])

    def test_alert_stays_active_while_window_has_enough_failures(self):
        logs = "0, m1,500,5\n20, m1,500,5\n30, m1,500,1"
        self.assertEqual(detect_incidents(logs), ["0,TRIGGER,m1,500"])

    def test_resolves_when_impact_drops(self):
        logs = "0, m1,500,5\n1, m1,200,500"
        self.assertEqual(detect_incidents(logs), ["0,TRIGGER,m1,500", "1,RESOLVE,m1,500"])

    def test_other_merchants_logs_do_not_resolve(self):
        self.assertEqual(detect_incidents("0, a,500,5\n40, b,200,1"), ["0,TRIGGER,a,500"])

    def test_any_log_for_merchant_resolves_all_its_stale_alerts(self):
        logs = "0, m1,500,5\n1, m1,404,5\n40, m1,429,1"
        self.assertEqual(
            detect_incidents(logs),
            ["0,TRIGGER,m1,500", "1,TRIGGER,m1,404", "40,RESOLVE,m1,404", "40,RESOLVE,m1,500"],
        )

    def test_alert_can_retrigger_after_resolve(self):
        logs = "0, m1,500,5\n30, m1,200,1\n31, m1,500,5"
        self.assertEqual(
            detect_incidents(logs),
            ["0,TRIGGER,m1,500", "30,RESOLVE,m1,500", "31,TRIGGER,m1,500"],
        )

    def test_same_second_resolve_sorts_before_trigger(self):
        logs = "0, m1,500,5\n30, m1,200,1\n30, m1,500,5"
        self.assertEqual(
            detect_incidents(logs),
            ["0,TRIGGER,m1,500", "30,RESOLVE,m1,500", "30,TRIGGER,m1,500"],
        )

    def test_output_sorted_by_timestamp_merchant_status(self):
        logs = "0, b,500,5\n0, a,503,5\n0, a,500,5"
        self.assertEqual(
            detect_incidents(logs),
            ["0,TRIGGER,a,500", "0,TRIGGER,a,503", "0,TRIGGER,b,500"],
        )


class ConfigurationTest(unittest.TestCase):
    def test_custom_trigger_rule(self):
        self.assertEqual(
            detect_incidents("0, m1,500,3", trigger_rule=volume_rule(3)),
            ["0,TRIGGER,m1,500"],
        )

    def test_custom_window_size(self):
        self.assertEqual(
            detect_incidents("0, m1,500,5\n10, m1,200,1", window_seconds=10),
            ["0,TRIGGER,m1,500", "10,RESOLVE,m1,500"],
        )

    def test_separate_resolve_rule(self):
        # Hysteresis: trigger at 5 failures, only resolve once below 2.
        logs = "0, m1,500,5\n30, m1,500,2\n40, m1,500,1\n60, m1,200,1"
        self.assertEqual(
            detect_incidents(logs, trigger_rule=volume_rule(5), resolve_rule=negate(volume_rule(2))),
            ["0,TRIGGER,m1,500", "60,RESOLVE,m1,500"],
        )


if __name__ == "__main__":
    unittest.main()
