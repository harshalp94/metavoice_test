"""Sliding-window incident detection for merchant transaction logs.

detect_incidents runs three steps for every log record:
    1. Reading              read_logs     -> (timestamp, merchant_id, status_code, count)
    2. Processing           add_to_window -> that merchant's status-code counts for the last 30s
    3. Incident resolution  find_incidents -> error codes meeting the rule now
                            alert_changes  -> TRIGGER new ones, RESOLVE ones no longer meeting it

For manual debugging: python3 incident_detection/detector.py [file | -]
"""
import sys
from collections import defaultdict, deque

WINDOW_SECONDS = 30
MIN_FAILURES = 5
MIN_IMPACT_PERCENT = 1
SUCCESS = 200


# 1. Reading

def to_record(entry):
    """Convert "10, m1,500,2", ["10", "m1", "500", "2"] or (10, "m1", 500, 2) to (10, "m1", 500, 2)."""
    fields = entry.replace(",", " ").split() if isinstance(entry, str) else entry
    timestamp, merchant_id, status_code, count = fields
    return int(timestamp), str(merchant_id).strip(), int(status_code), int(count)


def read_logs(logs):
    """Turn a multi-line string, or a list of lines / field lists, into typed records; skip blank lines."""
    entries = logs.splitlines() if isinstance(logs, str) else logs
    return [to_record(entry) for entry in entries if not isinstance(entry, str) or entry.strip()]


# 2. Processing

def add_to_window(window, counts, record):
    """Add a record to its merchant's window and drop records outside [T-29, T].

    `counts` is this merchant's status_code -> count dict, i.e. counts[merchant_id].
    """
    record = to_record(record)
    timestamp, _, status_code, count = record
    window.append(record)
    counts[status_code] += count
    while window[0][0] <= timestamp - WINDOW_SECONDS:
        _, _, old_code, old_count = window.popleft()
        counts[old_code] -= old_count


# 3. Incident resolution

def is_incident(failures, successes):
    """At least MIN_FAILURES failures that are more than MIN_IMPACT_PERCENT% of the successes."""
    return failures >= MIN_FAILURES and failures * 100 > successes * MIN_IMPACT_PERCENT


def find_incidents(counts):
    """Error codes in the merchant's window that currently meet the alert rule."""
    successes = counts.get(SUCCESS, 0)
    return {code for code, failures in counts.items()
            if code != SUCCESS and is_incident(failures, successes)}


def alert_changes(previous, current, timestamp, merchant_id):
    """TRIGGER newly failing codes and RESOLVE recovered ones; ongoing alerts emit nothing."""
    triggered = [(timestamp, merchant_id, code, "TRIGGER") for code in current - previous]
    resolved = [(timestamp, merchant_id, code, "RESOLVE") for code in previous - current]
    return triggered + resolved


def format_event(event):
    timestamp, merchant_id, status_code, event_type = event
    return f"{timestamp},{event_type},{merchant_id},{status_code}"


def detect_incidents(logs, debug=False):
    windows = defaultdict(deque)                        # merchant_id -> records in the window
    counts = defaultdict(lambda: defaultdict(int))      # merchant_id -> status_code -> count
    active = defaultdict(set)                           # merchant_id -> status codes with an alert
    events = []

    for record in read_logs(logs):
        timestamp, merchant_id, _, _ = record
        add_to_window(windows[merchant_id], counts[merchant_id], record)
        incidents = find_incidents(counts[merchant_id])
        new_events = alert_changes(active[merchant_id], incidents, timestamp, merchant_id)
        active[merchant_id] = incidents
        events.extend(new_events)
        if debug:
            print_step(record, counts[merchant_id], active[merchant_id], new_events)

    # Sorts by timestamp, merchant_id, status_code, then event type (RESOLVE before TRIGGER).
    return [format_event(event) for event in sorted(events)]


# Manual debugging

SAMPLES = {
    "part1": ("""
        10, merchant1,500,2
        10, merchant2,500,1
        15, merchant1,500,2
        20, merchant1,500,1
        20, merchant2,500,4
    """, ["20,TRIGGER,merchant1,500", "20,TRIGGER,merchant2,500"]),
    "part2": ("""
        10, merchant1,200,600
        12, merchant1,500,6
        15, merchant2,200,599
        16, merchant2,500,6
    """, ["16,TRIGGER,merchant2,500"]),
    "part3": ("""
        10, merchant1,500,6
        16, merchant2,500,6
        45, merchant1,200,1
        45, merchant2,200,1
    """, ["10,TRIGGER,merchant1,500", "16,TRIGGER,merchant2,500", "45,RESOLVE,merchant1,500"]),
}


def print_step(record, counts, active, new_events):
    window = {code: n for code, n in sorted(counts.items()) if n}
    print(f"  {record}")
    print(f"      window: {window}  active: {sorted(active)}")
    for event in new_events:
        print(f"      -> {format_event(event)}")


def run(logs):
    """Trace detect_incidents record by record and return its output."""
    print("Steps:")
    result = detect_incidents(logs, debug=True)
    print("Output:")
    for event in result or ["(no events)"]:
        print(f"  {event}")
    return result


def run_samples():
    """Trace every sample and check it against its expected output."""
    all_passed = True
    for name, (logs, expected) in SAMPLES.items():
        print(f"===== {name} =====")
        passed = run(logs) == expected
        all_passed = all_passed and passed
        print("PASS\n" if passed else f"FAIL, expected {expected}\n")
    return all_passed


if __name__ == "__main__":
    if len(sys.argv) > 1:
        source = sys.stdin if sys.argv[1] == "-" else open(sys.argv[1])
        with source:
            run(source.read())
    else:
        sys.exit(0 if run_samples() else 1)
