package forge.bridge;

import com.google.common.eventbus.Subscribe;
import forge.game.Game;
import forge.game.GameEndReason;
import forge.game.event.GameEvent;

/**
 * Ends the game in a draw on request. Forge's Game is not thread-safe and no seat ever
 * calls back into Python, so a request thread only flips the switch: the game ends on
 * the game thread, at its next game event.
 */
public class Abort {
    private final Game game;
    private volatile boolean requested = false;

    public Abort(Game game) {
        this.game = game;
        game.subscribeToEvents(this);
    }

    public void request() {
        requested = true;
    }

    @Subscribe
    public void onEvent(GameEvent event) {
        if (requested && !game.isGameOver()) {
            game.setGameOver(GameEndReason.Draw);
        }
    }
}
