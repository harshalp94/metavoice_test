from collections import defaultdict, deque

WINDOW_SECONDS = 30
ALERT_THRESHOLD = 5
SUCCESS_STATUS = 200


def parse_log(line):
    """Parse a "timestamp, merchant_id, status_code, count" record."""
    timestamp, merchant_id, status_code, count = (part.strip() for part in line.split(','))
    return int(timestamp), merchant_id, int(status_code), int(count)


def detect_incidents(logs):
    window = deque()
    code_counts = defaultdict(lambda: defaultdict(int))
    active = defaultdict(set)
    events = []

    for line in logs:
        timestamp, merchant_id, status_code, count = parse_log(line)
        window.append((timestamp, merchant_id, status_code, count))
        code_counts[merchant_id][status_code] += count

        # Window for timestamp T is [T-29, T]; any merchant losing entries must be re-evaluated.
        dirty = {merchant_id}
        while window[0][0] <= timestamp - WINDOW_SECONDS:
            _, old_merchant, old_code, old_count = window.popleft()
            code_counts[old_merchant][old_code] -= old_count
            if code_counts[old_merchant][old_code] == 0:
                del code_counts[old_merchant][old_code]
            dirty.add(old_merchant)

        for merchant in dirty:
            counts = code_counts[merchant]
            candidates = {code for code in counts if code != SUCCESS_STATUS} | active[merchant]
            for code in candidates:
                met = counts.get(code, 0) >= ALERT_THRESHOLD
                if met and code not in active[merchant]:
                    active[merchant].add(code)
                    events.append((timestamp, merchant, code, "TRIGGER"))
                elif not met and code in active[merchant]:
                    active[merchant].discard(code)
                    events.append((timestamp, merchant, code, "RESOLVE"))

    events.sort()
    return [f"{ts},{event},{merchant},{code}" for ts, merchant, code, event in events]
