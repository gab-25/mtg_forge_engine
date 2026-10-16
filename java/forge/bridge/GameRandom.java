package forge.bridge;

import forge.util.MyRandom;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.ObjectInputStream;
import java.io.ObjectOutputStream;
import java.io.UncheckedIOException;
import java.util.Random;
import java.util.function.Supplier;

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

    /**
     * Runs body on a copy of this thread's generator, so that what it draws
     * (threads it starts included) leaves the game's own sequence untouched.
     */
    public static <T> T isolated(Supplier<T> body) {
        Random outer = CURRENT.get();
        CURRENT.set(copy(outer != null ? outer : FALLBACK));
        try {
            return body.get();
        } finally {
            if (outer != null) {
                CURRENT.set(outer);
            } else {
                CURRENT.remove();
            }
        }
    }

    private static Random copy(Random random) {
        try {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            try (ObjectOutputStream out = new ObjectOutputStream(bytes)) {
                out.writeObject(random);
            }
            try (ObjectInputStream in = new ObjectInputStream(new ByteArrayInputStream(bytes.toByteArray()))) {
                return (Random) in.readObject();
            }
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        } catch (ClassNotFoundException e) {
            throw new IllegalStateException(e);
        }
    }

    @Override
    protected int next(int bits) {
        Random random = CURRENT.get();
        return (random != null ? random : FALLBACK).nextInt() >>> (32 - bits);
    }
}
