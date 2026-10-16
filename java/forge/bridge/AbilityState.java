package forge.bridge;

import forge.game.spellability.AbilitySub;
import forge.game.spellability.SpellAbility;
import forge.game.spellability.TargetChoices;

import java.util.ArrayList;
import java.util.List;

/**
 * What Forge's AI leaves on spell abilities while it only evaluates them (targets,
 * X, chosen modes), saved so it can be put back afterwards.
 */
final class AbilityState {
    private final List<Runnable> restore = new ArrayList<>();

    void save(Iterable<? extends SpellAbility> abilities) {
        for (SpellAbility sa : abilities) {
            save(sa);
        }
    }

    void save(SpellAbility sa) {
        for (SpellAbility part = sa; part != null; part = part.getSubAbility()) {
            SpellAbility saved = part;
            TargetChoices targets = part.getTargets() == null ? null : part.getTargets().clone();
            Integer x = part.getXManaCostPaid();
            List<AbilitySub> chosen = part.getChosenList() == null ? null : new ArrayList<>(part.getChosenList());
            restore.add(() -> {
                saved.setTargets(targets == null ? null : targets.clone());
                saved.setXManaCostPaid(x);
                saved.setChosenList(chosen);
            });
        }
    }

    void restore() {
        for (Runnable r : restore) {
            r.run();
        }
    }
}
