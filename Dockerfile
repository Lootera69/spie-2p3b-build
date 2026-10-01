# BrainBloom workshop, built for a 512 MB / 0.1 CPU free container.
#
# Everything the running image needs is baked in at build time: the solver wheels
# and the hash-pinned WordNet corpus. Generation itself never reaches the network.

FROM python:3.12-slim AS build

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /src

# z3-solver and clingo publish manylinux wheels for x86_64 and aarch64, so no
# toolchain is installed here and the build stays a download plus an unzip.
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir .

# The project's own installer owns the URL and the SHA-256 pin; calling it keeps
# this image on exactly the corpus the test suite verifies.
RUN /opt/venv/bin/python -m spie.questions.brainbloom dictionary-install \
        --out /opt/corpus/wordnet.zip


FROM python:3.12-slim AS runtime

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BRAINBLOOM_HOST=0.0.0.0 \
    PORT=10000

COPY --from=build /opt/venv /opt/venv
COPY --from=build /opt/corpus/wordnet.zip /app/.brainbloom/wordnet.zip

# Unprivileged, and the working directory is what makes .brainbloom/wordnet.zip
# the auto-detected corpus.
RUN useradd --create-home --uid 10001 workshop && chown -R workshop /app
USER workshop
WORKDIR /app

EXPOSE 10000

# The platform publishes the externally reachable URL; it is the only origin the
# same-origin check may widen to, and naming it is what enables the request cap.
# --no-oewn is not optional here: WordNet alone peaks at ~249 MB, but adding the
# optional OEWN corpus peaks at ~771 MB and would be killed on a 512 MB instance.
# exec hands SIGTERM to Python so a redeploy stops the server rather than the shell.
CMD ["sh", "-c", \
     "export BRAINBLOOM_PUBLIC_ORIGIN=\"${BRAINBLOOM_PUBLIC_ORIGIN:-$RENDER_EXTERNAL_URL}\"; \
      exec python -m spie.questions.brainbloom serve \
        --no-integrations --no-history --no-oewn"]
