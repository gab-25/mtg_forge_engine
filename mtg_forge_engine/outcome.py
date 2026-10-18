"""What changed between two positions, seen from the seat that decides. Pure Python.

A position is ``{player name: {"life", "hand", "graveyard", "permanents", "lost_game"}}``,
hand and graveyard as counts, ``permanents`` as ``{id: label}``, ``lost_game`` when the
player has lost (optional, False by default). The outcome lists,
for the deciding seat ("you") and each opponent, the numbers before and after
and the permanents lost, gained and changed, plus a one-line summary in a fixed
order: opponents first, then you.
"""


def _delta(name: str, before: dict, after: dict) -> dict:
    old, new = before.get("permanents", {}), after.get("permanents", {})
    return {
        "name": name,
        "life": [before["life"], after["life"]],
        "hand": [before["hand"], after["hand"]],
        "graveyard": [before["graveyard"], after["graveyard"]],
        "lost": sorted(label for pid, label in old.items() if pid not in new),
        "gained": sorted(label for pid, label in new.items() if pid not in old),
        "changed": sorted(f"{old[pid]} → {new[pid]}" for pid in old if pid in new and old[pid] != new[pid]),
        "lost_game": bool(after.get("lost_game", False)),
    }


def outcome(before: dict, after: dict, you: str) -> dict:
    """``{"you": delta, "opponents": [delta…], "summary": str}``; a player gone from ``after`` keeps its last numbers."""
    deltas = {name: _delta(name, before[name], after.get(name, before[name])) for name in before}
    result = {"you": deltas[you], "opponents": [d for name, d in deltas.items() if name != you]}
    result["summary"] = summary(result)
    return result


def _parts(delta: dict) -> list[str]:
    parts = []
    if delta["life"][0] != delta["life"][1]:
        parts.append(f"{delta['life'][0]} → {delta['life'][1]} life")
    if delta["lost"]:
        parts.append("loses " + ", ".join(delta["lost"]))
    if delta["gained"]:
        parts.append("gains " + ", ".join(delta["gained"]))
    parts += delta["changed"]
    if delta["hand"][0] != delta["hand"][1]:
        parts.append(f"hand {delta['hand'][0]} → {delta['hand'][1]}")
    if delta["graveyard"][0] != delta["graveyard"][1]:
        parts.append(f"graveyard {delta['graveyard'][0]} → {delta['graveyard'][1]}")
    if delta.get("lost_game"):
        parts.append("loses the game")
    return parts


def summary(result: dict) -> str:
    lines = []
    for delta in [*result["opponents"], result["you"]]:
        parts = _parts(delta)
        if parts:
            name = "you" if delta is result["you"] else delta["name"]
            lines.append(f"{name}: " + ", ".join(parts))
    return "; ".join(lines) or "no change"
