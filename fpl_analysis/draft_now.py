"""Draft-now board: free agents scored for the next six gameweeks.

Refines the season-long free-agent board with what is known right now:

1. Fixture-tier interaction, GW3-8: each club's actual opponents, with
   the LEAGUE'S OWN live tier bands (tierLabel from the saved league
   page - the bands FFPL will score with), pushed through the same
   per-component multiplier ladders as the season model.
2. Confirmed role: gameweek 1 minutes from the per-gameweek data
   (60+ minutes = full factor, cameo = 0.9, unused = 0.75), plus manual
   overrides for facts newer than the data mirror.

    draft_now = sum(component x component_multiplier(GW3-8)) x role

Usage:
    python draft_now.py [--data-dir data] [--out-dir output]
"""

import argparse
import pathlib

import pandas as pd

from ffpl_adjust import LADDER, TIER_MULT, COMPONENT_LADDER

# Facts fresher than the data mirror, applied as role-factor overrides:
# (player name, club code) -> (factor, note)
OVERRIDES = {
    ("Senesi", "TOT"): (0.85, "benched in GW2 per manager report - check team news"),
    ("Mateta", "CRY"): (0.30, "out ~4 weeks per manager report - misses most of GW3-8"),
}

# Players who left the league after the snapshots were taken
# (manager reports): removed from the board entirely.
DEPARTED = {
    ("Woltemade", "NEW"),  # joined Juventus
}


def role_factors(data_dir: pathlib.Path) -> dict:
    gw = pd.read_csv(data_dir / "merged_gw.csv")
    latest = gw[gw.GW == gw.GW.max()]
    raw = pd.read_csv(data_dir / "current_players_raw.csv")
    code_of = dict(zip(raw.id, raw.code))
    out = {}
    for r in latest.itertuples():
        code = code_of.get(r.element)
        if code is None:
            continue
        out[code] = 1.0 if r.minutes >= 60 else (0.9 if r.minutes > 0 else 0.75)
    return out


