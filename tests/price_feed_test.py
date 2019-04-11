import unittest
from dexbot.strategies.external_feeds.price_feed import PriceFeed
from dexbot.strategies.crossmarket.strategy import CrossMarketStrategy
from dexbot.strategies.crossmarket.external_market import ExternalMarket
from dexbot.strategies.crossmarket.internal_market import InternalMarket
from bitshares import BitShares
from bitshares.instance import set_shared_bitshares_instance

class PriceFeedTest(unittest.TestCase):
    def test_upper(self):
        symbol = 'BTC/USDT'  # STEEM/USD * USD/BTS = STEEM/BTS
        price_feed = PriceFeed("binance", symbol)
        price_feed.filter_symbols()
        center_price = price_feed.get_center_price(None)
        print('PriceFeed: {}'.format(center_price))

    def test_strategy(self):
        strat = CrossMarketStrategy("BTC/USDT", "BTC/USDT", {"percent_depth": 0.1})
        market = ExternalMarket("binance", {"api_key": "", "api_secret": "", })
        depth = market.getDepth("BTC/USDT")

        # step 1+2, scale down depth for our strategy
        depth,raw_depth, num_dec = strat.calculate_depth(depth)
        print("depth=", depth)
        center_price = (depth['bids'][0][0] + depth['asks'][0][0]) / 2
        # step best selling, and buying price
        spread,new_spread, lowest_price, highest_price = strat.calculate_spread(1, depth, center_price,num_dec)
        print("center={} spread={} new_spread={} lowest={} highest={}".format(center_price, spread, new_spread, lowest_price, highest_price))

        # step 3: with spread, let's filter the depth to only our interested spread
        new_depth = strat.filter_depth(depth, lowest_price, highest_price)
        print("filter_depth=", new_depth)

        balanceI = {"BTC": 0.56036679, "USDT": 0.0}
        balanceE = {"BTC": 0.56036679, "USDT": 0.0}

        buy_orders, sell_orders = strat.calculate_orders(raw_depth, new_depth, balanceI, balanceE)
        print("Buy orders=", buy_orders)
        print("Sell orders=", sell_orders)


    def test_internal_market(self):
        bitshares_instance = BitShares("ws://testnet-01.quantachain.io:8090", num_retries=-1)
        set_shared_bitshares_instance(bitshares_instance)

        m = InternalMarket()
        filled = m.get_account_orders_by_operation_type("1.2.15", "4")
        print(len(filled))
        found = m.find_orderid(filled, "1.7.462654", "1.3.2")
        print("found",len(found), found)
        orders = m.transform_to_order(filled, "1.3.2")
        print(orders[0],orders[0].order_id, orders[0]['quote']['asset']['id'])
        print(orders[0]['quote']['amount'])

        order_id = "1.7.463906"
        filtered1 = list(filter(lambda x: x['operation_history']['op_object']['order_id'] == order_id, filled))
        ids = list(x['operation_history']['virtual_op'] for x in filtered1)

        print("original data", len(filtered1), ids)

        filled = m.transform_to_order(filled, "1.3.2")
        filtered = list(filter(lambda x: x.order_id == order_id, filled))
        ids = list(x.virtual_op for x in filtered)

        print(len(filled), len(filtered), ids)

if __name__ == '__main__':
    unittest.main()