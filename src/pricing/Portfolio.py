from pricing.Market import Market
from pricing.Position import Position


class Portfolio():
    def __init__(self, cash: float, market: Market) -> None:
        self.cash: float = cash
        self.market: Market = market
        self.positions: dict[str, Position] = {}

        # init tradelog
        self.tradelog: dict[str, list[dict]] = {}
        for ric in market.universe:
            self.tradelog[ric] = []


    def nav(self: "Portfolio") -> float:
        '''Net Asset Value'''
        positions_mtm = sum([position.mark_to_market(self.market) for position in self.positions.values()])
        return self.cash + positions_mtm

    def enter(self: "Portfolio", new_position: Position) -> None:

        # get market data
        timestamp = self.market.quotes[new_position.product.id]['timestamp']
        new_position.price = new_position.product.present_value(self.market)

        # check if enough funds
        if self.cash < new_position.price * new_position.quantity:
            raise Exception("Insufficient funds")
        
        # enter position
        else:
            self.cash -= new_position.price * new_position.quantity

            # check if position already exists, if yes rebalance
            if new_position.product.id in self.positions.keys():
                current_position = self.positions[new_position.product.id]
                current_position.rebalance(new_position.price, new_position.quantity)
            
            # add new position
            else: self.positions[new_position.product.id] = new_position

            # update tradelog
            self.tradelog[new_position.product.id].append({
                "timestamp": timestamp,
                "quantity": new_position.quantity,
                "price": new_position.price
                })

    def exit(self: "Portfolio", id: str) -> None:

        if id not in self.positions.keys():
            raise Exception("Position not found")
        else:
            exit_position = self.positions[id]
            self.cash +=  exit_position.mark_to_market(self.market)
            self.tradelog[id] = {
                "timestamp": self.market.quotes[id]['timestamp'],
                "quantity": exit_position.quantity,
                "price": exit_position.price
                }
            self.positions.pop(id)
