from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class MarketConfig:
    stat_type_id: int
    label: str
    thresholds: tuple[int, ...]
    odds_market_key: str


LEAGUES = {
    8: "Premier League",
    9: "Championship",
    72: "Eredivisie",
    82: "Bundesliga",
    301: "Ligue 1",
    384: "Serie A",
    390: "Serie B",
    444: "Eliteserien",
    501: "Scottish Premiership",
    564: "La Liga",
    568: "La Liga 2",
    600: "Super Lig",
}

MARKETS = [
    MarketConfig(42, "shots", (1, 2, 3, 4), "player_shots"),
    MarketConfig(86, "shots_on_target", (1, 2), "player_shots_on_target"),
    MarketConfig(56, "fouls_committed", (1, 2), "player_fouls_committed"),
    MarketConfig(96, "fouls_drawn", (1, 2), "player_fouls_drawn"),
    MarketConfig(78, "tackles", (1, 2, 3), "player_tackles"),
]

# Bookmaker IDs from OddsSearch data.
BOOKMAKER_IDS = (2, 3, 4)  # Bet365, Kambi, Paddy Power
BOOKMAKER_NAMES = {
    2: "Bet365",
    3: "Kambi",
    4: "Paddy Power",
}


@dataclass(frozen=True)
class Settings:
    supabase_db_url: str
    anthropic_api_key: str | None
    model_name: str
    lookahead_hours: int
    min_appearances: int
    min_edge_pct: float
    min_confidence: float
    max_candidates: int
    include_similar: bool
    use_telegram: bool
    telegram_bot_token: str | None
    telegram_chat_id: str | None


def get_settings() -> Settings:
    return Settings(
        supabase_db_url=os.environ.get("SUPABASE_DB_URL", ""),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
        model_name=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
        lookahead_hours=int(os.environ.get("PROP_LOOKAHEAD_HOURS", "48")),
        min_appearances=int(os.environ.get("PROP_MIN_APPEARANCES", "5")),
        min_edge_pct=float(os.environ.get("PROP_MIN_EDGE_PCT", "10")),
        min_confidence=float(os.environ.get("PROP_MIN_CONFIDENCE", "65")),
        max_candidates=int(os.environ.get("PROP_MAX_PICKS", "10")),
        include_similar=os.environ.get("PROP_INCLUDE_SIMILAR", "1") == "1",
        use_telegram=bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID")),
        telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID"),
    )
