package forge.bridge;

import com.google.common.eventbus.Subscribe;
import forge.game.Game;
import forge.game.event.GameEvent;
import forge.game.player.Player;

import java.util.ArrayList;
import java.util.IdentityHashMap;
import java.util.List;
import java.util.Map;

/**
 * The turn each player lost in. Forge records no such turn and fires no event when a
 * player loses, so every game event checks whether the lost players have grown.
 */
public class EliminationTracker {
    private final Game game;
    private final List<Player> order = new ArrayList<>();
    private final Map<Player, Integer> turns = new IdentityHashMap<>();

    public EliminationTracker(Game game) {
        this.game = game;
        game.subscribeToEvents(this);
    }

    @Subscribe
    public void onEvent(GameEvent event) {
        record();
    }

    public synchronized void record() {
        for (Player player : game.getLostPlayers()) {
            if (!turns.containsKey(player)) {
                turns.put(player, game.getPhaseHandler().getTurn());
                order.add(player);
            }
        }
    }

    /** Lost players, first eliminated first. */
    public synchronized List<Player> getOrder() {
        return new ArrayList<>(order);
    }

    public synchronized int getTurn(Player player) {
        return turns.get(player);
    }
}
