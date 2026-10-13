"""Starts the JVM with Forge on the classpath and initialises Forge headless, once.

The same path as Forge's own ``sim`` command-line mode: a headless desktop GUI
interface, then FModel (preferences, card database, formats).
"""

import os
import shlex
import threading
from pathlib import Path

import jpype

_lock = threading.Lock()
_ready = threading.Event()


def start(forge_home: str) -> None:
    with _lock:
        if _ready.is_set():
            return
        home = Path(forge_home)
        jar = home / "forge.jar"
        if not jar.is_file():
            raise FileNotFoundError(f"{jar} not found: Forge is only installed in the Docker image")
        options = shlex.split(os.environ.get("JAVA_OPTS", "-Xmx2g"))
        options += ["-Djava.awt.headless=true", "-Djava.util.Arrays.useLegacyMergeSort=true"]
        # Forge resolves res/ relative to the working directory.
        os.chdir(home / "app")
        jpype.startJVM(*options, classpath=[str(jar), str(home / "bridge")], convertStrings=True)
        jpype.JClass("forge.gui.GuiBase").setInterface(jpype.JClass("forge.GuiDesktop")())
        jpype.JClass("forge.model.FModel").initialize(None, None)
        jpype.JClass("forge.bridge.GameRandom").install()
        _ready.set()


def is_ready() -> bool:
    return _ready.is_set()


def card_count() -> int:
    return int(jpype.JClass("forge.StaticData").instance().getCommonCards().getUniqueCards().size())
