#!/usr/bin/env bash
# Smoke test for the P4R3-patched prosperity3bt fork.
# Asserts:
#   1. Noop trader produces $0 PnL across all 3 R3 days, and all 12 P4R3 products show up.
#   2. Oversized-orders trader gets cancelled (sandbox log contains "exceeded limit").
#   3. v83 produces a known-good total in the $560k-$570k band on the 3-day backtest.

set -euo pipefail

FORK_DIR="$(cd "$(dirname "$0")/.." && pwd)"
R3_DIR="<legacy-r3>"
TRADER_V83="$R3_DIR/trader_r3_v83.py"

cd "$FORK_DIR"

echo "=== Test 1: noop trader, R3 all days ==="
NOOP_OUT=$(uv run prosperity3bt example/starter.py 3 --no-out --no-progress 2>&1)
echo "$NOOP_OUT" | grep -E "^Total profit: 0$" >/dev/null || { echo "FAIL: noop trader did not produce zero PnL"; echo "$NOOP_OUT" | tail -10; exit 1; }
for product in HYDROGEL_PACK VELVETFRUIT_EXTRACT VEV_4000 VEV_4500 VEV_5000 VEV_5100 VEV_5200 VEV_5300 VEV_5400 VEV_5500 VEV_6000 VEV_6500; do
  echo "$NOOP_OUT" | grep -F "$product:" >/dev/null || { echo "FAIL: product $product not found in noop run"; exit 1; }
done
echo "  PASS: noop = 0, all 12 products present"

echo "=== Test 2: oversized-orders trader, R3 day 0 ==="
TMPLOG=$(mktemp /tmp/smoke_oversized.XXXXXX.log)
uv run prosperity3bt example/oversized_trader.py 3-0 --out "$TMPLOG" --no-progress >/dev/null 2>&1
grep -F "exceeded limit of 200" "$TMPLOG" >/dev/null || { echo "FAIL: VELVETFRUIT 250 order should hit limit 200"; exit 1; }
grep -F "exceeded limit of 300" "$TMPLOG" >/dev/null || { echo "FAIL: VEV_5400 400 order should hit limit 300"; exit 1; }
rm -f "$TMPLOG"
echo "  PASS: oversized orders cancelled with correct limit messages"

echo "=== Test 3: v83 trader, R3 all days ==="
if [[ ! -f "$TRADER_V83" ]]; then
  echo "  SKIP: $TRADER_V83 not found"
  exit 0
fi
V83_OUT=$(uv run prosperity3bt "$TRADER_V83" 3 --merge-pnl --no-out --no-progress 2>&1)
TOTAL=$(echo "$V83_OUT" | tail -1 | grep -oE '[0-9,]+' | tr -d ',')
if [[ -z "$TOTAL" ]]; then
  echo "FAIL: could not parse v83 total profit"; echo "$V83_OUT" | tail -5; exit 1
fi
if [[ "$TOTAL" -lt 560000 || "$TOTAL" -gt 570000 ]]; then
  echo "FAIL: v83 total $TOTAL outside expected $560k-$570k band (regression?)"
  echo "$V83_OUT" | tail -10
  exit 1
fi
echo "  PASS: v83 total = $TOTAL (within \$560k-\$570k band)"

echo
echo "All smoke tests passed."
