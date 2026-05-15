"""R4 smoke-test trader: aggregates counterparty trade flow and prints a summary
on the final tick. Does not place any orders. Use to (a) verify the backtester
populates Trade.buyer/seller from the R4 trades CSV, and (b) get a first look
at which counterparties are active on which products."""

from collections import defaultdict

from prosperity3bt.datamodel import TradingState


class Trader:
    def __init__(self) -> None:
        # {product: {counterparty_name: [bought_qty, sold_qty]}}
        self.flow: dict[str, dict[str, list[int]]] = defaultdict(
            lambda: defaultdict(lambda: [0, 0])
        )
        self.last_ts = 0

    def run(self, state: TradingState):
        for product, trades in state.market_trades.items():
            for t in trades:
                if t.buyer:
                    self.flow[product][t.buyer][0] += t.quantity
                if t.seller:
                    self.flow[product][t.seller][1] += t.quantity

        self.last_ts = state.timestamp
        if state.timestamp == 999900:
            self._dump()
        return {}, 0, ""

    def _dump(self) -> None:
        print(f"\n=== R4 counterparty flow (final tick t={self.last_ts}) ===")
        for product in sorted(self.flow):
            print(f"\n[{product}]")
            rows = sorted(
                self.flow[product].items(),
                key=lambda kv: -(kv[1][0] + kv[1][1]),
            )
            for name, (bought, sold) in rows[:20]:
                net = bought - sold
                print(f"  {name:>10s}  bought={bought:>6d}  sold={sold:>6d}  net={net:+d}")
