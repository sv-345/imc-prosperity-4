"""Check order flow in server trade history for single-tick bursts.

For each ts: sum all trades (ours + bot-bot). Find ticks with:
- Multiple trades (bursts)
- Large total volume
- Big price spread across the ts
"""
from __future__ import annotations
import json, io, csv, pathlib
from collections import defaultdict

LOGS = {
    'iter23-303257 (9231)': '/tmp/prosperity_logs/303257/312201.log',
    'iter23-303280 (9514)': '/tmp/prosperity_logs/303280/312224.log',
    'tb1-313880 (9568)': '/tmp/prosperity_logs/313880/322847.log',
    'iter26-316247 (9890)': '/tmp/prosperity_logs/316247/325221.log',
    'iter26-316195 (9411)': '/tmp/prosperity_logs/316195/325169.log',
}


def main():
    for label, path in LOGS.items():
        try: d = json.load(open(path))
        except: continue
        trades = d.get('tradeHistory', [])
        print(f"\n=== {label} ===")
        print(f"Total tradeHistory entries: {len(trades)}")
        # Group by ts
        by_ts = defaultdict(list)
        for t in trades:
            by_ts[t['timestamp']].append(t)
        # Stats
        ts_with_multi = [(ts, ts_trades) for ts, ts_trades in by_ts.items() if len(ts_trades) >= 2]
        print(f"Ticks with 2+ trades: {len(ts_with_multi)}")
        # Top ticks by total qty AND by our qty
        print(f"\nTop 15 ticks by TOTAL qty (ours + bot-bot):")
        top_total = sorted(by_ts.items(), key=lambda x: -sum(t['quantity'] for t in x[1]))[:15]
        for ts, ts_trades in top_total:
            total_q = sum(t['quantity'] for t in ts_trades)
            our_q = sum(t['quantity'] for t in ts_trades if t['buyer'] == 'SUBMISSION' or t['seller'] == 'SUBMISSION')
            # Break down by product
            prods = set(t['symbol'] for t in ts_trades)
            # Show price range
            prices = [t['price'] for t in ts_trades]
            print(f"  ts={ts}  n={len(ts_trades)} total_qty={total_q} our_qty={our_q} px_range=[{min(prices)}..{max(prices)}] prods={','.join(p[:3] for p in prods)}")
            for t in ts_trades:
                side = 'BUY' if t['buyer'] == 'SUBMISSION' else ('SELL' if t['seller'] == 'SUBMISSION' else 'BOT')
                print(f"    {side}  {t['symbol'][:3]} qty={t['quantity']} px={t['price']}")

        # Biggest bot-bot events (not involving us)
        print(f"\nTop 10 bot-bot ticks by qty (we weren't involved):")
        bot_bot = []
        for ts, ts_trades in by_ts.items():
            total_q = sum(t['quantity'] for t in ts_trades if t['buyer'] != 'SUBMISSION' and t['seller'] != 'SUBMISSION')
            if total_q > 0:
                bot_bot.append((ts, ts_trades, total_q))
        bot_bot.sort(key=lambda x: -x[2])
        for ts, ts_trades, total_q in bot_bot[:10]:
            bot_trades = [t for t in ts_trades if t['buyer'] != 'SUBMISSION' and t['seller'] != 'SUBMISSION']
            print(f"  ts={ts}  bot_qty={total_q}")
            for t in bot_trades:
                print(f"    BOT {t['symbol'][:3]} qty={t['quantity']} px={t['price']}")


if __name__ == "__main__":
    main()
