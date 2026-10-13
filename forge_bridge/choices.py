"""Each exposed Forge decision as a sequence of single choices.

Every function returns the value Forge expects (Python side) or None, which
hands the decision to Forge's AI. Multi-selects ask one pick at a time, with a
"Done" option (index 0) once the minimum is reached.
"""

import jpype

from .labels import card_label
from .session import Option


def _zone(name: str):
    return getattr(jpype.JClass("forge.game.zone.ZoneType"), name)


def mulligan(session, seat: int, player, cards_to_return: int) -> bool | None:
    hand = ", ".join(card_label(c) for c in player.getCardsIn(_zone("Hand")))
    keep = "Keep this hand" + (f" (then put {cards_to_return} on the bottom)" if cards_to_return else "")
    choice = session.ask(seat, "mulligan", f"Mulligan? Your hand: {hand}", [Option(keep), Option("Mulligan")])
    return None if choice is None else choice == 0


def bottom(session, seat: int, player, hand, count: int) -> list | None:
    remaining = list(hand)
    chosen = []
    while len(chosen) < count and remaining:
        choice = session.ask(seat, "bottom",
                             f"Put a card on the bottom of your library ({len(chosen) + 1} of {count})",
                             [Option(card_label(c)) for c in remaining])
        if choice is None:
            return None
        chosen.append(remaining.pop(choice))
    return chosen
