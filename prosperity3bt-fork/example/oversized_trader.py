from prosperity3bt.datamodel import Order, TradingState


class Trader:
    def run(self, state: TradingState):
        orders = {}
        if state.timestamp == 0:
            orders["VEV_5400"] = [Order("VEV_5400", 1, 400)]
            orders["VELVETFRUIT_EXTRACT"] = [Order("VELVETFRUIT_EXTRACT", 1, 250)]
        return orders, 0, ""
