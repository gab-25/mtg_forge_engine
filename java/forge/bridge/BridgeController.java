package forge.bridge;

import forge.LobbyPlayer;
import forge.ai.ComputerUtil;
import forge.ai.ComputerUtilAbility;
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
import forge.game.zone.Zone;
import forge.game.zone.ZoneType;
import forge.util.collect.FCollectionView;
import org.apache.commons.lang3.tuple.ImmutablePair;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.IdentityHashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Supplier;

/**
 * Forge's AI controller, except that the exposed decisions are first offered to a
 * DecisionHandler (Python). A null answer hands the decision back to the AI.
 */
public class BridgeController extends PlayerControllerAi {
    private final DecisionHandler handler;
    private final Set<SpellAbility> chosenExternally = Collections.newSetFromMap(new IdentityHashMap<>());
    // True while the AI plays an ability it chose itself: it has already picked
    // that ability's modes and answers its own questions about it.
    private boolean aiPlaying = false;
    // True while the AI only evaluates a decision for the handler (see preview):
    // every question it asks itself is answered by the AI, unlogged.
    private boolean evaluating = false;

    public BridgeController(Game game, Player player, LobbyPlayer lobbyPlayer, DecisionHandler handler) {
        super(game, player, lobbyPlayer);
        this.handler = handler;
    }

