# syntax=docker/dockerfile:1
# FalkorDB binaries, bundled so a single container (e.g. Render free tier) can run without a separate database.
FROM falkordb/falkordb@sha256:b0bdcac2cbaff989e77cb0610439b7a9289e86de033ccbbd4368b66fb680ae7a AS falkordb

# Same Debian release as the FalkorDB image, so its binaries find matching system libraries.
FROM python:3.12-slim-trixie
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 libsystemd0 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=falkordb /usr/local/bin/redis-server /usr/local/bin/redis-cli /usr/local/bin/
COPY --from=falkordb /var/lib/falkordb/bin/falkordb.so /opt/falkordb/falkordb.so
WORKDIR /app
COPY requirements.txt requirements.lock ./
# Install the pinned Linux set from ./wheels if present (see `make wheels`), otherwise from PyPI.
COPY wheels/ /wheels/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-index --find-links /wheels -r requirements.lock \
    || pip install --default-timeout=120 --retries 10 -r requirements.lock
COPY backend ./backend
COPY frontend ./frontend
COPY data ./data
COPY tests ./tests
COPY pytest.ini start.sh ./
RUN sed -i 's/\r$//' start.sh && chmod +x start.sh
EXPOSE 8000
# Hosting platforms (Render, Railway, Fly) pass the port in $PORT; default 8000.
# With FALKOR_HOST unset or localhost, start.sh also runs the bundled FalkorDB.
CMD ["./start.sh"]
