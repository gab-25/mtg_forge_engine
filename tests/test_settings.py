from mtg_forge_engine.formats import FORMATS
from mtg_forge_engine.settings import load_settings


def test_defaults():
    s = load_settings({})
    assert (s.max_concurrent_games, s.decision_timeout, s.max_turns, s.game_ttl, s.forge_home) == (
        16, 120.0, 50, 3600.0, "/opt/forge")


def test_overrides():
    s = load_settings({"MAX_CONCURRENT_GAMES": "4", "DECISION_TIMEOUT": "1.5", "MAX_TURNS": "7",
                       "GAME_TTL": "60", "FORGE_HOME": "/x"})
    assert (s.max_concurrent_games, s.decision_timeout, s.max_turns, s.game_ttl, s.forge_home) == (
        4, 1.5, 7, 60.0, "/x")


def test_formats():
    assert set(FORMATS) == {"standard", "pioneer", "modern", "legacy", "vintage", "pauper", "duel_commander",
                            "commander"}
    assert FORMATS["duel_commander"].commander and FORMATS["duel_commander"].starting_life == 20
    assert not FORMATS["modern"].commander


def test_orphan_timeout():
    assert load_settings({}).orphan_timeout == 600.0
    assert load_settings({"ORPHAN_TIMEOUT": "5"}).orphan_timeout == 5.0
