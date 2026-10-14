"""Sliding-window incident detection for merchant transaction logs.

How the functions fit together, per log record, inside detect_incidents:

    split_logs(logs)            -> one record string per line
    parse_log(line)             -> (timestamp, merchant_id, status_code, count)
    add_to_window(...)          -> update that merchant's 30s window counts, evict old records
    evaluate_alerts(...)        -> apply trigger/resolve rules to the merchant's codes
                                   (rules are built from volume_rule, impact_rule,
                                   all_of, any_of, negate)
    format_event(event)         -> "timestamp,event_type,merchant_id,status_code", after sorting

For manual debugging, run(logs) prints every step, and running this file
directly (`python3 incident_detection/detector.py [file | -]`) traces the
samples, or the logs in a file / on stdin.
"""
import re
import sys
from collections import defaultdict, deque

WINDOW_SECONDS = 30
SUCCESS_STATUS = 200
TRIGGER = "TRIGGER"
RESOLVE = "RESOLVE"


# Parsing and formatting

def split_logs(logs):
    """Accept one string with a record per line, or a list of records; skip blank lines."""
    if isinstance(logs, str):
        logs = logs.splitlines()
    return [line for line in logs if line.strip()]


def parse_log(line):
    """Parse a "timestamp, merchant_id, status_code, count" record (comma and/or space separated)."""
    timestamp, merchant_id, status_code, count = re.split(r"[,\s]+", line.strip())
    return int(timestamp), merchant_id, int(status_code), int(count)


def format_event(event):
    timestamp, merchant_id, status_code, event_type = event
    return f"{timestamp},{event_type},{merchant_id},{status_code}"


# Sliding window

def add_to_window(window, counts, timestamp, status_code, count, window_seconds=WINDOW_SECONDS):
    """Add a record to a merchant's window, keeping only [T - window_seconds + 1, T].

    `window` is a deque of (timestamp, status_code, count) records and `counts`
    maps status code to its total in the window.
    """
    window.append((timestamp, status_code, count))
    counts[status_code] += count
    while window[0][0] <= timestamp - window_seconds:
        _, old_code, old_count = window.popleft()
        counts[old_code] -= old_count
        if counts[old_code] == 0:
            del counts[old_code]


# Alert rules: functions (counts, status_code) -> bool over a merchant's window counts.

def volume_rule(min_failures):
    """At least `min_failures` occurrences of the status code."""
    return lambda counts, status_code: counts.get(status_code, 0) >= min_failures


def impact_rule(percent):
    """Failures are more than `percent`% of the merchant's successful volume."""
    return lambda counts, status_code: (
        counts.get(status_code, 0) * 100 > counts.get(SUCCESS_STATUS, 0) * percent
    )


def all_of(*rules):
    return lambda counts, status_code: all(rule(counts, status_code) for rule in rules)


def any_of(*rules):
    return lambda counts, status_code: any(rule(counts, status_code) for rule in rules)


def negate(rule):
    return lambda counts, status_code: not rule(counts, status_code)


DEFAULT_TRIGGER_RULE = all_of(volume_rule(5), impact_rule(1))


# Alert evaluation

def evaluate_alerts(counts, active, trigger_rule, resolve_rule):
    """Update a merchant's `active` alert codes; return the (status_code, event_type) changes."""
    changes = []
    failure_codes = {code for code in counts if code != SUCCESS_STATUS}
    for code in failure_codes | active:
        if code in active:
            if resolve_rule(counts, code):
                active.discard(code)
                changes.append((code, RESOLVE))
        elif trigger_rule(counts, code):
            active.add(code)
            changes.append((code, TRIGGER))
    return changes


def print_step(line, counts, active, new_events):
    print(f"  {line.strip()}")
    print(f"      window: {dict(sorted(counts.items()))}  active: {sorted(active)}")
    for event in new_events:
        print(f"      -> {format_event(event)}")


def detect_incidents(logs, trigger_rule=DEFAULT_TRIGGER_RULE, resolve_rule=None,
                     window_seconds=WINDOW_SECONDS, debug=False):
    """Return TRIGGER/RESOLVE events for (merchant_id, status_code) alerts.

    `logs` is one string with a record per line, or a list of records. With
    `debug`, each record's window counts, active alerts and events are printed.

    An alert resolves when `resolve_rule` holds, by default when `trigger_rule`
    no longer does. A merchant's alerts only change state when that merchant logs.
    """
    resolve_rule = resolve_rule or negate(trigger_rule)
    windows = defaultdict(deque)
    counts = defaultdict(lambda: defaultdict(int))
    active = defaultdict(set)
    events = []

    for line in split_logs(logs):
        timestamp, merchant_id, status_code, count = parse_log(line)
        add_to_window(windows[merchant_id], counts[merchant_id], timestamp, status_code, count,
                      window_seconds)
        changes = evaluate_alerts(counts[merchant_id], active[merchant_id], trigger_rule, resolve_rule)
        new_events = [(timestamp, merchant_id, code, event_type) for code, event_type in changes]
        events.extend(new_events)
        if debug:
            print_step(line, counts[merchant_id], active[merchant_id], new_events)

    # Tuple order gives (timestamp, merchant_id, status_code, event_type) ascending; RESOLVE < TRIGGER.
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


def run(logs, **options):
    """Run detect_incidents with a step-by-step trace and return its output.

    `options` are passed through, e.g. run(logs, trigger_rule=volume_rule(3)).
    """
    print("Steps:")
    result = detect_incidents(logs, debug=True, **options)
    print("Output:")
    for event in result or ["(no events)"]:
        print(f"  {event}")
    return result


def run_samples():
    """Trace every sample and compare against its expected output."""
    all_passed = True
    for name, (logs, expected) in SAMPLES.items():
        print(f"===== {name} =====")
        result = run(logs)
        passed = result == expected
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
