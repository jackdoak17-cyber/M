# Premier League Prop Sheet Generator - Development Progress

## Last Updated: 2026-02-06 22:01

## Current Phase: Phase 8 - Automation Setup

## Completed Phases:
- [ ] Phase 1: Initial Setup
  - [x] Created project structure
  - [x] Created requirements.txt
  - [ ] Set up virtual environment
  - [ ] Installed dependencies
  - [x] Created config template
  - [x] Documented data sources being used
- [ ] Phase 2: Data Collection
- [ ] Phase 3: Player Stats Analysis
- [ ] Phase 4: Team Stats Analysis
- [ ] Phase 5: Output Formatter
- [ ] Phase 6: Integration & Main Script
- [ ] Phase 7: Testing & Validation
- [ ] Phase 8: Automation Setup
- [ ] Phase 9: Documentation & Handoff

## Current Task:
Add weekend player props posts (last 5 starts, 100%/80% tiers).

## Next Steps:
1. Run the generator and spot-check weekend player props output.
2. Create virtual environment and install dependencies.
3. Start Phase 7 testing checklist and document results.

## Blockers/Questions:
- None (missing Bet365 line will be skipped).

## Testing Notes:
Not started.

## Code Files Status:
- data_fetcher.py: Complete (core queries in place)
- player_analyzer.py: Complete (needs validation)
- team_analyzer.py: Complete (needs validation)
- formatter.py: Complete (needs validation)
- main.py: Complete (needs validation)

## Configuration Decisions Made:
- Stack: Python
- Kickoff timezone: UK time (GMT/BST)
- Data source: Supabase tables (direct DB queries)
- Premier League league_id: 8 (from statswebsite-web league map)
- Bet365 bookmaker_id: 2 (from statswebsite-web bookmaker map)
- Defender detection: use lineup_detailed_position_name if present, else detailed_position_name/position_name, else position_abbr. Treat positions containing "Back" or "Defender", or abbr in {CB, LB, RB, LWB, RWB} as defenders.
- Automation: GitHub Actions runs hourly on Thursdays and only generates at 10:00 UK time; outputs are committed to the repo.
- Threshold: 75% hit rate for all props (player + team), minimum sample size 5.
- Team line-2 logic: wins are counted against the floored threshold (e.g., 3+ means >= 3.0).
- Weekend player props: last 5 starts only (skip non-starts), 1+ stats require 5/5, 2+ stats require >=4/5.
- Weekend player props require starting the most recent match, then use last 5 starts for hit-rate.
- Weekend 80% post now includes 2+ shots (total) alongside 2+ SOT and fouls.

## Verified Data Sources (Supabase)
- fixtures: schedule + scores (starting_at, home/away_team_id, status)
- fixture_players: starters/minutes + positions (is_starter, minutes_played, position_* fields)
- fixture_player_statistics: player stat values by type_id
- fixture_statistics: team stat values by type_id
- sidelined_active: current injuries/suspensions
- players, teams: names + ids
- odds_outcomes: Bet365 lines and prices (bookmaker_id=2)
- types: stat type catalog (IDs verified)

## Verified Stat Type IDs
- Player shots total: type_id 42 (Shots Total)
- Player shots on target: type_id 86 (Shots On Target)
- Player fouls committed: type_id 56 (Fouls)
- Player fouls won/drawn: type_id 96 (Fouls Drawn)
- Team shots total: type_id 42
- Team shots on target: type_id 86

## Notes
- Team props scope trimmed to shots + shots on target only (corners/goal kicks/free kicks removed).
