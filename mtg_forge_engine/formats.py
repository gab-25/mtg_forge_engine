"""The formats a game can be played in. Deck legality is the client's job."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Format:
    label: str
    commander: bool
    starting_life: int = 20
    # The fewest and most seats a game may have.
    seats: tuple[int, int] = (2, 2)

    def seat_error(self, count: int) -> str | None:
        low, high = self.seats
        if low <= count <= high:
            return None
        allowed = str(low) if low == high else f"{low}-{high}"
        return f"{self.label} takes {allowed} seats, got {count}"


FORMATS: dict[str, Format] = {
    "standard": Format("Standard", False),
    "pioneer": Format("Pioneer", False),
    "modern": Format("Modern", False),
    "legacy": Format("Legacy", False),
    "vintage": Format("Vintage", False),
    "pauper": Format("Pauper", False),
    "duel_commander": Format("Duel Commander", True),
    "commander": Format("Commander", True, starting_life=40, seats=(2, 4)),
}
