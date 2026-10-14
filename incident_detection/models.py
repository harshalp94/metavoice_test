from dataclasses import dataclass
from enum import Enum

SUCCESS_STATUS = 200


class EventType(str, Enum):
    RESOLVE = "RESOLVE"
    TRIGGER = "TRIGGER"


@dataclass(frozen=True)
class LogEntry:
    timestamp: int
    merchant_id: str
    status_code: int
    count: int

    @classmethod
    def parse(cls, line):
        """Parse a "timestamp, merchant_id, status_code, count" record."""
        timestamp, merchant_id, status_code, count = (part.strip() for part in line.split(','))
        return cls(int(timestamp), merchant_id, int(status_code), int(count))


@dataclass(frozen=True, order=True)
class AlertEvent:
    # Field order defines sort order: timestamp, merchant_id, status_code, event_type.
    timestamp: int
    merchant_id: str
    status_code: int
    event_type: EventType

    def __str__(self):
        return f"{self.timestamp},{self.event_type.value},{self.merchant_id},{self.status_code}"
