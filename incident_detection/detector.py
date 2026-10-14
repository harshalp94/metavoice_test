from collections import defaultdict, deque

WINDOW_SECONDS = 30
VOLUME_THRESHOLD = 5
IMPACT_THRESHOLD_PERCENT = 1
SUCCESS_STATUS = 200


def parse_log(line):
    """Parse a "timestamp, merchant_id, status_code, count" record."""
    timestamp, merchant_id, status_code, count = (part.strip() for part in line.split(','))
    return int(timestamp), merchant_id, int(status_code), int(count)


def alert_condition(failures, successes):
    """At least 5 failures that are more than 1% of the successful volume."""
    return failures >= VOLUME_THRESHOLD and failures * 100 > successes * IMPACT_THRESHOLD_PERCENT


def detect_incidents(logs):
    windows = defaultdict(deque)
    code_counts = defaultdict(lambda: defaultdict(int))
    active = defaultdict(set)
    events = []

    for line in logs:
        timestamp, merchant_id, status_code, count = parse_log(line)
        window = windows[merchant_id]
        counts = code_counts[merchant_id]
        window.append((timestamp, status_code, count))
        counts[status_code] += count

        # Window for timestamp T is [T-29, T].
        while window[0][0] <= timestamp - WINDOW_SECONDS:
            _, old_code, old_count = window.popleft()
            counts[old_code] -= old_count
            if counts[old_code] == 0:
                del counts[old_code]

        # Alerts only change state when their merchant logs.
        successes = counts.get(SUCCESS_STATUS, 0)
        candidates = {code for code in counts if code != SUCCESS_STATUS} | active[merchant_id]
        for code in candidates:
            met = alert_condition(counts.get(code, 0), successes)
            if met and code not in active[merchant_id]:
                active[merchant_id].add(code)
                events.append((timestamp, merchant_id, code, "TRIGGER"))
            elif not met and code in active[merchant_id]:
                active[merchant_id].discard(code)
                events.append((timestamp, merchant_id, code, "RESOLVE"))

    events.sort()
    return [f"{ts},{event},{merchant},{code}" for ts, merchant, code, event in events]
