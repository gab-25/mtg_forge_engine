"""The diff of two positions seen from the deciding seat, and its one-line summary (pure)."""

from mtg_forge_engine.outcome import outcome, summary

BEFORE = {"A": {"life": 20, "hand": 5, "graveyard": 1, "permanents": {5: "Grizzly Bears (2/2)"}},
          "B": {"life": 20, "hand": 5, "graveyard": 0, "permanents": {7: "Llanowar Elves (1/1)"}}}
AFTER = {"A": {"life": 15, "hand": 5, "graveyard": 2, "permanents": {}},
         "B": {"life": 20, "hand": 4, "graveyard": 0,
               "permanents": {7: "Llanowar Elves (1/1, tapped)", 9: "Goblin (1/1)"}}}


def test_outcome_is_the_diff_seen_from_the_deciding_seat():
    result = outcome(BEFORE, AFTER, you="B")
    assert result["you"] == {
        "name": "B", "life": [20, 20], "hand": [5, 4], "graveyard": [0, 0], "lost": [], "gained": ["Goblin (1/1)"],
        "changed": ["Llanowar Elves (1/1) → Llanowar Elves (1/1, tapped)"], "lost_game": False}
    assert result["opponents"][0]["lost"] == ["Grizzly Bears (2/2)"] and result["opponents"][0]["life"] == [20, 15]


def test_summary_lists_opponents_then_you_and_only_changes():
    assert summary(outcome(BEFORE, AFTER, you="B")) == (
        "A: 20 → 15 life, loses Grizzly Bears (2/2), graveyard 1 → 2; "
        "you: gains Goblin (1/1), Llanowar Elves (1/1) → Llanowar Elves (1/1, tapped), hand 5 → 4")
    assert summary(outcome(BEFORE, BEFORE, you="B")) == "no change"
    assert outcome(BEFORE, AFTER, you="B")["summary"].startswith("A: 20 → 15 life")


def test_a_player_who_lost_is_said_to_lose_the_game():
    after = {"A": {"life": -2, "hand": 5, "graveyard": 1, "permanents": {}, "lost_game": True},
             "B": {"life": 20, "hand": 5, "graveyard": 0, "permanents": {7: "Llanowar Elves (1/1)"}}}
    result = outcome(BEFORE, after, you="B")
    assert result["opponents"][0]["life"] == [20, -2] and result["opponents"][0]["lost_game"] is True
    assert result["you"]["lost_game"] is False
    assert summary(result) == "A: 20 → -2 life, loses Grizzly Bears (2/2), loses the game"
