package forge.bridge;

import forge.util.MyRandom;

import java.util.Random;

/**
 * Forge draws every random number from one global MyRandom. This Random routes
 * each thread to its own seeded generator, so concurrent games do not share a
 * sequence and a game is reproducible from its seed.
 */
public final class GameRandom extends Random {
    private static final InheritableThreadLocal<Random> CURRENT = new InheritableThreadLocal<>();
    private static final Random FALLBACK = new Random();

    public static void install() {
        MyRandom.setRandom(new GameRandom());
    }

    public static void bindThisThread(long seed) {
        CURRENT.set(new Random(seed));
    }

    @Override
    protected int next(int bits) {
        Random random = CURRENT.get();
        return (random != null ? random : FALLBACK).nextInt() >>> (32 - bits);
    }
}
