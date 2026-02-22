from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence

from src.weekend_player_props import PlayerPropLine

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

SHORT_TEAM_NAMES: Dict[str, str] = {
    "AFC Bournemouth": "Bournemouth",
    "Aston Villa": "Aston Villa",
    "Brentford": "Brentford",
    "Brighton & Hove Albion": "Brighton",
    "Burnley": "Burnley",
    "Chelsea": "Chelsea",
    "Crystal Palace": "Palace",
    "Everton": "Everton",
    "Fulham": "Fulham",
    "Leeds United": "Leeds",
    "Liverpool": "Liverpool",
    "Manchester City": "Man City",
    "Manchester United": "Man Utd",
    "Newcastle United": "Newcastle",
    "Nottingham Forest": "Nottm Forest",
    "Sunderland": "Sunderland",
    "Tottenham Hotspur": "Spurs",
    "West Ham United": "West Ham",
    "Wolverhampton Wanderers": "Wolves",
    "Arsenal": "Arsenal",
}

WEEKEND_HEADERS_100 = [
    ("shots_on_target", "📊1+ Shots on Target in ≥5/5📊"),
    ("fouls_drawn", "📊1+ Fouls Drawn in ≥5/5📊"),
    ("fouls_committed", "📊1+ Fouls Committed in ≥5/5📊"),
]

WEEKEND_HEADERS_80 = [
    ("shots", "📊2+ Shots in ≥4/5📊"),
    ("shots_on_target", "📊2+ Shots on Target in ≥4/5📊"),
    ("fouls_committed", "📊2+ Fouls Committed in ≥4/5📊"),
    ("fouls_drawn", "📊2+ Fouls Drawn in ≥4/5📊"),
]


def format_player_stat_line(line: PlayerStatLine) -> str:
    player_name = _shorten_player_name(line.player_name)
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
    return f"{player_name} {label} (won in {line.wins}/{line.total})"


def format_team_stat_line(line: TeamStatLine) -> str:
    if line.stat_key == "shots_on_target":
        label = f"{line.threshold}+ SOT"
    else:
        label = f"{line.threshold}+ {line.stat_key.replace('_', ' ')}"
    return f"{line.team_name} {label} (won in {line.wins}/{line.total})"


def _format_weekend_values(values: Sequence[float]) -> str:
    formatted: List[str] = []
    for value in values:
        if value is None:
            formatted.append("0")
            continue
        if abs(value - round(value)) < 0.01:
            formatted.append(str(int(round(value))))
        else:
            formatted.append(f"{value:g}")
    return ", ".join(formatted)


def _shorten_player_name(name: str) -> str:
    clean = name.strip()
    if not clean:
        return name
    parts = clean.split()
    if len(parts) >= 2:
        first = parts[0].replace(".", "")
        last = parts[-1]
        if not first:
            return clean
        return f"{first[0].upper()}. {last}"
    return clean


def format_weekend_player_line(line: PlayerPropLine) -> str:
    values_text = _format_weekend_values(line.values)
    player_name = _shorten_player_name(line.player_name)
    team_name = SHORT_TEAM_NAMES.get(line.team_name, line.team_name)
    return f"- {player_name} ({team_name}) = {values_text}"


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


def _sorted_weekend_lines(lines: Iterable[PlayerPropLine]) -> List[PlayerPropLine]:
    return sorted(
        lines,
        key=lambda item: (
            item.team_name.lower(),
            item.player_name.lower(),
        ),
    )


def count_weekend_prop_lines(lines_by_stat: Dict[str, List[PlayerPropLine]]) -> int:
    return sum(len(lines) for lines in lines_by_stat.values())


