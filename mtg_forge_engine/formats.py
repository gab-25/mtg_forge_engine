"""The formats a game can be played in. Deck legality is the client's job."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Format:
    label: str
    commander: bool
    starting_life: int = 20


FORMATS: dict[str, Format] = {
    "standard": Format("Standard", False),
    "pioneer": Format("Pioneer", False),
    "modern": Format("Modern", False),
    "legacy": Format("Legacy", False),
    "vintage": Format("Vintage", False),
    "pauper": Format("Pauper", False),
    "duel_commander": Format("Duel Commander", True),
}
