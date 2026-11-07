#!/usr/bin/env bash
# Start the Appium server from this directory's lock, run the comparison, stop it.
# Called by .github/workflows/android-bench.yml inside android-emulator-runner,
# with the emulator up and `npm ci --omit=optional --ignore-scripts` done here.
# Usage: bench/android/run.sh OUT_JSON [SUMMARY_MD]
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
OUT="$1"
SUMMARY="${2:-}"
LOG="${OUT%.json}-appium.log"

# Appium finds its drivers in APPIUM_HOME's package.json: the locked driver, nothing else.
export APPIUM_HOME="$HERE"
"$HERE/node_modules/.bin/appium" --address 127.0.0.1 --port 4723 --log-level info --log "$LOG" &
APPIUM_PID=$!
trap 'kill "$APPIUM_PID" 2>/dev/null || true' EXIT

for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:4723/status >/dev/null 2>&1; then break; fi
  if ! kill -0 "$APPIUM_PID" 2>/dev/null; then echo "Appium exited; see $LOG" >&2; exit 1; fi
  sleep 1
done
curl -fsS http://127.0.0.1:4723/status

cd "$REPO"
python scripts/bench_android.py --appium http://127.0.0.1:4723 --out "$OUT" ${SUMMARY:+--markdown "$SUMMARY"}
