"""The complete actions a simulated decision offers: a fixed enumeration, no merit.

Pure Python over any hashable items, so the order and the cut can be tested
without Forge. A plan is a list of pairs; the first plan is always the empty
one ("no attack", "no block"). Plans are cut at ``limit`` in the order they
are listed here, and a plan equal to an earlier one is dropped.
"""

from itertools import combinations


def _unique(plans: list[list], limit: int) -> list[list]:
    seen, kept = set(), []
    for plan in plans:
        key = frozenset(plan)
        if key in seen:
            continue
        seen.add(key)
        kept.append(plan)
        if len(kept) == limit:
            break
    return kept


def attack_plans(attackers: list, defenders: list, players: list, limit: int) -> list[list[tuple]]:
    """No attack; all attackers at each defender (players first); each attacker alone
    at each defender (players first); with at most four attackers, each pair at the
    first player."""
    ordered = [d for d in defenders if d in players] + [d for d in defenders if d not in players]
    plans: list[list[tuple]] = [[]]
    if attackers:
        plans += [[(a, d) for a in attackers] for d in ordered]
        plans += [[(a, d)] for d in ordered for a in attackers]
        if len(attackers) <= 4 and players:
            plans += [[(a, players[0]), (b, players[0])] for a, b in combinations(attackers, 2)]
    return _unique(plans, limit)


def block_plans(pairs: list[tuple], limit: int) -> list[list[tuple]]:
    """No block; each legal (blocker, attacker) alone; with at most three blockers and
    more than one attacker, two blockers on two different attackers and two blockers
    on one attacker (double block)."""
    legal = set(pairs)
    blockers = list(dict.fromkeys(b for b, _ in pairs))
    attackers = list(dict.fromkeys(a for _, a in pairs))
    plans: list[list[tuple]] = [[]] + [[pair] for pair in pairs]
    if len(blockers) <= 3 and len(attackers) > 1:
        for x, y in combinations(blockers, 2):
            plans += [[(x, a), (y, b)] for a in attackers for b in attackers
                      if a != b and (x, a) in legal and (y, b) in legal]
            plans += [[(x, a), (y, a)] for a in attackers if (x, a) in legal and (y, a) in legal]
    return _unique(plans, limit)
