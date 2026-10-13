package forge.bridge;

import com.google.common.eventbus.Subscribe;
import forge.game.Game;
import forge.game.GameEndReason;
import forge.game.event.GameEventTurnBegan;

/**
 * Ends the game in a draw once it passes its last turn. Runs on the game thread at
 * each turn's start, so it also holds when no external seat is left to call back.
 */
public class TurnLimit {
    private final Game game;
    private final int lastTurn;
    private volatile boolean hit = false;

    public TurnLimit(Game game, int lastTurn) {
        this.game = game;
        this.lastTurn = lastTurn;
        game.subscribeToEvents(this);
    }

    @Subscribe
    public void onTurnBegan(GameEventTurnBegan event) {
        if (event.turnNumber() > lastTurn && !game.isGameOver()) {
            hit = true;
            game.setGameOver(GameEndReason.Draw);
        }
    }

    public boolean isHit() {
        return hit;
    }
}
