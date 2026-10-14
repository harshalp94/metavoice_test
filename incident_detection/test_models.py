import unittest

from incident_detection.models import AlertEvent, EventType, LogEntry


class LogEntryTest(unittest.TestCase):
    def test_parses_fields_and_strips_spaces(self):
        self.assertEqual(LogEntry.parse("12, m1, 503, 7"), LogEntry(12, "m1", 503, 7))


class AlertEventTest(unittest.TestCase):
    def test_formats_as_csv_record(self):
        self.assertEqual(str(AlertEvent(20, "m1", 500, EventType.TRIGGER)), "20,TRIGGER,m1,500")

    def test_sorts_by_timestamp_merchant_status_then_event_type(self):
        events = [
            AlertEvent(1, "a", 500, EventType.TRIGGER),
            AlertEvent(0, "b", 500, EventType.TRIGGER),
            AlertEvent(0, "a", 503, EventType.TRIGGER),
            AlertEvent(0, "a", 500, EventType.TRIGGER),
            AlertEvent(0, "a", 500, EventType.RESOLVE),
        ]
        self.assertEqual(
            [str(event) for event in sorted(events)],
            ["0,RESOLVE,a,500", "0,TRIGGER,a,500", "0,TRIGGER,a,503", "0,TRIGGER,b,500", "1,TRIGGER,a,500"],
        )


if __name__ == "__main__":
    unittest.main()
