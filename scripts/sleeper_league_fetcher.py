#!/usr/bin/env python3
"""
Sleeper Fantasy Football League Fetcher
----------------------------------------
Reusable CLI tool to pull complete league data from Sleeper's public API
(no auth required) and export it to JSON + CSV for any league, any season.

USAGE
    pip install requests
    python sleeper_league_fetcher.py --league-id 1317218659407495168
    python sleeper_league_fetcher.py --username shanemantz --season 2025
    python sleeper_league_fetcher.py --league-id 1317218659407495168 --out my_league_data

WHAT IT PULLS
    - League settings & scoring
    - Users / team owners
    - Rosters (records, points for/against, waiver budget)
    - Weekly matchups (regular season, auto-detected)
    - Transactions (waivers, free agents, trades) per week
    - Playoff brackets (winners + losers)
    - Draft(s) and draft picks

OUTPUT
    <out>/league_data.json   -- everything, nested
    <out>/standings.csv      -- flat standings table
    <out>/weekly_scores.csv  -- flat per-team, per-week scoring table
    <out>/transactions.csv   -- flat transaction log
"""

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import requests

API = "https://api.sleeper.app/v1"


def get(url, retries=3, backoff=1.5):
    """GET a Sleeper API URL with basic retry handling."""
    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            if attempt == retries - 1:
                raise RuntimeError(f"Failed to fetch {url}: {e}") from e
            time.sleep(backoff * (attempt + 1))


def resolve_league_id(args):
    if args.league_id:
        return args.league_id
    if not args.username:
        sys.exit("Provide either --league-id or --username")
    season = args.season or get(f"{API}/state/nfl")["season"]
    user = get(f"{API}/user/{args.username}")
    leagues = get(f"{API}/user/{user['user_id']}/leagues/nfl/{season}")
    if not leagues:
        sys.exit(f"No NFL leagues found for {args.username} in {season}")
    if len(leagues) == 1:
        return leagues[0]["league_id"]
    print(f"\n{args.username} is in {len(leagues)} leagues for {season}:\n")
    for i, lg in enumerate(leagues):
        print(f"  [{i}] {lg['name']}  (league_id={lg['league_id']})")
    idx = input("\nWhich league number? ")
    return leagues[int(idx)]["league_id"]


def fetch_league_data(league_id):
    print(f"Fetching league {league_id} ...")
    league = get(f"{API}/league/{league_id}")
    users = get(f"{API}/league/{league_id}/users")
    rosters = get(f"{API}/league/{league_id}/rosters")
    nfl_state = get(f"{API}/state/nfl")

    playoff_start = (league.get("settings") or {}).get("playoff_week_start", 15)
    if league["season"] == nfl_state["season"]:
        last_week = max(1, nfl_state.get("week", 1))
    else:
        last_week = playoff_start - 1
    weeks_to_scan = max(1, min(last_week, playoff_start - 1, 18))

    print(f"Scanning weeks 1-{weeks_to_scan} for matchups & transactions ...")
    matchups_by_week = {}
    transactions_by_week = {}
    for wk in range(1, weeks_to_scan + 1):
        matchups_by_week[wk] = get(f"{API}/league/{league_id}/matchups/{wk}")
        transactions_by_week[wk] = get(f"{API}/league/{league_id}/transactions/{wk}")

    print("Fetching brackets & drafts ...")
    try:
        winners_bracket = get(f"{API}/league/{league_id}/winners_bracket")
    except RuntimeError:
        winners_bracket = []
    try:
        losers_bracket = get(f"{API}/league/{league_id}/losers_bracket")
    except RuntimeError:
        losers_bracket = []
    try:
        drafts = get(f"{API}/league/{league_id}/drafts")
    except RuntimeError:
        drafts = []

    return {
        "league": league,
        "users": users,
        "rosters": rosters,
        "matchups_by_week": matchups_by_week,
        "transactions_by_week": transactions_by_week,
        "winners_bracket": winners_bracket,
        "losers_bracket": losers_bracket,
        "drafts": drafts,
        "weeks_scanned": weeks_to_scan,
    }


