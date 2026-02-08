# Premier League Prop Sheet Generator - Development Progress

## Last Updated: 2026-02-08 13:05

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
Optimize prop bot runtime for Daily Prop Picks (reduce per-fixture query load).

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
- Team corners now emit all qualifying thresholds (3+ and higher) instead of only 3+.
- Weekend player props now shorten team names and long player names (e.g., C. Summerville).
- Weekend player props now always use initial+surname (e.g., C. Palmer) and add a blank line in the intro copy.
- Prop sheet player names now use initial+surname format to prevent line wraps.
- Prop sheet fixture sections now render as flat lists (no section headers).
- Prop sheet output filenames include `by_fixture` for easier scanning in GitHub.

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

---

# Automated Prop Bot (Multi-League) - Development Progress

## Current Phase: Phase 1 - Foundation

## Completed Phases:
- [ ] Phase 1: Foundation (structure + core engine modules)
- [ ] Phase 2: Engine Layers (baseline, opponent, adjustments, distribution)
- [ ] Phase 3: Odds + Edge + Selection
- [ ] Phase 4: Write-ups (Claude)
- [ ] Phase 5: Output + Result Tracking
- [ ] Phase 6: Automation + Docs

## Current Task:
Implement v1 engine per handoff docs (fixtures → candidates → top 10 → write-ups → JSON output).

## Next Steps:
1. Wire engine modules into the main runner and validate against Supabase data.
2. Add workflows for daily picks and result checks.
3. Validate with a dry run and inspect sample JSON output.

## New Files Added (Prop Bot):
- src/prop_bot/main.py (entry point)
- src/prop_bot/check_results.py (result tracking)
- src/prop_bot/engine/* (data + engine layers)
- .github/workflows/daily_picks.yml
- .github/workflows/check_results.yml

## Configuration Decisions Made (Prop Bot):
- Uses direct Supabase Postgres via `SUPABASE_DB_URL`
- Model: claude-sonnet-4-20250514 (set `ANTHROPIC_API_KEY`)
- Leagues: 8, 9, 72, 82, 301, 384, 390, 444, 501, 564, 568, 600
- Markets: shots, SOT, fouls committed, fouls drawn, tackles
- Filters: min 5 appearances, confidence ≥ 65, edge ≥ 10%
- Filters: tiered recent hit-rate gate (pass any of 4/5, 6/7, 7/10, plus overall ≥70% when n>10)
- Filters: odds range 1.80–4.00 and minimum avg ≥ threshold
- Ranking: (confidence * 0.3) + (our_probability * 100 * 0.5) + (edge% * 0.2)
- Output: one pick per player (dedup)
- Writeups: opponent stats mirrored for fouls markets and bookmaker included; prompt excludes projections/edge.
- Writeups: omit vs_similar when hit rate <60%; suppress opponent concession stats when opponent ranks #1 fewest.
- Prop bot uses pooled DB connections to avoid per-query reconnect cost.
- Similar-opponent analysis now runs only for final top picks when `PROP_INCLUDE_SIMILAR=1`.
