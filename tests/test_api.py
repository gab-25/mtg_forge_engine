import random
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


def play(client, game_id, rng, timeout=300):
    deadline = time.monotonic() + timeout
    while client.get(f"/games/{game_id}").json()["status"] in ("queued", "running"):
        assert time.monotonic() < deadline
        response = client.get("/decisions", params={"wait": 1, "game": game_id})
        if response.status_code == 204:
            continue
        decision = response.json()
        client.post(f"/decisions/{decision['decision_id']}",
                    json={"choice": rng.randrange(len(decision["options"])), "meta": {"confidence": 0.5}})


def wait_until_ended(client, game_id, timeout=60):
    deadline = time.monotonic() + timeout
    while (status := client.get(f"/games/{game_id}").json()["status"]) in ("queued", "running"):
        assert time.monotonic() < deadline
        time.sleep(0.2)
    return status


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ready" and body["cards"] > 20000


def test_full_game_over_http(client):
    response = new_game(client)
    assert response.status_code == 201
    game = response.json()
    assert [s["name"] for s in game["seats"]] == ["Red", "Green"]
    play(client, game["id"], random.Random(5))
    final = client.get(f"/games/{game['id']}").json()
    assert final["status"] == "finished"
    events = client.get(f"/games/{game['id']}/events", params={"since": 0}).json()
    assert events["next"] == len(events["events"])
    assert events["events"][-1]["kind"] == "game_over"
    decisions = [e for e in events["events"] if e["kind"] == "decision"]
    assert decisions and decisions[0]["payload"]["confidence"] == 0.5
    tail = client.get(f"/games/{game['id']}/events", params={"since": events["next"]}).json()
    assert tail["events"] == []


def test_unknown_cards_422(client):
    response = new_game(client, seats=[{"name": "A", "decklist": "4 Lightning Bolt\n1 Nope Card"},
                                       {"name": "B", "decklist": GREEN}])
    assert response.status_code == 422
    assert response.json()["detail"] == {"unresolved": {"A": ["Nope Card"]}}


def test_duel_commander_requires_a_commander(client):
    response = new_game(client, fmt="duel_commander",
                        seats=[{"name": "A", "decklist": "100 Mountain"}, {"name": "B", "decklist": DUEL_COMMANDER}])
    assert response.status_code == 422


def test_bad_requests_422(client):
    assert new_game(client, fmt="nope").status_code == 422
    assert client.post("/games", json={"format": "modern", "seats": [{"name": "A", "decklist": RED}]}).status_code == 422


def test_answers_409_and_422_and_abort(client):
    game = new_game(client, seed=9).json()
    decision = client.get("/decisions", params={"wait": 30, "game": game["id"]}).json()
    out_of_range = client.post(f"/decisions/{decision['decision_id']}", json={"choice": len(decision["options"])})
    assert out_of_range.status_code == 422
    neither = client.post(f"/decisions/{decision['decision_id']}", json={})
    assert neither.status_code == 422
    assert client.post(f"/decisions/{decision['decision_id']}", json={"choice": 0}).status_code == 204
    assert client.post(f"/decisions/{decision['decision_id']}", json={"choice": 0}).status_code == 409
    assert client.delete(f"/games/{game['id']}").status_code == 204
    assert wait_until_ended(client, game["id"]) == "aborted"


def test_unknown_game_404(client):
    assert client.get("/games/nope").status_code == 404
    assert client.get("/games/nope/events").status_code == 404
    assert client.delete("/games/nope").status_code == 404


def test_lease_timeout_hands_the_decision_to_forge(client):
    from mtg_forge_engine import api

    api.queue.timeout = 0.5
    try:
        game = new_game(client, seed=10).json()
        leased = client.get("/decisions", params={"wait": 30, "game": game["id"]}).json()
        time.sleep(1.5)
        late = client.post(f"/decisions/{leased['decision_id']}", json={"choice": 0})
        assert late.status_code == 409
        events = client.get(f"/games/{game['id']}/events").json()["events"]
        assert any(e["kind"] == "fallback" and e["payload"]["reason"] == "timeout" for e in events)
        client.delete(f"/games/{game['id']}")
        wait_until_ended(client, game["id"])
    finally:
        api.queue.timeout = api.settings.decision_timeout
