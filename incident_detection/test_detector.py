import io
import unittest
from collections import defaultdict, deque
from contextlib import redirect_stdout

from incident_detection.detector import (
    SAMPLES, add_to_window, alert_changes, detect_incidents, find_incidents, is_incident, read_logs,
    run, run_samples,
)


class SampleTest(unittest.TestCase):
    def test_samples(self):
        for name, (logs, expected) in SAMPLES.items():
            with self.subTest(name):
                self.assertEqual(detect_incidents(logs), expected)


class RunnerTest(unittest.TestCase):
    def test_run_traces_steps_and_returns_output(self):
        logs, expected = SAMPLES["part3"]
        out = io.StringIO()
        with redirect_stdout(out):
            result = run(logs)
        self.assertEqual(result, expected)
        self.assertIn("window: {200: 1, 500: 6}  active: [500]", out.getvalue())
        self.assertIn("-> 45,RESOLVE,merchant1,500", out.getvalue())

    def test_debug_off_prints_nothing(self):
        out = io.StringIO()
        with redirect_stdout(out):
            detect_incidents(SAMPLES["part1"][0])
        self.assertEqual(out.getvalue(), "")

    def test_run_samples_passes(self):
        with redirect_stdout(io.StringIO()):
            self.assertTrue(run_samples())


class ReadingTest(unittest.TestCase):
    def test_reads_comma_and_space_separated_lines_and_skips_blanks(self):
        self.assertEqual(
            read_logs("\n  12, m1,503,7\n\n13 m2 200 1\n"),
            [(12, "m1", 503, 7), (13, "m2", 200, 1)],
        )

    def test_reads_list_of_lines(self):
        self.assertEqual(read_logs(["10, merchant1,500,6"]), [(10, "merchant1", 500, 6)])

    def test_reads_list_of_field_lists(self):
        self.assertEqual(
            read_logs([["10", " merchant1", "500", "6"], (11, "merchant1", 200, 1)]),
            [(10, "merchant1", 500, 6), (11, "merchant1", 200, 1)],
        )

    def test_empty_input(self):
        self.assertEqual(detect_incidents(""), [])


class ProcessingTest(unittest.TestCase):
    def test_keeps_records_at_t_minus_29_and_evicts_older(self):
        window, counts = deque(), defaultdict(int)
        add_to_window(window, counts, (0, "m1", 500, 5))
        add_to_window(window, counts, (29, "m1", 200, 1))
        self.assertEqual(counts[500], 5)
        add_to_window(window, counts, (30, "m1", 200, 1))
        self.assertEqual(counts[500], 0)
        self.assertEqual(counts[200], 2)
        self.assertEqual(list(window), [(29, "m1", 200, 1), (30, "m1", 200, 1)])

    def test_accepts_unconverted_string_records(self):
        window, counts = deque(), defaultdict(int)
        add_to_window(window, counts, "10, merchant1,500,2".split(","))
        add_to_window(window, counts, "12 merchant1 500 3")
        self.assertEqual(counts[500], 5)
        self.assertEqual(list(window), [(10, "merchant1", 500, 2), (12, "merchant1", 500, 3)])


class ResolutionTest(unittest.TestCase):
    def test_volume_threshold_is_inclusive(self):
        self.assertFalse(is_incident(4, 0))
        self.assertTrue(is_incident(5, 0))

    def test_impact_threshold_is_exclusive(self):
        self.assertFalse(is_incident(6, 600))
        self.assertTrue(is_incident(6, 599))

    def test_find_incidents_checks_each_error_code_against_successes(self):
        self.assertEqual(find_incidents({200: 100, 500: 5, 503: 1, 404: 0}), {500})
        self.assertEqual(find_incidents({200: 1000, 500: 10}), set())

    def test_alert_changes_triggers_new_and_resolves_recovered(self):
        self.assertEqual(
            alert_changes({500, 503}, {500, 404}, 7, "m1"),
            [(7, "m1", 404, "TRIGGER"), (7, "m1", 503, "RESOLVE")],
        )

    def test_alert_changes_is_empty_while_alerts_continue(self):
        self.assertEqual(alert_changes({500}, {500}, 7, "m1"), [])


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


if __name__ == "__main__":
    unittest.main()
