# Premier League Prop Sheet Generator - Development Progress

## Last Updated: 2026-02-04 22:27

## Current Phase: Phase 1 - Project Setup & Planning

## Completed Phases:
- [ ] Phase 1: Initial Setup
  - [x] Created project structure
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
Build the player/team analyzers now that data access is in place.

## Next Steps:
1. Implement player analyzer (eligibility + stat thresholds using consecutive starts).
2. Implement team analyzer (Line-2 logic using available odds lines).
3. Create virtual environment and install dependencies.

## Blockers/Questions:
- Fallback when Bet365 line is missing (skip or alternate book)?

## Testing Notes:
Not started.

## Code Files Status:
- data_fetcher.py: Not Started
- player_analyzer.py: Not Started
- team_analyzer.py: Not Started
- formatter.py: Not Started
- main.py: Not Started

## Configuration Decisions Made:
- Stack: Python
- Kickoff timezone: UK time (GMT/BST)
- Data source: Supabase tables (direct DB queries)
- Premier League league_id: 8 (from statswebsite-web league map)
- Bet365 bookmaker_id: 2 (from statswebsite-web bookmaker map)
- Defender detection: use lineup_detailed_position_name if present, else detailed_position_name/position_name, else position_abbr. Treat positions containing "Back" or "Defender", or abbr in {CB, LB, RB, LWB, RWB} as defenders.

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
- Team corners: type_id 34
- Team goal kicks: type_id 53
- Team free kicks: type_id 55

## Notes
- odds_outcomes currently contains team_shots and team_shots_on_target markets, but no corners/goal_kicks/free_kicks lines. Those team props will require either expanding odds ingestion or a separate odds API fetch.
