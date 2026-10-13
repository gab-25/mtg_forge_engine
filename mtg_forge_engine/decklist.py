"""Text decklists (Moxfield / MTGO / Arena style) -> quantities and card names. Pure, no Forge."""

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
    # Arena exports: the companion is also listed in the sideboard.
    "companion": "companion",
    # Arena exports: "About" is followed by "Name <deck name>".
    "about": "about",
}
LINE = re.compile(r"^(?:(\d+)\s*x?\s+)?(.+)$", re.IGNORECASE)
SET_SUFFIX = re.compile(r"\s+\([A-Za-z0-9]{2,6}\)(?:\s+\S+)?$")
TAGS = re.compile(r"\s*\*[A-Za-z]+\*")
SIDEBOARD_PREFIX = re.compile(r"^SB:\s*", re.IGNORECASE)


@dataclass
class ParsedDeck:
    main: list[tuple[int, str]] = field(default_factory=list)
    commanders: list[tuple[int, str]] = field(default_factory=list)
    sideboard: list[tuple[int, str]] = field(default_factory=list)


def _header(line: str) -> str | None:
    return HEADERS.get(line.rstrip(":").strip().lower())


def parse_decklist(text: str) -> ParsedDeck:
    deck = ParsedDeck()
    lines = [raw.strip() for raw in text.splitlines()]
    # MTGO lists have no headers: a blank line after the main deck starts the sideboard.
    headerless = not any(_header(line) for line in lines)
    companions: list[tuple[int, str]] = []
    section = "main"
    for line in lines:
        if not line:
            if headerless and deck.main:
                section = "sideboard"
            continue
        if line.startswith(("//", "#")):
            continue
        header = _header(line)
        if header:
            section = header
            continue
        if section == "about":
            continue
        target = section
        if SIDEBOARD_PREFIX.match(line):
            line = SIDEBOARD_PREFIX.sub("", line)
            target = "sideboard"
        if "*CMDR*" in line.upper():
            target = "commanders"
        line = SET_SUFFIX.sub("", TAGS.sub("", line)).strip()
        match = LINE.match(line)
        entry = (int(match.group(1)) if match.group(1) else 1, match.group(2).strip())
        if target == "companion":
            companions.append(entry)
        else:
            getattr(deck, target).append(entry)
    sideboard_names = {name for _, name in deck.sideboard}
    deck.sideboard += [entry for entry in companions if entry[1] not in sideboard_names]
    return deck
