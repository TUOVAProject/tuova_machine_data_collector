#!/usr/bin/env bash
#
# Collector checks in the local test environment. Everything runs in Docker.
#
#   dev/test.sh          unit tests + smoke test
#   dev/test.sh unit     unit tests only (no InfluxDB needed)
#   dev/test.sh smoke    a few polls of the simulated agent into the test InfluxDB, then checks
#   dev/test.sh down     stop the environment and delete its data volume
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE=(docker compose -f "$REPO_DIR/docker-compose.test.yml")
MEASUREMENTS=(mtc_metrics mtc_status)
# Polls every 2 s (POLL_INTERVAL): the first polls store the whole snapshot, the later ones the changes
POLL_SECONDS=8

# Row count per measurement. Parsed by sh inside the InfluxDB container, where
# $INFLUX_BUCKET and the influx CLI's org and token come from dev/test.env.
COUNT_CMD='influx query "from(bucket: \"$INFLUX_BUCKET\")
  |> range(start: 0)
  |> group(columns: [\"_measurement\"])
  |> count()
  |> keep(columns: [\"_measurement\", \"_value\"])"'

step() { printf '\n==> %s\n' "$*"; }

unit() {
    step "Unit tests"
    "${COMPOSE[@]}" run --rm --no-deps mtc_processor \
        python -m unittest discover -s tests -v
}

smoke() {
    step "Starting test InfluxDB and the simulated agent"
    "${COMPOSE[@]}" up -d --wait influxdb fake_agent

    step "Collector polls the agent (${POLL_SECONDS} s)"
    # A fresh container, so its log holds only this run
    "${COMPOSE[@]}" up -d --force-recreate mtc_processor
    sleep "$POLL_SECONDS"
    "${COMPOSE[@]}" stop mtc_processor

    step "Rows in InfluxDB"
    local result
    result="$("${COMPOSE[@]}" exec -T influxdb sh -c "$COUNT_CMD")"
    echo "$result"

    local failed=0
    for m in "${MEASUREMENTS[@]}"; do
        grep -q "$m" <<<"$result" || { echo "MISSING: $m"; failed=1; }
    done
    [[ $failed -eq 0 ]] && echo "OK: all measurements written"

    # e.g. "Deduped by sequence: 86 -> 4": the unchanged values were dropped, the changed ones kept
    local deduped
    deduped="$("${COMPOSE[@]}" logs --no-log-prefix mtc_processor | grep -m1 "Deduped by sequence" || true)"
    if [[ $deduped =~ ([0-9]+)\ -\>\ ([0-9]+) ]] && (( BASH_REMATCH[2] > 0 )); then
        echo "OK: later polls stored only the changed values (${BASH_REMATCH[1]} -> ${BASH_REMATCH[2]})"
    else
        echo "FAIL: no poll stored only the changed values"; failed=1
    fi
    return $failed
}

case "${1:-all}" in
    unit)  unit ;;
    smoke) smoke ;;
    all)   unit && smoke ;;
    down)  "${COMPOSE[@]}" down -v ;;
    *)     sed -n '3,9p' "$0"; exit 2 ;;
esac
