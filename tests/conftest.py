import os

import pytest

FORGE_HOME = os.environ.get("FORGE_HOME", "/opt/forge")


@pytest.fixture(scope="session")
def forge():
    """Forge started once per test session; skips outside the Docker image."""
    if not os.path.isfile(os.path.join(FORGE_HOME, "forge.jar")):
        pytest.skip("Forge runs only in the Docker image")
    from mtg_forge_engine import jvm

    jvm.start(FORGE_HOME)
    return FORGE_HOME
