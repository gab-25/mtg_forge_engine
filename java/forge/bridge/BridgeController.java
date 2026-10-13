package forge.bridge;

import forge.LobbyPlayer;
import forge.ai.ComputerUtil;
import forge.ai.PlayerControllerAi;
import forge.card.ColorSet;
import forge.game.Game;
import forge.game.GameEntity;
import forge.game.ability.ApiType;
import forge.game.card.Card;
import forge.game.card.CardCollection;
import forge.game.card.CardCollectionView;
import forge.game.combat.Combat;
import forge.game.player.DelayedReveal;
import forge.game.player.Player;
import forge.game.player.PlayerActionConfirmMode;
import forge.game.spellability.AbilitySub;
import forge.game.spellability.SpellAbility;
import forge.game.trigger.WrappedAbility;
import forge.util.collect.FCollectionView;
import org.apache.commons.lang3.tuple.ImmutablePair;

import java.util.ArrayList;
import java.util.Collections;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Forge's AI controller, except that the exposed decisions are first offered to a
 * DecisionHandler (Python). A null answer hands the decision back to the AI.
 */
public class BridgeController extends PlayerControllerAi {
    private final DecisionHandler handler;
    private final Set<SpellAbility> chosenExternally = Collections.newSetFromMap(new IdentityHashMap<>());

    public BridgeController(Game game, Player player, LobbyPlayer lobbyPlayer, DecisionHandler handler) {
        super(game, player, lobbyPlayer);
        this.handler = handler;
    }

    private void ai(String method) {
        handler.onAiDecision(player, method);
    }

    private static List<GameEntity> entities(Iterable<? extends GameEntity> items) {
        List<GameEntity> list = new ArrayList<>();
        for (GameEntity item : items) {
            list.add(item);
        }
        return list;
    }

    private static CardCollection cards(List<GameEntity> chosen) {
        CardCollection result = new CardCollection();
        for (GameEntity entity : chosen) {
            result.add((Card) entity);
        }
        return result;
    }

    private static boolean usesTargeting(SpellAbility sa) {
        for (SpellAbility s = sa; s != null; s = s.getSubAbility()) {
            if (s.usesTargeting()) {
                return true;
            }
        }
        return false;
    }

    // --- mulligan -------------------------------------------------------------

    @Override
    public boolean mulliganKeepHand(Player firstPlayer, int cardsToReturn) {
        Boolean keep = handler.mulliganKeepHand(player, cardsToReturn);
        if (keep != null) {
            return keep;
        }
        ai("mulliganKeepHand");
        return super.mulliganKeepHand(firstPlayer, cardsToReturn);
    }

    @Override
    public CardCollectionView tuckCardsViaMulligan(CardCollectionView hand, int cardsToReturn) {
        List<Card> chosen = handler.tuckCardsViaMulligan(player, hand, cardsToReturn);
        if (chosen != null) {
            return new CardCollection(chosen);
        }
        ai("tuckCardsViaMulligan");
        return super.tuckCardsViaMulligan(hand, cardsToReturn);
    }

    // --- priority and casting -------------------------------------------------

    @Override
    public List<SpellAbility> chooseSpellAbilityToPlay() {
        List<SpellAbility> chosen = handler.chooseSpellAbilityToPlay(player);
        if (chosen == null) {
            ai("chooseSpellAbilityToPlay");
            return super.chooseSpellAbilityToPlay();
        }
        if (chosen.isEmpty()) {
            return null; // pass priority
        }
        chosenExternally.addAll(chosen);
        return chosen;
    }

    @Override
    public boolean playChosenSpellAbility(SpellAbility sa) {
        if (!chosenExternally.remove(sa) || sa.isLandAbility()) {
            return super.playChosenSpellAbility(sa);
        }
        // The AI pays the costs; targets go through chooseTargetsFor (below).
        ComputerUtil.handlePlayingSpellAbility(player, sa, SpellAbility::setupTargets);
        return true;
    }

    @Override
    public boolean chooseTargetsFor(SpellAbility sa) {
        Boolean ok = handler.chooseTargetsFor(player, sa);
        if (ok != null) {
            return ok;
        }
        ai("chooseTargetsFor");
        return super.chooseTargetsFor(sa);
    }

    @Override
    public boolean playTrigger(Card host, WrappedAbility wrapper, boolean isMandatory) {
        SpellAbility sa = wrapper.getWrappedAbility();
        if (!usesTargeting(sa)) {
            return super.playTrigger(host, wrapper, isMandatory);
        }
        if (sa.getApi() == ApiType.Charm || sa.hasParam("TargetingPlayer") || !sa.setupTargets()) {
            ai("playTrigger");
            return super.playTrigger(host, wrapper, isMandatory);
        }
        return ComputerUtil.playNoStack(wrapper.getActivatingPlayer(), wrapper, getGame(), true);
    }

    // --- combat ---------------------------------------------------------------

    @Override
    public void declareAttackers(Player attacker, Combat combat) {
        if (handler.declareAttackers(attacker, combat) == null) {
            ai("declareAttackers");
            super.declareAttackers(attacker, combat);
        }
    }

    @Override
    public void declareBlockers(Player defender, Combat combat) {
        if (handler.declareBlockers(defender, combat) == null) {
            ai("declareBlockers");
            super.declareBlockers(defender, combat);
        }
    }

    // --- choosing cards and entities ------------------------------------------

    @Override
    public CardCollectionView chooseCardsForEffect(CardCollectionView sourceList, SpellAbility sa, String title, int min, int max, boolean isOptional, Map<String, Object> params) {
        List<GameEntity> chosen = handler.chooseEntities(player, sa, title, entities(sourceList), isOptional ? 0 : min, max);
        if (chosen == null) {
            ai("chooseCardsForEffect");
            return super.chooseCardsForEffect(sourceList, sa, title, min, max, isOptional, params);
        }
        return cards(chosen);
    }

