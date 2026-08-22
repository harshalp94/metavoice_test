"""Re-rank the FPL projections under FFPL rules (https://www.ffpl.site/rules).

FFPL pulls each player's official FPL points from the FPL API, then scales
them by a club-tier multiplier recut from the live table every gameweek:
positions 1-6 are Tier 1, 7-14 Tier 2, 15-20 Tier 3. A player's points in a
match are multiplied by the band gap to the opponent's club:

    facing 2 up x1.4 | 1 up x1.2 | level x1.0 | 1 down x0.85 | 2 down x0.7

So the base projection from analyze.py is the right starting point, and the
work here is estimating each club's season-long *effective* multiplier:

1. Expected 2026-27 club strength = blend of last season's league points
   (promoted clubs get a typical-promoted prior) and this season's FPL
   market strength ratings, z-scored 50/50.
2. Monte Carlo over table uncertainty: jitter strengths, re-rank, band into
   tiers. This yields tier probabilities instead of cliff-edge assignments
   for borderline clubs.
3. Per simulated table, the effective multiplier over a club's 38 fixtures
   weights each opponent by how much a player actually produces in that
   kind of match: attacking output and clean sheets shrink against
   stronger opponents (exactly when the multiplier is high), while
   defensive contributions, saves and goals conceded rise. Each projection
   component gets its own weighting ladder.

FFPL scores gameweeks 3-38, so season totals use 36 gameweeks.

Usage:
    python ffpl_adjust.py [--data-dir data] [--out-dir output] [--sims 4000]
"""

import argparse
import pathlib

import numpy as np
import pandas as pd

PROMOTED_PTS_PRIOR = 33     # typical promoted-club season, league points
STRENGTH_JITTER = 0.55      # sd of z-score noise per simulated season
TIER_MULT = {2: 1.4, 1: 1.2, 0: 1.0, -1: 0.85, -2: 0.7}

# How each projection component scales with the band gap to the opponent
# (gap = own tier number - opponent tier number; +2 = facing 2 up).
# Attacking returns and clean sheets shrink facing up; defensive volume,
# saves and goals conceded grow facing up; the rest is opponent-neutral.
LADDER = {
    "attack": {2: 0.77, 1: 0.87, 0: 1.0, -1: 1.15, -2: 1.30},
    "defvol": {2: 1.20, 1: 1.10, 0: 1.0, -1: 0.92, -2: 0.85},
    "conceded": {2: 1.25, 1: 1.12, 0: 1.0, -1: 0.90, -2: 0.80},
    "flat": {2: 1.0, 1: 1.0, 0: 1.0, -1: 1.0, -2: 1.0},
}
COMPONENT_LADDER = {
    "attack_pts": "attack", "cs_pts": "attack",
    "defcon_pts": "defvol", "save_pts": "defvol",
    "conceded_pts": "conceded",
    "appearance_pts": "flat", "bonus_pts": "flat", "card_pts": "flat",
}
SCORED_GWS = 36  # FFPL scores GW3-38


def league_table(fixtures: pd.DataFrame, teams: pd.DataFrame) -> pd.Series:
    """Final league points per club (short name) from a season's results."""
    name = dict(zip(teams.id, teams.short_name))
    done = fixtures[fixtures.finished == True]  # noqa: E712
    pts = {}
    for r in done.itertuples():
        h, a = name[r.team_h], name[r.team_a]
        hs, as_ = int(r.team_h_score), int(r.team_a_score)
        pts[h] = pts.get(h, 0) + (3 if hs > as_ else 1 if hs == as_ else 0)
        pts[a] = pts.get(a, 0) + (3 if as_ > hs else 1 if hs == as_ else 0)
    return pd.Series(pts)


def expected_strength(d: dict) -> pd.DataFrame:
    """Blended strength per current club: last-season points + market rating."""
    teams = d["teams"].copy()
    prev_pts = league_table(d["prev_fixtures"], d["prev_teams"])
    teams["prev_pts"] = teams.short_name.map(prev_pts).fillna(PROMOTED_PTS_PRIOR)
    teams["rating"] = teams.strength_overall_home + teams.strength_overall_away

    def z(s):
        return (s - s.mean()) / s.std(ddof=0)

    teams["strength_z"] = 0.5 * z(teams.prev_pts) + 0.5 * z(teams.rating)
    return teams[["id", "short_name", "prev_pts", "rating", "strength_z"]]


def tier_of_rank(rank: np.ndarray) -> np.ndarray:
    """League position (0-based rank) -> tier number 1/2/3."""
    return np.where(rank < 6, 1, np.where(rank < 14, 2, 3))


