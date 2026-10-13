from forge_bridge.decklist import parse_decklist


def test_quantities_and_names():
    deck = parse_decklist("4 Lightning Bolt\n4x Goblin Guide\nMountain\n")
    assert deck.main == [(4, "Lightning Bolt"), (4, "Goblin Guide"), (1, "Mountain")]


def test_set_code_collector_number_and_tags_are_dropped():
    deck = parse_decklist("1 Ragavan, Nimble Pilferer (MH2) 138 *F*\n2 Fire // Ice (MH2)\n")
    assert deck.main == [(1, "Ragavan, Nimble Pilferer"), (2, "Fire // Ice")]


def test_sections_and_commander_tag():
    text = """
    Commander
    1 Kenrith, the Returned King

    Deck
    1 Sol Ring
    1 Arcane Signet *CMDR*
    // a comment
    Sideboard:
    2 Pyroblast
    """
    deck = parse_decklist(text)
    assert deck.commanders == [(1, "Kenrith, the Returned King"), (1, "Arcane Signet")]
    assert deck.main == [(1, "Sol Ring")]
    assert deck.sideboard == [(2, "Pyroblast")]


def test_blank_and_comment_lines_are_ignored():
    assert parse_decklist("\n# x\n// y\n").main == []
