import time

import pytest

from tests.decks import DUEL_COMMANDER, GREEN, RED

pytestmark = pytest.mark.jvm


@pytest.fixture(scope="module")
def client(forge):
    from fastapi.testclient import TestClient

    from mtg_forge_engine.api import app

    with TestClient(app) as client:
        deadline = time.monotonic() + 300
        while client.get("/health").status_code != 200:
            assert time.monotonic() < deadline
            time.sleep(1)
        yield client


def new_game(client, seats=None, fmt="modern", seed=5):
    seats = seats or [{"name": "Red", "decklist": RED}, {"name": "Green", "decklist": GREEN}]
    return client.post("/games", json={"format": fmt, "seed": seed, "seats": seats})


def wait_until_ended(client, game_id, timeout=300):
    deadline = time.monotonic() + timeout
    while (status := client.get(f"/games/{game_id}").json()["status"]) in ("queued", "running"):
        assert time.monotonic() < deadline
        time.sleep(0.2)
    return status


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ready" and body["cards"] > 20000


def test_full_game_over_http(client):
    seats = [{"name": "Red", "decklist": RED}, {"name": "Green", "decklist": GREEN, "controller": "external"}]
    response = new_game(client, seats=seats)  # unknown keys, like the old controller, are ignored
    assert response.status_code == 201
    game = response.json()
    assert game["seats"] == [{"name": "Red", "unsupported_cards": []}, {"name": "Green", "unsupported_cards": []}]
    assert wait_until_ended(client, game["id"]) == "finished"
    final = client.get(f"/games/{game['id']}").json()
    assert final["end_reason"]
    events = client.get(f"/games/{game['id']}/events", params={"since": 0}).json()
    assert events["next"] == len(events["events"])
    assert {e["kind"] for e in events["events"]} == {"log", "game_over"}
    assert events["events"][-1]["kind"] == "game_over"
    assert events["events"][-1]["payload"]["winner"] == final["winner"]
    tail = client.get(f"/games/{game['id']}/events", params={"since": events["next"]}).json()
    assert tail["events"] == []


def test_unknown_cards_422(client):
    response = new_game(client, seats=[{"name": "A", "decklist": "4 Lightning Bolt\n1 Nope Card"},
                                       {"name": "B", "decklist": GREEN}])
    assert response.status_code == 422
    assert response.json()["detail"] == {"unresolved": {"A": ["Nope Card"]}}


def test_check_deck_names_unknown_cards_without_starting_a_game(client):
    response = client.post("/decks/check", json={"format": "modern", "decklist": "4 Lightning Bolt\n1 Nope Card"})
    assert response.status_code == 200
    assert response.json() == {"unresolved": ["Nope Card"], "unsupported_cards": [], "missing_commander": False}
    response = client.post("/decks/check", json={"format": "duel_commander", "decklist": "1 Forest"})
    assert response.json()["missing_commander"] is True
    assert client.post("/decks/check", json={"format": "nope", "decklist": "1 Forest"}).status_code == 422


def test_duel_commander_requires_a_commander(client):
    response = new_game(client, fmt="duel_commander",
                        seats=[{"name": "A", "decklist": "100 Mountain"}, {"name": "B", "decklist": DUEL_COMMANDER}])
    assert response.status_code == 422


def test_bad_requests_422(client):
    assert new_game(client, fmt="nope").status_code == 422
    assert client.post("/games", json={"format": "modern", "seats": [{"name": "A", "decklist": RED}]}).status_code == 422


def test_abort(client):
    game = new_game(client, seed=9, seats=[{"name": "G1", "decklist": GREEN},
                                           {"name": "G2", "decklist": GREEN}]).json()
    assert client.delete(f"/games/{game['id']}").status_code == 204
    assert wait_until_ended(client, game["id"], timeout=60) == "aborted"
    assert client.get(f"/games/{game['id']}").json()["end_reason"] == "aborted"


def test_decisions_are_gone(client):
    assert client.get("/decisions").status_code in (404, 405)
    assert client.post("/decisions/x", json={"choice": 0}).status_code in (404, 405)


def test_unknown_game_404(client):
    assert client.get("/games/nope").status_code == 404
    assert client.get("/games/nope/events").status_code == 404
    assert client.delete("/games/nope").status_code == 404
