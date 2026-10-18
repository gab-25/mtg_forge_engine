"""The fixed enumeration of attack and block plans (pure)."""

from mtg_forge_engine.candidates import attack_plans, block_plans


def test_attack_plans_order_and_cut():
    plans = attack_plans(["a", "b"], ["P", "W"], ["P"], limit=8)
    assert plans[:3] == [[], [("a", "P"), ("b", "P")], [("a", "W"), ("b", "W")]]
    assert plans[3:7] == [[("a", "P")], [("b", "P")], [("a", "W")], [("b", "W")]]
    assert len(plans) == 7  # the only pair equals "all": dropped as a duplicate
    assert attack_plans(["a", "b", "c"], ["P"], ["P"], limit=4) == [
        [], [("a", "P"), ("b", "P"), ("c", "P")], [("a", "P")], [("b", "P")]]


def test_pairs_only_up_to_four_attackers():
    plans = attack_plans(list("abcde"), ["P"], ["P"], limit=50)
    assert all(len(p) != 2 for p in plans[2:])
    assert [("a", "P"), ("b", "P")] in attack_plans(list("abcd"), ["P"], ["P"], limit=50)


def test_no_attackers_gives_only_no_attack():
    assert attack_plans([], ["P"], ["P"], limit=8) == [[]]


def test_planeswalkers_are_defenders_after_players():
    assert attack_plans(["a"], ["PW", "P"], ["P"], limit=8) == [[], [("a", "P")], [("a", "PW")]]


def test_block_plans():
    pairs = [("x", "A"), ("x", "B"), ("y", "A")]
    plans = block_plans(pairs, limit=8)
    assert plans[:4] == [[], [("x", "A")], [("x", "B")], [("y", "A")]]
    assert [("x", "B"), ("y", "A")] in plans and [("x", "A"), ("y", "A")] in plans
    assert [("x", "A"), ("y", "B")] not in plans  # ("y", "B") is not legal
    assert block_plans(pairs, limit=3) == [[], [("x", "A")], [("x", "B")]]
    # Four blockers: singles only.
    assert block_plans([("x", "A"), ("y", "A"), ("z", "A"), ("w", "A")], limit=50)[5:] == []