def team_lookup(data):
    """roster_id -> {team_name, owner_name, ...}"""
    user_by_id = {u["user_id"]: u for u in data["users"]}
    lookup = {}
    for r in data["rosters"]:
        u = user_by_id.get(r["owner_id"], {})
        meta = u.get("metadata") or {}
        s = r.get("settings") or {}
        lookup[r["roster_id"]] = {
            "roster_id": r["roster_id"],
            "team_name": meta.get("team_name") or u.get("display_name") or f"Team {r['roster_id']}",
            "owner_name": u.get("display_name", "Unknown"),
            "wins": s.get("wins", 0),
            "losses": s.get("losses", 0),
            "ties": s.get("ties", 0),
            "fpts": (s.get("fpts", 0) or 0) + (s.get("fpts_decimal", 0) or 0) / 100,
            "fpts_against": (s.get("fpts_against", 0) or 0) + (s.get("fpts_against_decimal", 0) or 0) / 100,
            "waiver_budget_used": s.get("waiver_budget_used", 0),
            "total_moves": s.get("total_moves", 0),
        }
    return lookup


def write_json(data, out_dir):
    path = out_dir / "league_data.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"  wrote {path}")


def write_standings_csv(data, out_dir):
    teams = team_lookup(data)
    rows = sorted(teams.values(), key=lambda t: (-t["wins"], -t["fpts"]))
    path = out_dir / "standings.csv"
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "rank", "team_name", "owner_name", "wins", "losses", "ties",
            "fpts", "fpts_against", "point_diff", "waiver_budget_used", "total_moves"
        ])
        writer.writeheader()
        for i, t in enumerate(rows, start=1):
            writer.writerow({
                "rank": i,
                "team_name": t["team_name"],
                "owner_name": t["owner_name"],
                "wins": t["wins"],
                "losses": t["losses"],
                "ties": t["ties"],
                "fpts": round(t["fpts"], 2),
                "fpts_against": round(t["fpts_against"], 2),
                "point_diff": round(t["fpts"] - t["fpts_against"], 2),
                "waiver_budget_used": t["waiver_budget_used"],
                "total_moves": t["total_moves"],
            })
    print(f"  wrote {path}")


def write_weekly_scores_csv(data, out_dir):
    teams = team_lookup(data)
    path = out_dir / "weekly_scores.csv"
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["week", "team_name", "owner_name", "points", "matchup_id"])
        writer.writeheader()
        for wk, entries in data["matchups_by_week"].items():
            for e in entries or []:
                t = teams.get(e.get("roster_id"), {})
                writer.writerow({
                    "week": wk,
                    "team_name": t.get("team_name", f"Roster {e.get('roster_id')}"),
                    "owner_name": t.get("owner_name", ""),
                    "points": e.get("points"),
                    "matchup_id": e.get("matchup_id"),
                })
    print(f"  wrote {path}")


def write_transactions_csv(data, out_dir):
    teams = team_lookup(data)
    path = out_dir / "transactions.csv"
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "week", "type", "status", "teams_involved", "adds", "drops", "waiver_bid"
        ])
        writer.writeheader()
        for wk, txs in data["transactions_by_week"].items():
            for tx in txs or []:
                if tx.get("status") != "complete":
                    continue
                team_names = [teams.get(rid, {}).get("team_name", str(rid)) for rid in tx.get("roster_ids", [])]
                writer.writerow({
                    "week": wk,
                    "type": tx.get("type"),
                    "status": tx.get("status"),
                    "teams_involved": "; ".join(team_names),
                    "adds": "; ".join((tx.get("adds") or {}).keys()),
                    "drops": "; ".join((tx.get("drops") or {}).keys()),
                    "waiver_bid": tx.get("settings", {}).get("waiver_bid") if tx.get("settings") else "",
                })
    print(f"  wrote {path}")


def main():
    parser = argparse.ArgumentParser(description="Fetch a Sleeper fantasy football league's full season data.")
    parser.add_argument("--league-id", help="Sleeper league ID (skip username lookup)")
    parser.add_argument("--username", help="Sleeper username (used if --league-id not given)")
    parser.add_argument("--season", help="Season year, e.g. 2025 (only used with --username)")
    parser.add_argument("--out", default="sleeper_export", help="Output directory (default: sleeper_export)")
    args = parser.parse_args()

    league_id = resolve_league_id(args)
    data = fetch_league_data(league_id)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nWriting exports to {out_dir}/ ...")
    write_json(data, out_dir)
    write_standings_csv(data, out_dir)
    write_weekly_scores_csv(data, out_dir)
    write_transactions_csv(data, out_dir)

    print(f"\nDone. League: {data['league']['name']} ({data['league']['season']}) — "
          f"{len(data['rosters'])} teams, {data['weeks_scanned']} weeks scanned.")


if __name__ == "__main__":
    main()
