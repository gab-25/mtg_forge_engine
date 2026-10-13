"""Text decklists (Moxfield / MTGO style) -> quantities and card names. Pure, no Forge."""

import re
from dataclasses import dataclass, field

HEADERS = {
    "commander": "commanders",
    "commanders": "commanders",
    "deck": "main",
    "main": "main",
    "mainboard": "main",
    "maindeck": "main",
    "sideboard": "sideboard",
}
LINE = re.compile(r"^(?:(\d+)\s*x?\s+)?(.+)$", re.IGNORECASE)
SET_SUFFIX = re.compile(r"\s+\([A-Za-z0-9]{2,6}\)(?:\s+\S+)?$")
TAGS = re.compile(r"\s*\*[A-Za-z]+\*")


@dataclass
class ParsedDeck:
    main: list[tuple[int, str]] = field(default_factory=list)
    commanders: list[tuple[int, str]] = field(default_factory=list)
    sideboard: list[tuple[int, str]] = field(default_factory=list)


def parse_decklist(text: str) -> ParsedDeck:
    deck = ParsedDeck()
    section = "main"
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("//", "#")):
            continue
        header = line.rstrip(":").strip().lower()
        if header in HEADERS:
            section = HEADERS[header]
            continue
        is_commander = "*CMDR*" in line.upper()
        line = SET_SUFFIX.sub("", TAGS.sub("", line)).strip()
        match = LINE.match(line)
        quantity = int(match.group(1)) if match.group(1) else 1
        getattr(deck, "commanders" if is_commander else section).append((quantity, match.group(2).strip()))
    return deck
