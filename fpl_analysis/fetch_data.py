"""Download FPL data snapshots used by the analysis.

Primary source is the vaastav/Fantasy-Premier-League open dataset on GitHub,
which mirrors the official FPL API (https://fantasy.premierleague.com/api/)
into CSVs. The official API blocks some cloud egress networks; the GitHub
mirror is reachable everywhere and updated daily during the season.

Usage:
    python fetch_data.py [--data-dir data]
"""

import argparse
import pathlib
import urllib.request

BASE = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data"

CURRENT_SEASON = "2026-27"
PREVIOUS_SEASON = "2025-26"

FILES = {
    f"{CURRENT_SEASON}/players_raw.csv": "current_players_raw.csv",
    f"{CURRENT_SEASON}/teams.csv": "current_teams.csv",
    f"{CURRENT_SEASON}/fixtures.csv": "current_fixtures.csv",
    f"{PREVIOUS_SEASON}/players_raw.csv": "previous_players_raw.csv",
    f"{PREVIOUS_SEASON}/teams.csv": "previous_teams.csv",
    f"{PREVIOUS_SEASON}/fixtures.csv": "previous_fixtures.csv",
}


def fetch(data_dir: pathlib.Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    for remote, local in FILES.items():
        url = f"{BASE}/{remote}"
        dest = data_dir / local
        print(f"Fetching {url}")
        with urllib.request.urlopen(url, timeout=120) as resp:
            dest.write_bytes(resp.read())
        print(f"  -> {dest} ({dest.stat().st_size} bytes)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data", type=pathlib.Path)
    args = parser.parse_args()
    fetch(args.data_dir)
