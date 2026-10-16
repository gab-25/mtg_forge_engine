package forge.bridge;

import forge.game.GameEntity;
import forge.game.card.Card;
import forge.game.card.CardCollectionView;
import forge.game.combat.Combat;
import forge.game.player.Player;
import forge.game.spellability.AbilitySub;
import forge.game.spellability.SpellAbility;

import java.util.List;
import java.util.Map;
import java.util.function.Supplier;

/**
 * Implemented in Python (mtg_forge_engine.handler). Every method may return null:
 * Forge's AI then makes the decision instead.
 *
 * The last argument of each decision is what Forge's AI would answer, computed on
 * demand without touching the game; it yields null when the AI has no answer.
 */
public interface DecisionHandler {
    Boolean mulliganKeepHand(Player player, int cardsToReturn, Supplier<Boolean> ai);

    List<Card> tuckCardsViaMulligan(Player player, CardCollectionView hand, int cardsToReturn, Supplier<List<Card>> ai);

    /** An empty list passes priority; so does an empty AI answer. */
    List<SpellAbility> chooseSpellAbilityToPlay(Player player, Supplier<List<SpellAbility>> ai);

    /** ai: the targets the AI would choose for sa itself. */
    Boolean chooseTargetsFor(Player player, SpellAbility sa, Supplier<List<Object>> ai);

    /** ai: attacker to defender. */
    Boolean declareAttackers(Player player, Combat combat, Supplier<Map<Card, GameEntity>> ai);

    /** ai: blocker to the attackers it blocks. */
    Boolean declareBlockers(Player player, Combat combat, Supplier<Map<Card, List<Card>>> ai);

    List<GameEntity> chooseEntities(Player player, SpellAbility sa, String title, List<GameEntity> options, int min, int max, Supplier<List<GameEntity>> ai);

    Boolean confirm(Player player, String message, Supplier<Boolean> ai);

    List<AbilitySub> chooseModes(Player player, SpellAbility sa, List<AbilitySub> possible, int min, int num, boolean allowRepeat, Supplier<List<AbilitySub>> ai);

    /** A spell or ability the client chose was not played; reason: "modes", "targets" or "costs". */
    void onPlayFailed(Player player, SpellAbility sa, String reason);

    /** Called whenever Forge's AI makes a decision for this player that is worth logging. */
    void onAiDecision(Player player, String method);
}
