"""Seat counts per format. Pure: the API checks them before it needs Forge."""

from fastapi.testclient import TestClient

from mtg_forge_engine.api import app
from mtg_forge_engine.formats import FORMATS


def test_commander_format():
    commander = FORMATS["commander"]
    assert (commander.commander, commander.starting_life, commander.seats) == (True, 40, (2, 4))
    assert all(fmt.seats == (2, 2) for key, fmt in FORMATS.items() if key != "commander")


def test_seat_error():
    assert FORMATS["commander"].seat_error(4) is None
    assert FORMATS["commander"].seat_error(5) == "Commander takes 2-4 seats, got 5"
    assert FORMATS["modern"].seat_error(2) is None
    assert FORMATS["modern"].seat_error(3) == "Modern takes 2 seats, got 3"


def body(fmt, count):
    return {"format": fmt, "seats": [{"name": f"P{i}", "decklist": "1 Forest"} for i in range(count)]}


def test_seat_count_outside_the_format_is_422():
    client = TestClient(app)  # no lifespan: Forge is not loading
    for fmt, count in [("modern", 3), ("duel_commander", 4), ("commander", 1), ("commander", 5)]:
        response = client.post("/games", json=body(fmt, count))
        assert response.status_code == 422, (fmt, count)
    assert "Modern takes 2 seats, got 3" in client.post("/games", json=body("modern", 3)).text


def test_seat_count_inside_the_format_reaches_forge():
    client = TestClient(app)
    # 503: the request passed validation and only lacks a running Forge.
    assert client.post("/games", json=body("commander", 4)).status_code == 503
    assert client.post("/games", json=body("modern", 2)).status_code == 503


def session_with(fmt, count, max_turns=50):
    import threading

    from mtg_forge_engine.queue import DecisionQueue
    from mtg_forge_engine.session import GameSession

    # Never started: the constructor does not touch Forge.
    return GameSession("t", FORMATS[fmt], 1, [None] * count, DecisionQueue(1), max_turns, threading.BoundedSemaphore(1))


def test_turn_limit_counts_rounds_above_two_seats():
    assert session_with("modern", 2).turn_limit == 50
    assert session_with("commander", 2).turn_limit == 50
    assert session_with("commander", 3).turn_limit == 150
    assert session_with("commander", 4, max_turns=10).turn_limit == 40
