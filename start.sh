#!/bin/sh
# Start the app. If FALKOR_HOST is unset or localhost (e.g. a single Render container),
# run the bundled FalkorDB in the background first. The graph is in-memory only; the app
# reseeds Kettle Labs on startup whenever the graph is empty.
set -e

case "${FALKOR_HOST:-localhost}" in
  localhost|127.0.0.1)
    echo "Starting bundled FalkorDB on 127.0.0.1:${FALKOR_PORT:-6379}"
    redis-server --bind 127.0.0.1 --port "${FALKOR_PORT:-6379}" --save "" --appendonly no \
      --loadmodule /opt/falkordb/falkordb.so THREAD_COUNT 2 MAX_QUEUED_QUERIES 25 TIMEOUT 1000 RESULTSET_SIZE 10000 &
    export FALKOR_HOST=localhost FALKOR_USERNAME="" FALKOR_PASSWORD="" FALKOR_SSL=false
    i=0
    until redis-cli -p "${FALKOR_PORT:-6379}" ping >/dev/null 2>&1; do
      i=$((i + 1))
      [ "$i" -ge 50 ] && { echo "Bundled FalkorDB did not start"; break; }
      sleep 0.2
    done
    ;;
esac

exec uvicorn backend.main:app --host 0.0.0.0 --port "${PORT:-8000}"
