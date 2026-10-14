# --- Forge and the Java shim ----------------------------------------------------
FROM maven:3.9-eclipse-temurin-17 AS forge
ARG FORGE_REF=forge-2.0.15
RUN git clone --depth 1 --branch ${FORGE_REF} https://github.com/Card-Forge/forge.git /src/forge
WORKDIR /src/forge
RUN mvn -B -q -pl forge-gui-desktop -am -DskipTests package \
 && cp forge-gui-desktop/target/forge-gui-desktop-*-jar-with-dependencies.jar /src/forge.jar
COPY java /src/bridge-src
RUN mkdir /src/bridge \
 && javac -nowarn -cp /src/forge.jar -d /src/bridge $(find /src/bridge-src -name '*.java')

# --- The service -----------------------------------------------------------------
FROM eclipse-temurin:17-jre
COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /uvx /bin/
ENV FORGE_HOME=/opt/forge \
    UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PATH=/opt/venv/bin:$PATH
COPY --from=forge /src/forge.jar /opt/forge/forge.jar
COPY --from=forge /src/bridge /opt/forge/bridge
COPY --from=forge /src/forge/forge-gui/res /opt/forge/forge-gui/res
# Forge looks for res/ in the working directory, or in ../forge-gui/ for git builds.
RUN mkdir -p /opt/forge/app && ln -s ../forge-gui/res /opt/forge/app/res
WORKDIR /srv
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-install-project
COPY mtg_forge_engine ./mtg_forge_engine
COPY tests ./tests
RUN uv sync --frozen
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=5s --start-period=180s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8080/health').status == 200 else 1)"
CMD ["sh", "-c", "exec uvicorn mtg_forge_engine.api:app --host 0.0.0.0 --port ${PORT:-8080} --timeout-graceful-shutdown 5"]