def format_game_section(
    home_team: str,
    away_team: str,
    kickoff_time: str,
    player_lines: Iterable[PlayerStatLine],
    team_lines: Iterable[TeamStatLine],
) -> str:
    player_sections: Dict[str, List[PlayerStatLine]] = {key: [] for key in PLAYER_SECTION_HEADERS}
    for line in player_lines:
        if line.stat_key in player_sections:
            player_sections[line.stat_key].append(line)

    flat_lines: List[str] = []
    for stat_key in PLAYER_SECTION_HEADERS:
        lines = _sorted_player_lines(player_sections[stat_key])
        flat_lines.extend(format_player_stat_line(item) for item in lines)

    team_lines_sorted = _sorted_team_lines(team_lines)
    flat_lines.extend(format_team_stat_line(item) for item in team_lines_sorted)

    if not flat_lines:
        return ""

    home_emoji = TEAM_COLOURS.get(home_team, "")
    away_emoji = TEAM_COLOURS.get(away_team, "")
    fixture_label = f"{home_emoji} {home_team} vs {away_team} {away_emoji} - {kickoff_time}".strip()
    output_lines = [fixture_label, ""]
    output_lines.extend(flat_lines)
    return "\n".join(output_lines)


def generate_full_prop_sheet(
    day_label: str,
    sections: Iterable[str],
) -> str:
    header = f"📊 Premier League props stat list by fixture ({day_label.title()})"
    intro = (
        f"I've analysed the data for {day_label}'s fixtures and identified the most consistent props. "
        "All data-driven, all based on recent form.\n\n"
        "If you find this useful please leave a like and remember to bookmark 🔖"
    )
    outro = "Make sure you bookmark for later 🔖\n\nGood luck with your bets 🎯"
    sections_list = [section for section in sections if section]
    output_lines = [header, "", intro]
    for index, section in enumerate(sections_list):
        output_lines.append("")
        output_lines.append(section)
    output_lines.append("")
    output_lines.append(outro)
    return "\n".join(output_lines)


def format_weekend_props_post(
    lines_by_stat: Dict[str, List[PlayerPropLine]],
    tier: str,
) -> str:
    if tier == "100":
        intro = (
            "As usual I've collated todays Premier League 1+ player stats (100% hit-rates) "
            "based on their last 5 games.\n\n"
            "Leave a like if you find these useful."
        )
        headers = WEEKEND_HEADERS_100
    else:
        intro = (
            "I've collated todays Premier League 2+ player stats (80% hit-rates) "
            "based on their last 5 games.\n\n"
            "Leave a like if you find these useful."
        )
        headers = WEEKEND_HEADERS_80

    sections: List[str] = []
    for stat_key, header in headers:
        lines = _sorted_weekend_lines(lines_by_stat.get(stat_key, []))
        if not lines:
            continue
        rendered = [header]
        rendered.extend(format_weekend_player_line(item) for item in lines)
        sections.append("\n".join(rendered))

    if not sections:
        return intro

    return intro + "\n\n" + "\n\n".join(sections)


def format_weekend_props_combined(
    hundred_lines: Dict[str, List[PlayerPropLine]],
    eighty_lines: Dict[str, List[PlayerPropLine]],
) -> str:
    total_100 = count_weekend_prop_lines(hundred_lines)
    total_80 = count_weekend_prop_lines(eighty_lines)
    if total_100 == 0 and total_80 == 0:
        return format_weekend_props_post(hundred_lines, "100")
    if total_100 == 0:
        return format_weekend_props_post(eighty_lines, "80")
    if total_80 == 0:
        return format_weekend_props_post(hundred_lines, "100")

    intro = (
        "As usual I've collated todays Premier League 1+ (100% hit-rates) and 2+ (80% hit-rates) "
        "player stats based on their last 5 games.\n\n"
        "Leave a like if you find these useful."
    )

    sections: List[str] = []
    for stat_key, header in WEEKEND_HEADERS_100:
        lines = _sorted_weekend_lines(hundred_lines.get(stat_key, []))
        if not lines:
            continue
        rendered = [header]
        rendered.extend(format_weekend_player_line(item) for item in lines)
        sections.append("\n".join(rendered))

    for stat_key, header in WEEKEND_HEADERS_80:
        lines = _sorted_weekend_lines(eighty_lines.get(stat_key, []))
        if not lines:
            continue
        rendered = [header]
        rendered.extend(format_weekend_player_line(item) for item in lines)
        sections.append("\n".join(rendered))

    if not sections:
        return intro

    return intro + "\n\n" + "\n\n".join(sections)