    private void ai(String method) {
        if (!evaluating) {
            handler.onAiDecision(player, method);
        }
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

    /**
     * The answer Forge's AI would give, computed when the handler asks for it. The
     * caller undoes what the AI leaves on the game; the AI draws from a copy of the
     * game's random generator, so the seed still replays the same game. A failure
     * yields null: no answer.
     */
    private <T> Supplier<T> preview(Supplier<T> answer) {
        return () -> {
            boolean outer = evaluating;
            evaluating = true;
            try {
                return GameRandom.isolated(answer);
            } catch (RuntimeException e) {
                return null;
            } finally {
                evaluating = outer;
            }
        };
    }

    private static <T> List<T> listOrNull(Iterable<? extends T> items) {
        if (items == null) {
            return null;
        }
        List<T> list = new ArrayList<>();
        for (T item : items) {
            list.add(item);
        }
        return list;
    }

    private static void restoreAttackers(Combat combat, Map<Card, GameEntity> before) {
        for (Card attacker : combat.getAttackers()) {
            GameEntity defender = before.get(attacker);
            if (defender == null || !defender.equals(combat.getDefenderByAttacker(attacker))) {
                combat.removeFromCombat(attacker);
            }
        }
        for (Map.Entry<Card, GameEntity> entry : before.entrySet()) {
            if (!combat.isAttacking(entry.getKey())) {
                combat.addAttacker(entry.getKey(), entry.getValue());
            }
        }
    }

    private static Map<Card, List<Card>> blocks(Combat combat) {
        Map<Card, List<Card>> blocks = new LinkedHashMap<>();
        for (Card blocker : combat.getAllBlockers()) {
            blocks.put(blocker, new ArrayList<>(combat.getAttackersBlockedBy(blocker)));
        }
        return blocks;
    }

    private static void restoreBlockers(Combat combat, Map<Card, List<Card>> before) {
        for (Card blocker : combat.getAllBlockers()) {
            if (!before.containsKey(blocker)) {
                combat.removeFromCombat(blocker);
            }
        }
        for (Map.Entry<Card, List<Card>> entry : before.entrySet()) {
            for (Card attacker : entry.getValue()) {
                if (!combat.getAttackersBlockedBy(entry.getKey()).contains(attacker)) {
                    combat.addBlocker(attacker, entry.getKey());
                }
            }
        }
    }

    private boolean playingForAi(java.util.function.BooleanSupplier play) {
        boolean outer = aiPlaying;
        aiPlaying = true;
        try {
            return play.getAsBoolean();
        } finally {
            aiPlaying = outer;
        }
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
        if (evaluating) {
            return super.mulliganKeepHand(firstPlayer, cardsToReturn);
        }
        Boolean keep = handler.mulliganKeepHand(player, cardsToReturn,
                preview(() -> super.mulliganKeepHand(firstPlayer, cardsToReturn)));
        if (keep != null) {
            return keep;
        }
        ai("mulliganKeepHand");
        return super.mulliganKeepHand(firstPlayer, cardsToReturn);
    }

    @Override
    public CardCollectionView tuckCardsViaMulligan(CardCollectionView hand, int cardsToReturn) {
        if (evaluating) {
            return super.tuckCardsViaMulligan(hand, cardsToReturn);
        }
        List<Card> chosen = handler.tuckCardsViaMulligan(player, hand, cardsToReturn,
                preview(() -> listOrNull(super.tuckCardsViaMulligan(new CardCollection(hand), cardsToReturn))));
        if (chosen != null) {
            return new CardCollection(chosen);
        }
        ai("tuckCardsViaMulligan");
        return super.tuckCardsViaMulligan(hand, cardsToReturn);
    }

    // --- priority and casting -------------------------------------------------

    @Override
    public List<SpellAbility> chooseSpellAbilityToPlay() {
        if (evaluating) {
            return super.chooseSpellAbilityToPlay();
        }
        List<SpellAbility> chosen = handler.chooseSpellAbilityToPlay(player, preview(() -> {
            AbilityState state = new AbilityState();
            for (Card card : ComputerUtilAbility.getAvailableCards(getGame(), player)) {
                state.save(card.getAllSpellAbilities());
            }
            try {
                List<SpellAbility> play = super.chooseSpellAbilityToPlay();
                return play == null ? new ArrayList<>() : new ArrayList<>(play);
            } finally {
                state.restore();
            }
        }));
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
        if (evaluating || !chosenExternally.remove(sa) || sa.isLandAbility()) {
            return playingForAi(() -> super.playChosenSpellAbility(sa));
        }
        Zone origin = sa.getHostCard().getZone();
        // How far the play went, to say why it failed: modes, then targets, then costs.
        boolean[] targeting = {false};
        boolean[] targeted = {false};
        // The AI pays the costs; targets go through chooseTargetsFor (below).
        boolean played = ComputerUtil.handlePlayingSpellAbility(player, sa, s -> {
            targeting[0] = true;
            targeted[0] = s.setupTargets() && s.isTargetNumberValid();
        });
        Card host = sa.getHostCard();
        if (!played && origin != null && host.isInZone(ZoneType.Stack)) {
            // Forge already moved the card to the stack zone before targeting failed.
            getGame().getAction().moveTo(origin.getZoneType(), host, null, null);
        }
        if (!played) {
            handler.onPlayFailed(player, sa, !targeting[0] ? "modes" : !targeted[0] ? "targets" : "costs");
        }
        return played;
    }

    @Override
    public boolean chooseTargetsFor(SpellAbility sa) {
        if (evaluating) {
            return super.chooseTargetsFor(sa);
        }
        Boolean ok = handler.chooseTargetsFor(player, sa, preview(() -> {
            AbilityState state = new AbilityState();
            state.save(sa);
            try {
                return super.chooseTargetsFor(sa) ? new ArrayList<Object>(sa.getTargets()) : null;
            } finally {
                state.restore();
            }
        }));
        if (ok != null) {
            return ok;
        }
        ai("chooseTargetsFor");
        return super.chooseTargetsFor(sa);
    }

    @Override
    public boolean playTrigger(Card host, WrappedAbility wrapper, boolean isMandatory) {
        SpellAbility sa = wrapper.getWrappedAbility();
        if (evaluating || !usesTargeting(sa)) {
            return playingForAi(() -> super.playTrigger(host, wrapper, isMandatory));
        }
        if (sa.getApi() == ApiType.Charm || sa.hasParam("TargetingPlayer") || !sa.setupTargets()) {
            ai("playTrigger");
            return playingForAi(() -> super.playTrigger(host, wrapper, isMandatory));
        }
        return ComputerUtil.playNoStack(wrapper.getActivatingPlayer(), wrapper, getGame(), true);
    }

    // --- combat ---------------------------------------------------------------

    @Override
    public void declareAttackers(Player attacker, Combat combat) {
        if (evaluating) {
            super.declareAttackers(attacker, combat);
            return;
        }
        Supplier<Map<Card, GameEntity>> ai = preview(() -> {
            Map<Card, GameEntity> before = new HashMap<>(combat.getAttackersAndDefenders());
            try {
                super.declareAttackers(attacker, combat);
                return new LinkedHashMap<>(combat.getAttackersAndDefenders());
            } finally {
                restoreAttackers(combat, before);
            }
        });
        if (handler.declareAttackers(attacker, combat, ai) == null) {
            ai("declareAttackers");
            super.declareAttackers(attacker, combat);
        }
    }

    @Override
    public void declareBlockers(Player defender, Combat combat) {
        if (evaluating) {
            super.declareBlockers(defender, combat);
            return;
        }
        Supplier<Map<Card, List<Card>>> ai = preview(() -> {
            Map<Card, List<Card>> before = blocks(combat);
            try {
                super.declareBlockers(defender, combat);
                return blocks(combat);
            } finally {
                restoreBlockers(combat, before);
            }
        });
        if (handler.declareBlockers(defender, combat, ai) == null) {
            ai("declareBlockers");
            super.declareBlockers(defender, combat);
        }
    }

    // --- choosing cards and entities ------------------------------------------

    @Override
    public CardCollectionView chooseCardsForEffect(CardCollectionView sourceList, SpellAbility sa, String title, int min, int max, boolean isOptional, Map<String, Object> params) {
        if (evaluating) {
            return super.chooseCardsForEffect(sourceList, sa, title, min, max, isOptional, params);
        }
        List<GameEntity> chosen = handler.chooseEntities(player, sa, title, entities(sourceList), isOptional ? 0 : min, max,
                preview(() -> listOrNull(super.chooseCardsForEffect(new CardCollection(sourceList), sa, title, min, max, isOptional, params))));
        if (chosen == null) {
            ai("chooseCardsForEffect");
            return super.chooseCardsForEffect(sourceList, sa, title, min, max, isOptional, params);
        }
        return cards(chosen);
    }

    @Override
    @SuppressWarnings("unchecked")
    public <T extends GameEntity> T chooseSingleEntityForEffect(FCollectionView<T> optionList, DelayedReveal delayedReveal, SpellAbility sa, String title, boolean isOptional, Player targetedPlayer, Map<String, Object> params) {
        if (evaluating) {
            return super.chooseSingleEntityForEffect(optionList, delayedReveal, sa, title, isOptional, targetedPlayer, params);
        }
        List<GameEntity> chosen = handler.chooseEntities(player, sa, title, entities(optionList), isOptional ? 0 : 1, 1, preview(() -> {
            T one = super.chooseSingleEntityForEffect(optionList, delayedReveal, sa, title, isOptional, targetedPlayer, params);
            List<GameEntity> answer = new ArrayList<>();
            if (one != null) {
                answer.add(one);
            }
            return answer;
        }));
        if (chosen == null) {
            ai("chooseSingleEntityForEffect");
            return super.chooseSingleEntityForEffect(optionList, delayedReveal, sa, title, isOptional, targetedPlayer, params);
        }
        return chosen.isEmpty() ? null : (T) chosen.get(0);
    }

    @Override
    @SuppressWarnings("unchecked")
    public <T extends GameEntity> List<T> chooseEntitiesForEffect(FCollectionView<T> optionList, int min, int max, DelayedReveal delayedReveal, SpellAbility sa, String title, Player targetedPlayer, Map<String, Object> params) {
        if (evaluating) {
            return super.chooseEntitiesForEffect(optionList, min, max, delayedReveal, sa, title, targetedPlayer, params);
        }
        List<GameEntity> chosen = handler.chooseEntities(player, sa, title, entities(optionList), min, max,
                preview(() -> listOrNull(super.chooseEntitiesForEffect(optionList, min, max, delayedReveal, sa, title, targetedPlayer, params))));
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
        if (p == player && !evaluating) {
            List<GameEntity> chosen = handler.chooseEntities(player, sa, "Discard", entities(validCards), min, max,
                    preview(() -> listOrNull(super.chooseCardsToDiscardFrom(p, sa, new CardCollection(validCards), min, max, visibleToChooser))));
            if (chosen != null) {
                return cards(chosen);
            }
        }
        ai("chooseCardsToDiscardFrom");
        return super.chooseCardsToDiscardFrom(p, sa, validCards, min, max, visibleToChooser);
    }

    @Override
    public CardCollectionView chooseCardsToDiscardToMaximumHandSize(int numDiscard) {
        if (evaluating) {
            return super.chooseCardsToDiscardToMaximumHandSize(numDiscard);
        }
        List<GameEntity> chosen = handler.chooseEntities(player, null, "Discard down to your maximum hand size",
                entities(player.getCardsIn(ZoneType.Hand)), numDiscard, numDiscard,
                preview(() -> listOrNull(super.chooseCardsToDiscardToMaximumHandSize(numDiscard))));
        if (chosen == null) {
            ai("chooseCardsToDiscardToMaximumHandSize");
            return super.chooseCardsToDiscardToMaximumHandSize(numDiscard);
        }
        return cards(chosen);
    }

    @Override
    public CardCollectionView choosePermanentsToSacrifice(SpellAbility sa, int min, int max, CardCollectionView validTargets, String message) {
        if (evaluating) {
            return super.choosePermanentsToSacrifice(sa, min, max, validTargets, message);
        }
        List<GameEntity> chosen = handler.chooseEntities(player, sa, message == null ? "Sacrifice" : message, entities(validTargets), min, max,
                preview(() -> listOrNull(super.choosePermanentsToSacrifice(sa, min, max, new CardCollection(validTargets), message))));
        if (chosen == null) {
            ai("choosePermanentsToSacrifice");
            return super.choosePermanentsToSacrifice(sa, min, max, validTargets, message);
        }
        return cards(chosen);
    }

    // --- yes/no and modes -----------------------------------------------------

    @Override
    public boolean confirmAction(SpellAbility sa, PlayerActionConfirmMode mode, String message, List<String> options, Card cardToShow, Map<String, Object> params) {
        if (evaluating) {
            return super.confirmAction(sa, mode, message, options, cardToShow, params);
        }
        Boolean yes = aiPlaying ? null : handler.confirm(player, message,
                preview(() -> super.confirmAction(sa, mode, message, options, cardToShow, params)));
        if (yes != null) {
            return yes;
        }
        ai("confirmAction");
        return super.confirmAction(sa, mode, message, options, cardToShow, params);
    }

    @Override
    public boolean confirmTrigger(WrappedAbility sa) {
        if (evaluating) {
            return super.confirmTrigger(sa);
        }
        Boolean yes = handler.confirm(player, "Use the optional trigger of " + sa.getHostCard().getName() + ": " + sa.getStackDescription(),
                preview(() -> super.confirmTrigger(sa)));
        if (yes != null) {
            return yes;
        }
        ai("confirmTrigger");
        return super.confirmTrigger(sa);
    }

    @Override
    public List<AbilitySub> chooseModeForAbility(SpellAbility sa, List<AbilitySub> possible, int min, int num, boolean allowRepeat) {
        if (evaluating) {
            return super.chooseModeForAbility(sa, possible, min, num, allowRepeat);
        }
        List<AbilitySub> chosen = aiPlaying ? null : handler.chooseModes(player, sa, possible, min, num, allowRepeat, preview(() -> {
            AbilityState state = new AbilityState();
            state.save(sa);
            state.save(possible);
            try {
                return listOrNull(super.chooseModeForAbility(sa, possible, min, num, allowRepeat));
            } finally {
                state.restore();
            }
        }));
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
