"""Configuration from environment variables (see the README)."""

import os
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    max_concurrent_games: int = 16
    decision_timeout: float = 120.0
    max_turns: int = 50
    game_ttl: float = 3600.0
    forge_home: str = "/opt/forge"
    orphan_timeout: float = 600.0


def load_settings(env: Mapping[str, str] = os.environ) -> Settings:
    return Settings(
        max_concurrent_games=int(env.get("MAX_CONCURRENT_GAMES", 16)),
        decision_timeout=float(env.get("DECISION_TIMEOUT", 120)),
        max_turns=int(env.get("MAX_TURNS", 50)),
        game_ttl=float(env.get("GAME_TTL", 3600)),
        forge_home=env.get("FORGE_HOME", "/opt/forge"),
        orphan_timeout=float(env.get("ORPHAN_TIMEOUT", 600)),
    )
