# Sleeper League Dashboard

A live KPI dashboard for a Sleeper fantasy football league. Pure static HTML/JS —
it calls Sleeper's public API directly from the visitor's browser, so it can be
hosted for free on GitHub Pages with no backend or build step.

**Live demo:** `https://<your-username>.github.io/<repo-name>/`

## What it shows
- League leader, high/low weekly scores, closest matchup, biggest blowout, league avg PPG
- Full standings (record, points for/against, differential, current streak)
- Power ranking chart (points for, by team)
- Roster activity leaderboard (transactions + trades per team)

## Reusing for another league or season
Open the page and paste any Sleeper League ID into the input box, then click
**Load League**. To change the default league that loads on first visit, edit
the `value="..."` attribute on the `#leagueIdInput` field in `index.html`.

## Local / scripted data pulls
`scripts/sleeper_league_fetcher.py` is a standalone CLI tool for exporting a
league's full season data to JSON/CSV (useful for archiving a season, or
feeding the data into Excel/Sheets/another tool):

```bash
pip install requests
python scripts/sleeper_league_fetcher.py --league-id 1317218659407495168
```

## Data source
[Sleeper API](https://docs.sleeper.com/) — public, read-only, no auth required.
