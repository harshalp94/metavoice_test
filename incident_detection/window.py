from collections import defaultdict, deque

from incident_detection.models import SUCCESS_STATUS


class MerchantWindow:
    """Per-status-code transaction counts for one merchant over a sliding window.

    The window for a log at timestamp T covers [T - size + 1, T].
    """

    def __init__(self, size, success_status=SUCCESS_STATUS):
        self._size = size
        self._success_status = success_status
        self._entries = deque()
        self._counts = defaultdict(int)

    def add(self, entry):
        self._entries.append(entry)
        self._counts[entry.status_code] += entry.count
        self._evict_before(entry.timestamp - self._size + 1)

    def count(self, status_code):
        return self._counts.get(status_code, 0)

    @property
    def success_count(self):
        return self.count(self._success_status)

    def failure_codes(self):
        return {code for code in self._counts if code != self._success_status}

    def _evict_before(self, start):
        while self._entries and self._entries[0].timestamp < start:
            old = self._entries.popleft()
            self._counts[old.status_code] -= old.count
            if self._counts[old.status_code] == 0:
                del self._counts[old.status_code]
