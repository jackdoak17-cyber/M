from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List


@dataclass(frozen=True)
class PlayerStatLine:
    player_name: str
    stat_key: str
    threshold: int
    wins: int
    total: int

    @property
    def rate(self) -> float:
        return self.wins / self.total if self.total else 0.0


@dataclass(frozen=True)
class TeamStatLine:
    team_name: str
    stat_key: str
    threshold: int
    wins: int
    total: int

    @property
    def rate(self) -> float:
        return self.wins / self.total if self.total else 0.0


PLAYER_SECTION_HEADERS: Dict[str, str] = {
    "shots": "⚽ SHOTS:",
    "shots_on_target": "🎯 SHOTS ON TARGET:",
    "fouls_committed": "⚠️ FOULS COMMITTED:",
    "fouls_won": "⚠️ FOULS WON:",
}

TEAM_SECTION_HEADER = "📈 TEAM PROPS:"

TEAM_COLOURS: Dict[str, str] = {
    "Arsenal": "🔴",
    "Aston Villa": "🟣",
    "Bournemouth": "🔴",
    "AFC Bournemouth": "🔴",
    "Brentford": "🔴",
    "Brighton": "🔵",
    "Brighton & Hove Albion": "🔵",
    "Burnley": "🟣",
    "Chelsea": "🔵",
    "Crystal Palace": "🔴",
    "Everton": "🔵",
    "Fulham": "⚪",
    "Leeds United": "⚪",
    "Liverpool": "🔴",
    "Manchester City": "🔵",
    "Manchester United": "🔴",
    "Newcastle United": "⚫",
    "Nottingham Forest": "🔴",
    "Sunderland": "🔴",
    "Tottenham Hotspur": "⚪",
    "West Ham United": "🟣",
    "Wolverhampton Wanderers": "🟠",
}


def format_player_stat_line(line: PlayerStatLine) -> str:
    if line.stat_key == "shots_on_target":
        label = "SOT" if line.threshold == 1 else f"{line.threshold}+ SOT"
    elif line.stat_key == "shots":
        label = f"{line.threshold}+ shots"
    elif line.stat_key == "fouls_committed":
        label = f"{line.threshold}+ fouls committed"
    elif line.stat_key == "fouls_won":
        label = f"{line.threshold}+ fouls won"
    else:
        label = f"{line.threshold}+ {line.stat_key.replace('_', ' ')}"
    return f"{line.player_name} {label} (won in {line.wins}/{line.total})"


def format_team_stat_line(line: TeamStatLine) -> str:
    if line.stat_key == "shots_on_target":
        label = f"{line.threshold}+ SOT"
    else:
        label = f"{line.threshold}+ {line.stat_key.replace('_', ' ')}"
    return f"{line.team_name} {label} (won in {line.wins}/{line.total})"


def _sorted_player_lines(lines: Iterable[PlayerStatLine]) -> List[PlayerStatLine]:
    return sorted(
        lines,
        key=lambda item: (
            item.threshold,
            -item.rate,
            -item.total,
            item.player_name.lower(),
        ),
    )


def _sorted_team_lines(lines: Iterable[TeamStatLine]) -> List[TeamStatLine]:
    return sorted(
        lines,
        key=lambda item: (
            -item.rate,
            -item.total,
            item.team_name.lower(),
        ),
    )


def format_game_section(
    home_team: str,
    away_team: str,
    kickoff_time: str,
    player_lines: Iterable[PlayerStatLine],
    team_lines: Iterable[TeamStatLine],
) -> str:
    player_sections: Dict[str, List[PlayerStatLine]] = {
        key: [] for key in PLAYER_SECTION_HEADERS
    }
    for line in player_lines:
        if line.stat_key in player_sections:
            player_sections[line.stat_key].append(line)

    sections: List[str] = []
    for stat_key, header in PLAYER_SECTION_HEADERS.items():
        lines = _sorted_player_lines(player_sections[stat_key])
        if not lines:
            continue
        rendered = [header]
        rendered.extend(format_player_stat_line(item) for item in lines)
        sections.append("\n".join(rendered))

    team_lines_sorted = _sorted_team_lines(team_lines)
    if team_lines_sorted:
        rendered = [TEAM_SECTION_HEADER]
        rendered.extend(format_team_stat_line(item) for item in team_lines_sorted)
        sections.append("\n".join(rendered))

    if not sections:
        return ""

    home_emoji = TEAM_COLOURS.get(home_team, "")
    away_emoji = TEAM_COLOURS.get(away_team, "")
    fixture_label = f"{home_emoji} {home_team} vs {away_team} {away_emoji} - {kickoff_time}".strip()
    output_lines = [fixture_label]
    for section in sections:
        output_lines.append("")
        output_lines.append(section)
    return "\n".join(output_lines)


def generate_full_prop_sheet(
    day_label: str,
    sections: Iterable[str],
) -> str:
    header = f"📊 PREMIER LEAGUE PROPS STAT LIST BY FIXTURE ({day_label.upper()})"
    intro = (
        f"I've analysed the data for {day_label}'s fixtures and identified the most consistent props. "
        "All data-driven, all based on recent form.\n\n"
        "If you find this useful please leave a like and remember to bookmark 🔖"
    )
    outro = (
        "Using these? Make sure you bookmark for later 🔖\n\n"
        "Good luck with your bets 🎯"
    )
    sections_list = [section for section in sections if section]
    output_lines = [header, "", intro]
    for index, section in enumerate(sections_list):
        output_lines.append("")
        output_lines.append(section)
    output_lines.append("")
    output_lines.append(outro)
    return "\n".join(output_lines)