def simulate_multipliers(strength: pd.DataFrame, sims: int, rng) -> pd.DataFrame:
    n = len(strength)
    base = strength.strength_z.to_numpy()
    eff = {k: np.zeros(n) for k in LADDER}
    tier_counts = np.zeros((n, 3))

    for _ in range(sims):
        noisy = base + rng.normal(0, STRENGTH_JITTER, n)
        rank = (-noisy).argsort().argsort()   # 0 = top of the table
        tiers = tier_of_rank(rank)
        for i in range(n):
            tier_counts[i, tiers[i] - 1] += 1
            gaps = tiers[i] - np.delete(tiers, i)  # vs the 19 opponents
            for key, ladder in LADDER.items():
                w = np.array([ladder[g] for g in gaps])
                m = np.array([TIER_MULT[g] for g in gaps])
                eff[key][i] += (w * m).sum() / w.sum()

    out = strength.copy()
    for key in LADDER:
        out[f"mult_{key}"] = eff[key] / sims
    for t in (1, 2, 3):
        out[f"p_tier{t}"] = tier_counts[:, t - 1] / sims
    out["exp_tier"] = out.p_tier1 * 1 + out.p_tier2 * 2 + out.p_tier3 * 3
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data", type=pathlib.Path)
    parser.add_argument("--out-dir", default="output", type=pathlib.Path)
    parser.add_argument("--sims", default=4000, type=int)
    args = parser.parse_args()

    d = {
        "teams": pd.read_csv(args.data_dir / "current_teams.csv"),
        "prev_teams": pd.read_csv(args.data_dir / "previous_teams.csv"),
        "prev_fixtures": pd.read_csv(args.data_dir / "previous_fixtures.csv"),
    }
    proj = pd.read_csv(args.out_dir / "player_projections.csv")

    strength = expected_strength(d)
    rng = np.random.default_rng(2627)
    clubs = simulate_multipliers(strength, args.sims, rng)

    p = proj.merge(
        clubs[["short_name", "exp_tier", "p_tier1", "p_tier2", "p_tier3",
               "mult_attack", "mult_defvol", "mult_conceded", "mult_flat"]],
        on="short_name", how="left")

    p["ffpl_pgw"] = sum(
        p[comp] * p[f"mult_{LADDER_KEY}"]
        for comp, LADDER_KEY in COMPONENT_LADDER.items())
    p["eff_mult"] = p.ffpl_pgw / p.proj_pgw
    p["ffpl_season"] = p.ffpl_pgw * SCORED_GWS

    # A "likely starter" started 27+ of 38 league matches last season, is
    # currently available, and (for keepers) is priced as the club's #1.
    flags_str = p["flags"].fillna("")
    p["likely_starter"] = ((p.status == "a")
                           & (p.starts >= 27)
                           & ~flags_str.str.contains("GK-RISK"))

    p = p.sort_values("ffpl_pgw", ascending=False)
    keep = ["web_name", "short_name", "position", "exp_tier", "eff_mult",
            "proj_pgw", "ffpl_pgw", "ffpl_season", "p_tier1", "p_tier2",
            "p_tier3", "exp_mins_gw", "starts", "likely_starter",
            "penalties_order", "direct_freekicks_order",
            "corners_and_indirect_freekicks_order", "status", "flags"]
    p[keep].round(3).to_csv(args.out_dir / "ffpl_projections.csv", index=False)

    clubs_out = clubs.sort_values("strength_z", ascending=False)
    clubs_out.round(3).to_csv(args.out_dir / "ffpl_club_tiers.csv", index=False)

    print("Expected club tiers (P Tier1/2/3, attack multiplier):")
    for r in clubs_out.itertuples():
        print(f"  {r.short_name}  exp_tier {r.exp_tier:.2f}  "
              f"P {r.p_tier1:.2f}/{r.p_tier2:.2f}/{r.p_tier3:.2f}  "
              f"mult_attack {r.mult_attack:.3f}")

    listed = p[p.likely_starter]
    print("\nFFPL top 20, likely starters only "
          "(tier-adjusted expected points per gameweek):")
    for i, r in enumerate(listed.head(20).itertuples(), 1):
        print(f"  {i:2d}. {r.web_name:<16} {r.short_name}  {r.position:<3} "
              f"base {r.proj_pgw:.2f} x {r.eff_mult:.2f} = {r.ffpl_pgw:.2f} "
              f"/GW  (~{r.ffpl_season:.0f} over GW3-38)  starts {r.starts}  "
              f"{r.flags if isinstance(r.flags, str) else ''}")

    dropped = p[~p.likely_starter].head(40)
    dropped = dropped[dropped.ffpl_pgw >= listed.ffpl_pgw.iloc[19]]
    if len(dropped):
        print("\nExcluded by the starter filter despite top-20 points:")
        for r in dropped.itertuples():
            reason = ("injury/unavailable" if r.status != "a"
                      else "keeper competition" if isinstance(r.flags, str)
                      and "GK-RISK" in r.flags
                      else f"only {r.starts} starts last season")
            print(f"      {r.web_name} {r.short_name} {r.ffpl_pgw:.2f} - {reason}")


if __name__ == "__main__":
    main()