def club_multipliers(data_dir: pathlib.Path, tier_of: dict) -> pd.DataFrame:
    fixtures = pd.read_csv(data_dir / "current_fixtures.csv")
    teams = pd.read_csv(data_dir / "current_teams.csv")
    name_of = dict(zip(teams.id, teams.short_name))
    window = fixtures[(fixtures.event >= 3) & (fixtures.event <= 8)]

    opponents = {}
    for r in window.itertuples():
        h, a = name_of[r.team_h], name_of[r.team_a]
        opponents.setdefault(h, []).append(a)
        opponents.setdefault(a, []).append(h)

    rows = []
    gap_lists = {}
    for club, opps in opponents.items():
        gaps = [max(-2, min(2, tier_of.get(club, 2) - tier_of.get(o, 2)))
                for o in opps]
        gap_lists[club] = gaps
        row = {"short_name": club, "n_fixtures": len(gaps)}
        for key, ladder in LADDER.items():
            w = [ladder[g] for g in gaps]
            m = [TIER_MULT[g] for g in gaps]
            row[f"mult_{key}"] = (sum(wi * mi for wi, mi in zip(w, m))
                                  / sum(w))
        rows.append(row)
    return pd.DataFrame(rows), gap_lists


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data", type=pathlib.Path)
    parser.add_argument("--out-dir", default="output", type=pathlib.Path)
    parser.add_argument("--top", default=22, type=int)
    parser.add_argument("--exclude-clubs", nargs="*", default=[],
                        help="club codes to leave out of the printed board")
    args = parser.parse_args()

    free = pd.read_csv(args.out_dir / "ffpl_free_agents.csv")
    proj = pd.read_csv(args.out_dir / "player_projections.csv")
    league = pd.read_csv(args.data_dir / "league_players.csv")

    tier_of = (league.dropna(subset=["tierLabel"])
               .groupby("clubCode").tierLabel.agg(lambda s: int(s.iloc[0]))
               .to_dict())
    mults, gap_lists = club_multipliers(args.data_dir, tier_of)

    comps = proj[["code", "short_name", "xg90", "xa90", "dc90", "cs_prob",
                  "exp_mins_gw"] + list(COMPONENT_LADDER)].copy()
    gone = free.apply(lambda r: (r["name"], r.clubCode) in DEPARTED, axis=1)
    board = free[~gone].dropna(subset=["code"]).merge(comps, on="code",
                                                      how="left")
    board = board.merge(mults, left_on="clubCode", right_on="short_name",
                        how="left")

    board["next6_pgw"] = sum(
        board[comp] * board[f"mult_{ladder}"]
        for comp, ladder in COMPONENT_LADDER.items())

    # Pure-expected variant: the attacking component from xG/xA rates only
    # (the default already blends 60% expected / 40% actual; this view drops
    # actual returns entirely, so finishing luck cannot flatter anyone).
    goal_pts = board.position.map({"GK": 10, "DEF": 6, "MID": 5, "FWD": 4})
    board["xgi90"] = board.xg90 + board.xa90
    pure_x_attack = ((board.xg90 * goal_pts + board.xa90 * 3)
                     * board.exp_mins_gw / 90)
    board["x_adjust"] = (pure_x_attack - board.attack_pts) * board.mult_attack

    roles = role_factors(args.data_dir)
    board["role"] = board.code.map(roles).fillna(0.75)
    board["role_note"] = ""
    for (name, club), (factor, note) in OVERRIDES.items():
        hit = (board.name == name) & (board.clubCode == club)
        board.loc[hit, "role"] = factor
        board.loc[hit, "role_note"] = note

    board["draft_now"] = board.next6_pgw * board.role
    board["draft_x"] = board.draft_now + board.x_adjust * board.role

    # Potential impact: the spike week - expected points in the club's
    # single most favorable fixture of the window, where the tier
    # multiplier (and the matching output ratio) peaks.
    def spike(r):
        gaps = gap_lists.get(r.clubCode)
        if not gaps or r.ffpl_pgw != r.ffpl_pgw:
            return 0.0
        best = 0.0
        for g in gaps:
            total = sum(getattr(r, comp) * LADDER[ladder][g] * TIER_MULT[g]
                        for comp, ladder in COMPONENT_LADDER.items())
            best = max(best, total)
        return best

    board["spike_gw"] = [spike(r) for r in board.itertuples()]
    # Final ranking: 70% steady xG-based value, 30% ceiling.
    board["impact"] = 0.7 * board.draft_x + 0.3 * board.spike_gw * board.role
    board = board.sort_values("impact", ascending=False)

    keep = ["name", "clubCode", "position", "tierLabel", "xg90", "xa90",
            "xgi90", "dc90", "cs_prob", "ffpl_pgw", "next6_pgw", "role",
            "draft_now", "draft_x", "spike_gw", "impact", "season_points",
            "status", "flags", "role_note"]
    board[keep].round(2).to_csv(args.out_dir / "ffpl_draft_now.csv",
                                index=False)

    listed = board[(board.status == "a")
                   & ~board.clubCode.isin(args.exclude_clubs)]
    print("Draft board ranked by impact (0.7 x steady xG value + 0.3 x spike week):")
    for i, r in enumerate(listed.head(args.top).itertuples(), 1):
        note = r.role_note or (r.flags if isinstance(r.flags, str) else "")
        starter = "" if r.likely_starter else "not nailed; "
        print(f"  {i:2d}. {r.name:<16} {r.clubCode} {r.position:<3} "
              f"T{int(r.tierLabel)}  xGI90 {r.xgi90:.2f}  dc90 {r.dc90:4.1f}  "
              f"CS {r.cs_prob:.0%}  xG {r.draft_x:.2f}  spike {r.spike_gw:.2f}  "
              f"impact {r.impact:.2f}  {starter}{note}")


if __name__ == "__main__":
    main()
