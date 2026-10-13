package forge.bridge;

import forge.ai.LobbyPlayerAi;
import forge.game.Game;
import forge.game.player.Player;

/** A lobby player whose in-game controller is a BridgeController. */
public class BridgeLobbyPlayer extends LobbyPlayerAi {
    private final DecisionHandler handler;

    public BridgeLobbyPlayer(String name, DecisionHandler handler) {
        super(name, null);
        this.handler = handler;
        setAiProfile("Default");
    }

    @Override
    public Player createIngamePlayer(Game game, int id) {
        Player player = new Player(getName(), game, id);
        player.setFirstController(new BridgeController(game, player, this, handler));
        return player;
    }
}
