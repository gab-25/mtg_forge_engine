package forge.bridge;

import forge.game.GameEntity;
import forge.game.card.Card;
import forge.game.card.CardCollectionView;
import forge.game.combat.Combat;
import forge.game.player.Player;
import forge.game.spellability.AbilitySub;
import forge.game.spellability.SpellAbility;

import java.util.List;

/**
 * Implemented in Python (mtg_forge_engine.handler). Every method may return null:
 * Forge's AI then makes the decision instead.
 */
public interface DecisionHandler {
    Boolean mulliganKeepHand(Player player, int cardsToReturn);

    List<Card> tuckCardsViaMulligan(Player player, CardCollectionView hand, int cardsToReturn);

    /** An empty list passes priority. */
    List<SpellAbility> chooseSpellAbilityToPlay(Player player);

    Boolean chooseTargetsFor(Player player, SpellAbility sa);

    Boolean declareAttackers(Player player, Combat combat);

    Boolean declareBlockers(Player player, Combat combat);

    List<GameEntity> chooseEntities(Player player, SpellAbility sa, String title, List<GameEntity> options, int min, int max);

    Boolean confirm(Player player, String message);

    List<AbilitySub> chooseModes(Player player, SpellAbility sa, List<AbilitySub> possible, int min, int num, boolean allowRepeat);

    /** Called whenever Forge's AI makes a decision for this player that is worth logging. */
    void onAiDecision(Player player, String method);
}
