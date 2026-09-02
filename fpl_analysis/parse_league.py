"""Parse the FFPL league players page into a CSV and build the free-agent
draft board.

The saved page (Next.js flight payload) embeds one JSON object per player:
name, position, clubCode, basePrice, tierLabel, ownedBy (null = free
agent) and departed (left the league). This script extracts them, joins
them to the FFPL projections on (name, club), and writes:

- data/league_players.csv       every player with ownership state
- output/ffpl_free_agents.csv   free agents ranked by FFPL points

Usage:
    python parse_league.py <saved_page.html> [--data-dir data] [--out-dir output]
"""

import argparse
import json
import pathlib
import re

import pandas as pd


def parse_players(html: str) -> pd.DataFrame:
    text = html.replace('\\"', '"')
    pattern = re.compile(
        r'\{"id":"[^"]+","name":"[^"]*","position":"(?:GK|DEF|MID|FWD)".*?'
        r'"departedNote":(?:null|"[^"]*")\}')
    players = [json.loads(m) for m in pattern.findall(text)]
    df = pd.DataFrame(players).drop_duplicates(subset="id")
    return df[["name", "position", "clubCode", "clubName", "basePrice",
               "tierLabel", "goals", "assists", "ownedBy", "departed",
               "departedNote"]]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("page", type=pathlib.Path)
    parser.add_argument("--data-dir", default="data", type=pathlib.Path)
    parser.add_argument("--out-dir", default="output", type=pathlib.Path)
    args = parser.parse_args()

    league = parse_players(args.page.read_text())
    league.to_csv(args.data_dir / "league_players.csv", index=False)
    taken = league.ownedBy.notna()
    print(f"league players: {len(league)} | taken: {taken.sum()} | "
          f"departed: {league.departed.sum()} | "
          f"free agents: {(~taken & ~league.departed).sum()}")

    proj = pd.read_csv(args.out_dir / "ffpl_projections.csv")
    free = league[~taken & ~league.departed].merge(
        proj, left_on=["name", "clubCode"],
        right_on=["web_name", "short_name"], how="left")

    # The league page reflects deadline-day moves before the FPL mirror
    # does, so a player can sit at a new club there. Recover those with a
    # second join on (name, position), accepted only when unambiguous.
    missed = free.ffpl_pgw.isna()
    fallback = free.loc[missed, ["name", "position_x"]].merge(
        proj.drop_duplicates(subset=["web_name", "position"], keep=False),
        left_on=["name", "position_x"],
        right_on=["web_name", "position"], how="left")
    fallback.index = free.index[missed]
    for col in proj.columns:
        free.loc[missed, col] = fallback[col]
    recovered = fallback.web_name.notna()
    if recovered.any():
        free.loc[fallback.index[recovered], "flags"] = (
            free.loc[fallback.index[recovered], "flags"].fillna("")
            .replace("", "MOVED-DEADLINE")
            .apply(lambda f: f if "MOVED-DEADLINE" in f
                   else f + ", MOVED-DEADLINE"))
        print("club changed per league data (projection kept from old club):",
              ", ".join(free.loc[fallback.index[recovered], "name"]))

    unmatched = free[free.ffpl_pgw.isna()]
    print(f"free agents without a projection match: {len(unmatched)} "
          "(no last-season PL data)")

    board = (free.dropna(subset=["ffpl_pgw"])
             .sort_values("ffpl_pgw", ascending=False))
    cols = ["name", "clubCode", "position_x", "tierLabel", "ffpl_pgw",
            "ffpl_season", "season_points", "likely_starter", "starts",
            "penalties_order", "direct_freekicks_order",
            "corners_and_indirect_freekicks_order", "status", "flags"]
    out = board[cols].rename(columns={"position_x": "position"})
    out.round(2).to_csv(args.out_dir / "ffpl_free_agents.csv", index=False)

    starters = out[out.likely_starter & (out.status == "a")]
    print("\nFree-agent draft board (likely starters):")
    for i, r in enumerate(starters.head(25).itertuples(), 1):
        fl = r.flags if isinstance(r.flags, str) else ""
        print(f"  {i:2d}. {r.name:<16} {r.clubCode} {r.position:<3} "
              f"T{r.tierLabel}  {r.ffpl_pgw:.2f}/GW  {fl}")

    print("\nBest taken-player check (top 5 already owned):")
    owned = league[taken].merge(
        proj, left_on=["name", "clubCode"],
        right_on=["web_name", "short_name"], how="inner")
    for r in owned.nlargest(5, "ffpl_pgw").itertuples():
        print(f"      {r.name} {r.clubCode} {r.ffpl_pgw:.2f} -> {r.ownedBy}")


if __name__ == "__main__":
    main()
