from collections import defaultdict

from incident_detection.models import AlertEvent, EventType, LogEntry
from incident_detection.rules import ImpactRule, VolumeRule
from incident_detection.window import MerchantWindow

WINDOW_SECONDS = 30
DEFAULT_TRIGGER_RULE = VolumeRule(5) & ImpactRule(1)


class IncidentDetector:
    """Stateful alert tracker for a stream of log entries.

    An alert per (merchant_id, status_code) triggers when `trigger_rule` holds and
    resolves when `resolve_rule` holds (by default, when the trigger rule no longer
    holds). A merchant's alerts only change state when that merchant logs.
    """

    def __init__(self, trigger_rule=DEFAULT_TRIGGER_RULE, resolve_rule=None,
                 window_seconds=WINDOW_SECONDS):
        self._trigger_rule = trigger_rule
        self._resolve_rule = resolve_rule or ~trigger_rule
        self._window_seconds = window_seconds
        self._windows = {}
        self._active = defaultdict(set)

    def process(self, entry):
        """Add a log entry and return the alert events it causes."""
        window = self._windows.setdefault(entry.merchant_id, MerchantWindow(self._window_seconds))
        window.add(entry)

        active = self._active[entry.merchant_id]
        events = []
        for code in window.failure_codes() | active:
            if code in active:
                if self._resolve_rule.is_met(window, code):
                    active.discard(code)
                    events.append(AlertEvent(entry.timestamp, entry.merchant_id, code, EventType.RESOLVE))
            elif self._trigger_rule.is_met(window, code):
                active.add(code)
                events.append(AlertEvent(entry.timestamp, entry.merchant_id, code, EventType.TRIGGER))
        return events


def detect_incidents(logs, detector=None):
    detector = detector or IncidentDetector()
    events = [event for line in logs for event in detector.process(LogEntry.parse(line))]
    return [str(event) for event in sorted(events)]
