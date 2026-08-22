"""Per-club FFPL option boards: every club's auction options in one place.

For each of the 20 clubs: expected tier band and attack multiplier, the
likely-starter options with target priority and max bids, the first-choice
set-piece takers (with a marker when they are not board-eligible), and the
notable exclusions - injured, bench/rotation, or no PL data.

Writes output/ffpl_club_boards.md.

Usage:
    python club_boards.py [--data-dir data] [--out-dir output]
"""

import argparse
import pathlib

import pandas as pd

POS_NAME = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
MAX_ROWS = 6


def qualifier(name, club, proj_idx):
    row = proj_idx.get((name, club))
    if row is None:
        return "no PL data"
    if row.status != "a":
        return "injured/out"
    if not row.likely_starter:
        return "not a regular starter"
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data", type=pathlib.Path)
    parser.add_argument("--out-dir", default="output", type=pathlib.Path)
    args = parser.parse_args()

    bids = pd.read_csv(args.out_dir / "ffpl_max_bids.csv")
    proj = pd.read_csv(args.out_dir / "ffpl_projections.csv")
    tiers = pd.read_csv(args.out_dir / "ffpl_club_tiers.csv")
    raw = pd.read_csv(args.data_dir / "current_players_raw.csv")
    teams = pd.read_csv(args.data_dir / "current_teams.csv")
    raw["club"] = raw.team.map(dict(zip(teams.id, teams.short_name)))
    proj_idx = {(r.web_name, r.short_name): r for r in proj.itertuples()}

    lines = ["# FFPL options, club by club", ""]
    lines.append(
        "Likely starters with target priority (P#) and max bids for "
        "6 / 8 / 10-team leagues. Set-piece duties: PEN penalties, FK direct "
        "free kicks, CK corners. Clubs are in expected-strength order.")
    lines.append("")

    for t in tiers.sort_values("strength_z", ascending=False).itertuples():
        club = t.short_name
        full = teams.loc[teams.short_name == club, "name"].iloc[0]
        lines.append(f"## {full} ({club})")
        lines.append(
            f"Band: T1 {t.p_tier1:.0%} / T2 {t.p_tier2:.0%} / "
            f"T3 {t.p_tier3:.0%} - attack multiplier x{t.mult_attack:.2f}")
        lines.append("")

        board = (bids[bids.short_name == club]
                 .sort_values("ffpl_pgw", ascending=False).head(MAX_ROWS))
        if len(board):
            lines.append("| Priority | Player | Pos | Pts/GW | "
                         "Max bid 6/8/10 | Set pieces |")
            lines.append("|---|---|---|---|---|---|")
            for r in board.itertuples():
                sp = r.set_pieces if isinstance(r.set_pieces, str) else ""
                lines.append(
                    f"| P{int(r.priority)} | {r.web_name} | {r.position} | "
                    f"{r.ffpl_pgw:.2f} | {r.max_bid_6_teams} / "
                    f"{r.max_bid_8_teams} / {r.max_bid_10_teams} | {sp} |")
        else:
            lines.append("No board options: no player passes the "
                         "likely-starter rule (600+ minutes and 27+ starts "
                         "in the PL last season).")
        lines.append("")

        sp_bits = []
        for label, col in [("PEN", "penalties_order"),
                           ("FK", "direct_freekicks_order"),
                           ("CK", "corners_and_indirect_freekicks_order")]:
            takers = raw[(raw.club == club) & (raw[col] == 1)]
            for r in takers.itertuples():
                q = qualifier(r.web_name, club, proj_idx)
                sp_bits.append(f"{label} {r.web_name}"
                               + (f" ({q})" if q else ""))
        if sp_bits:
            lines.append("Set pieces: " + "; ".join(sp_bits) + ".")

        notes = []
        hurt = raw[(raw.club == club) & raw.status.isin(["i", "s", "d"])
                   & (raw.now_cost >= 60)]
        for r in hurt.itertuples():
            news = r.news if isinstance(r.news, str) else "unavailable"
            notes.append(f"{r.web_name}: {news}")
        nodata = raw[(raw.club == club) & (raw.status == "a")
                     & (raw.minutes < 600) & (raw.now_cost >= 60)]
        if len(nodata):
            notes.append("No PL data (market-priced starters): "
                         + ", ".join(nodata.web_name) + ".")
        bench = proj[(proj.short_name == club) & (proj.status == "a")
                     & ~proj.likely_starter & (proj.ffpl_pgw >= 3.5)]
        if len(bench):
            notes.append("Under the starter rule despite good points: "
                         + ", ".join(bench.web_name) + ".")
        for n in notes:
            lines.append(f"- {n}")
        lines.append("")

    text = "\n".join(lines)
    (args.out_dir / "ffpl_club_boards.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
