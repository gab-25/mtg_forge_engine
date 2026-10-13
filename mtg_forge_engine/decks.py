"""A parsed decklist -> a Forge Deck, with the names Forge does not know."""

from dataclasses import dataclass

import jpype

from .decklist import ParsedDeck


@dataclass(frozen=True)
class DeckBuild:
    deck: object  # forge.deck.Deck
    unresolved: list[str]
    # Cards Forge knows but marks as unsupported (they play as placeholders).
    unsupported: list[str]


def _lookup(db, name: str):
    card = db.getCard(name)
    if card is None and " // " in name:
        # Scryfall names double-faced cards "Front // Back"; Forge knows the front face.
        card = db.getCard(name.split(" // ")[0])
    return card


def build_deck(name: str, parsed: ParsedDeck, *, commander: bool) -> DeckBuild:
    db = jpype.JClass("forge.StaticData").instance().getCommonCards()
    section = jpype.JClass("forge.deck.DeckSection")
    deck = jpype.JClass("forge.deck.Deck")(name)
    unresolved: list[str] = []
    unsupported: list[str] = []
    pools = [
        (deck.getMain(), parsed.main + ([] if commander else parsed.commanders)),
        (deck.getOrCreate(section.Commander), parsed.commanders if commander else []),
        (deck.getOrCreate(section.Sideboard), parsed.sideboard),
    ]
    for pool, entries in pools:
        for quantity, card_name in entries:
            card = _lookup(db, card_name)
            if card is None:
                unresolved.append(card_name)
                continue
            if card.getRules().isUnsupported():
                unsupported.append(str(card.getName()))
            pool.add(card, quantity)
    return DeckBuild(deck, unresolved, unsupported)
