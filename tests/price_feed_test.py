import unittest
from dexbot.strategies.external_feeds.price_feed import PriceFeed
from dexbot.strategies.crossmarket.strategy import Strategy

class PriceFeedTest(unittest.TestCase):
    def test_upper(self):
        symbol = 'BTC/USDT'  # STEEM/USD * USD/BTS = STEEM/BTS
        price_feed = PriceFeed("binance", symbol)
        price_feed.filter_symbols()
        center_price = price_feed.get_center_price(None)
        print('PriceFeed: {}'.format(center_price))

    def test_strategy(self):
        strat = Strategy("binance", "BTC/USDT", "BTC/USDT", {"api_key": "", "api_secret": "", "percent_depth": 10, "min_spread": 0.50})
        depth,raw_depth, num_dec = strat.calculate_depth()
        print("depth=", depth)
        center_price = (depth['bids'][0][0] + depth['asks'][0][0]) / 2
        spread,new_spread, lowest_price, highest_price = strat.calculate_spread(depth, center_price,num_dec)
        print("spread=", center_price, spread, new_spread, lowest_price, highest_price)
        new_depth = strat.filter_depth(depth, lowest_price, highest_price)
        print("filter_depth=", new_depth)

        balanceI = {"BTC": 2.0, "USDT": 8000.0}
        balanceE = {"BTC": 2.0, "USDT": 8000.0}

        buy_orders, sell_orders = strat.calculate_orders(raw_depth, new_depth, balanceI, balanceE)
        print("Buy orders=", buy_orders)
        print("Sell orders=", sell_orders)

if __name__ == '__main__':
    unittest.main()