    @Override
    @SuppressWarnings("unchecked")
    public <T extends GameEntity> T chooseSingleEntityForEffect(FCollectionView<T> optionList, DelayedReveal delayedReveal, SpellAbility sa, String title, boolean isOptional, Player targetedPlayer, Map<String, Object> params) {
        List<GameEntity> chosen = handler.chooseEntities(player, sa, title, entities(optionList), isOptional ? 0 : 1, 1);
        if (chosen == null) {
            ai("chooseSingleEntityForEffect");
            return super.chooseSingleEntityForEffect(optionList, delayedReveal, sa, title, isOptional, targetedPlayer, params);
        }
        return chosen.isEmpty() ? null : (T) chosen.get(0);
    }

    @Override
    @SuppressWarnings("unchecked")
    public <T extends GameEntity> List<T> chooseEntitiesForEffect(FCollectionView<T> optionList, int min, int max, DelayedReveal delayedReveal, SpellAbility sa, String title, Player targetedPlayer, Map<String, Object> params) {
        List<GameEntity> chosen = handler.chooseEntities(player, sa, title, entities(optionList), min, max);
        if (chosen == null) {
            ai("chooseEntitiesForEffect");
            return super.chooseEntitiesForEffect(optionList, min, max, delayedReveal, sa, title, targetedPlayer, params);
        }
        List<T> result = new ArrayList<>();
        for (GameEntity entity : chosen) {
            result.add((T) entity);
        }
        return result;
    }

    @Override
    public CardCollection chooseCardsToDiscardFrom(Player p, SpellAbility sa, CardCollection validCards, int min, int max, CardCollectionView visibleToChooser) {
        if (p == player) {
            List<GameEntity> chosen = handler.chooseEntities(player, sa, "Discard", entities(validCards), min, max);
            if (chosen != null) {
                return cards(chosen);
            }
        }
        ai("chooseCardsToDiscardFrom");
        return super.chooseCardsToDiscardFrom(p, sa, validCards, min, max, visibleToChooser);
    }

    @Override
    public CardCollectionView chooseCardsToDiscardToMaximumHandSize(int numDiscard) {
        List<GameEntity> chosen = handler.chooseEntities(player, null, "Discard down to your maximum hand size",
                entities(player.getCardsIn(forge.game.zone.ZoneType.Hand)), numDiscard, numDiscard);
        if (chosen == null) {
            ai("chooseCardsToDiscardToMaximumHandSize");
            return super.chooseCardsToDiscardToMaximumHandSize(numDiscard);
        }
        return cards(chosen);
    }

    @Override
    public CardCollectionView choosePermanentsToSacrifice(SpellAbility sa, int min, int max, CardCollectionView validTargets, String message) {
        List<GameEntity> chosen = handler.chooseEntities(player, sa, message == null ? "Sacrifice" : message, entities(validTargets), min, max);
        if (chosen == null) {
            ai("choosePermanentsToSacrifice");
            return super.choosePermanentsToSacrifice(sa, min, max, validTargets, message);
        }
        return cards(chosen);
    }

    // --- yes/no and modes -----------------------------------------------------

    @Override
    public boolean confirmAction(SpellAbility sa, PlayerActionConfirmMode mode, String message, List<String> options, Card cardToShow, Map<String, Object> params) {
        Boolean yes = handler.confirm(player, message);
        if (yes != null) {
            return yes;
        }
        ai("confirmAction");
        return super.confirmAction(sa, mode, message, options, cardToShow, params);
    }

    @Override
    public boolean confirmTrigger(WrappedAbility sa) {
        Boolean yes = handler.confirm(player, "Use the optional trigger of " + sa.getHostCard().getName() + ": " + sa.getStackDescription());
        if (yes != null) {
            return yes;
        }
        ai("confirmTrigger");
        return super.confirmTrigger(sa);
    }

    @Override
    public List<AbilitySub> chooseModeForAbility(SpellAbility sa, List<AbilitySub> possible, int min, int num, boolean allowRepeat) {
        List<AbilitySub> chosen = handler.chooseModes(player, sa, possible, min, num, allowRepeat);
        if (chosen != null) {
            return chosen;
        }
        ai("chooseModeForAbility");
        return super.chooseModeForAbility(sa, possible, min, num, allowRepeat);
    }

    // --- decisions left to the AI, logged -------------------------------------

    @Override
    public Map<Card, Integer> assignCombatDamage(Card attacker, CardCollectionView blockers, CardCollectionView remaining, int damageDealt, GameEntity defender, boolean overrideOrder) {
        ai("assignCombatDamage");
        return super.assignCombatDamage(attacker, blockers, remaining, damageDealt, defender, overrideOrder);
    }

    @Override
    public CardCollection orderBlockers(Card attacker, CardCollection blockers) {
        ai("orderBlockers");
        return super.orderBlockers(attacker, blockers);
    }

    @Override
    public ImmutablePair<CardCollection, CardCollection> arrangeForScry(CardCollection topN) {
        ai("arrangeForScry");
        return super.arrangeForScry(topN);
    }

    @Override
    public ImmutablePair<CardCollection, CardCollection> arrangeForSurveil(CardCollection topN) {
        ai("arrangeForSurveil");
        return super.arrangeForSurveil(topN);
    }

    @Override
    public int chooseNumber(SpellAbility sa, String title, int min, int max) {
        ai("chooseNumber");
        return super.chooseNumber(sa, title, min, max);
    }

    @Override
    public byte chooseColor(String message, SpellAbility sa, ColorSet colors) {
        ai("chooseColor");
        return super.chooseColor(message, sa, colors);
    }
}
