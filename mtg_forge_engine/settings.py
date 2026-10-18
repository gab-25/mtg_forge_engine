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
    # Simulated outcomes on attack, block and priority decisions (see the README).
    simulate: bool = False
    max_candidates: int = 8
    max_targets_per_ability: int = 4
    simulation_budget_ms: int = 1500


def load_settings(env: Mapping[str, str] = os.environ) -> Settings:
    return Settings(
        max_concurrent_games=int(env.get("MAX_CONCURRENT_GAMES", 16)),
        decision_timeout=float(env.get("DECISION_TIMEOUT", 120)),
        max_turns=int(env.get("MAX_TURNS", 50)),
        game_ttl=float(env.get("GAME_TTL", 3600)),
        forge_home=env.get("FORGE_HOME", "/opt/forge"),
        orphan_timeout=float(env.get("ORPHAN_TIMEOUT", 600)),
        simulate=str(env.get("SIMULATE", "0")).strip().lower() in ("1", "true", "yes"),
        max_candidates=int(env.get("MAX_CANDIDATES", 8)),
        max_targets_per_ability=int(env.get("MAX_TARGETS_PER_ABILITY", 4)),
        simulation_budget_ms=int(env.get("SIMULATION_BUDGET_MS", 1500)),
    )
