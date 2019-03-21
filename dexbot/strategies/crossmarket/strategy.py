from dexbot.strategies.external_feeds.process_pair import split_pair
import json
from json import JSONEncoder

def truncate(n, decimals=0):
    multiplier = 10 ** decimals
    return int(n * multiplier) / multiplier

def num_after_point(x):
    s = str(x)
    if not '.' in s:
        return 0
    return len(s) - s.index('.') - 1

class CrossMarketUserData:
    '''
    map of [operation_id] = { amount, asset_id }
    map of [counteroffer_id] = { amount, limit_price, filled }
    active: true/false
    '''
    def __init__(self, fill_orders={}, counterorder={}):
        self.fill_orders = fill_orders
        self.counterorder = counterorder

    '''
    fill_orders = [Order]
    returns True if changed
    '''
    def update(self, fill_orders):
        changed = []
        for x in fill_orders:
            if str(x.virtual_op) not in self.fill_orders:
                self.fill_orders[x.virtual_op] = {
                    'amount': x['quote']['amount'],
                    'asset_id': x['quote']['asset']['id']
                }
                changed.append(x)
        return changed

    @staticmethod
    def fromJSON(data):
        try:
            result = json.loads(data)
            return CrossMarketUserData(**result)
        except:
            return CrossMarketUserData()

    def to_json(self):
        return json.dumps(self.__dict__)

class CrossMarketStrategy:
    def __init__(self, internal_symbol, external_symbol, external_options):
        self.external_symbol = external_symbol
        self.internal_symbol = internal_symbol
        self.pair_i = split_pair(self.internal_symbol)
        self.pair_e = split_pair(self.external_symbol)
        self.minimum_amount = 0.01 # BTC

        self.percent_depth  = external_options['percent_depth']

    def aggregate_decimals(self, depth, decimal):
        bids = []
        for b in depth:
            price = truncate(b[0], decimal)
            amount = b[1]
            if len(bids) > 0:
                last = bids[-1]
                if last[0] == price:
                    del bids[-1]
                    bids.append([price, last[1]+amount])
                else:
                    bids.append([price,amount])
            else:
                bids.append([price, amount])

        return bids

    def percent_of_depth(self, depth):
        for b in depth["bids"]:
            b[1] *= self.percent_depth/100
        for b in depth["asks"]:
            b[1] *= self.percent_depth/100
        return depth

    def calculate_depth(self, depth):
        num_dec = num_after_point(depth['bids'][0][0])
        new_depth = depth.copy()
        new_depth['bids'] = self.aggregate_decimals(depth['bids'], num_dec-1)
        new_depth['asks'] = self.aggregate_decimals(depth['asks'], num_dec-1)
        new_depth = self.percent_of_depth(new_depth)
        return new_depth, depth, num_dec-1

    # bids -- first one is the best bid
    # asks -- first one is the best ask
    def calculate_spread(self, min_spread, depth, center_price, num_dec):
        spread = depth["asks"][0][0] / depth["bids"][0][0] - 1
        new_spread = spread + (min_spread/100)
        lowest_price = center_price / (1 + (new_spread/2))
        highest_price = center_price * (1 + (new_spread/2))

        return spread, new_spread, round(lowest_price,num_dec-1), round(highest_price,num_dec-1)

    def filter_depth(self, depth, best_bid, best_ask):
        bids = []
        bid_acc = 0
        asks = []
        ask_acc = 0
        for b in depth["bids"]:
            if len(bids) == 0:
                bid_acc += b[1]
            if b[0] <= best_bid:
                if len(bids) == 0:
                    bids.append([b[0], bid_acc])
                else:
                    bids.append(b)
        for b in depth["asks"]:
            if len(bids) == 0:
                bid_acc += b[1]
            if b[0] >= best_ask:
                if len(bids) == 0:
                    asks.append([b[0], ask_acc])
                else:
                    asks.append(b)

        return {
            "bids": bids, "asks": asks
        }

    '''
    Get average price to fill depth from amount (base)
    '''
    @staticmethod
    def price_from_depth(depth, amount_):
        fill_depth = []
        current_amount = amount_

        for price,amount in depth:
            if current_amount < amount:
                fill_depth.append([price, current_amount])
                current_amount = 0
            else:
                current_amount -= amount
                fill_depth.append([price, amount])

        total_USD = 0
        for price,amount in fill_depth:
            total_USD += price * amount

        #print(fill_depth)
        return fill_depth, total_USD / amount_, total_USD


    '''
    Get average price to fill depth from amount (counter)
    '''
    @staticmethod
    def price_from_depth_base(depth, total_counter):
        fill_depth = []
        current_amount = total_counter

        for price,amount in depth:
            total_amount = price * amount
            # take all
            if current_amount < total_amount:
                fill_amount = current_amount / price
                fill_depth.append([price, fill_amount])
                current_amount = 0
            else:
                current_amount -= total_amount
                fill_depth.append([price, amount])

        total_amount = 0
        for price,amount in fill_depth:
            total_amount += amount

        #print(fill_depth)
        return fill_depth, total_counter / total_amount, total_amount

    '''
        Given a depth, balances, calculate the order that satisfy the constraint
        of balances available, and available amount depth per price level
        (assume example in BTC/USD)
    '''
    def calculate_orders(self, depth, filter_depth, balance_internal, balance_external):
        # check minimum base, and counter available to make exchange
        buy_orders = []
        sell_orders = []

        current_balance_internal = balance_internal.copy()
        current_balance_external = balance_external.copy()

        for price,amount in filter_depth["bids"]:
            # how much can we buy BTC (giving USD) on our market?
            internal_pays_amount_usd = current_balance_internal[self.pair_i[1]] # USD

            # with the BTC on the external exchange, how much can we sell them for in USD
            total_btc = current_balance_external[self.pair_e[0]]
            if total_btc == 0:
                break

            # we should walk from our previous position just to  be precise
            fill_depth, price_from_depth,external_total_USD = self.price_from_depth(depth["bids"], total_btc)

            # we should pick minimum money available internal market, and external market
            depth_pays_usd_limit = price * amount

            #print("min?", pays_amount_usd_limit, total_USD, pays_amount_usd)
            usd_limit = min(depth_pays_usd_limit, external_total_USD, internal_pays_amount_usd)
            btc_limit = usd_limit/price

            if btc_limit < self.minimum_amount:
                #print("buy amount is too small ", btc_limit)
                continue

            fill_depth, price_from_depth, fill_USD = self.price_from_depth(depth["bids"], btc_limit)
            expected_usd_give = price * btc_limit
            expected_usd_take = price_from_depth * btc_limit
            expected_profit = expected_usd_take - expected_usd_give
            print("Estimated profit={:.2f} {} buy_at={}, sell_at={}".format(expected_profit, self.pair_i[1], price, price_from_depth))

            buy_orders.append([price, btc_limit])
            current_balance_internal[self.pair_i[1]] -= usd_limit
            current_balance_external[self.pair_e[0]] -= btc_limit

        for price,amount in filter_depth["asks"]:
            # how much can we sell BTC (giving BTC) on our market?
            internal_pays_amount_btc = current_balance_internal[self.pair_i[0]]

            # with the USD on the external exchange, how much BTC can we get
            total_usd = current_balance_external[self.pair_e[1]]
            if total_usd == 0:
                break

            # we should walk from our previous position just to  be precise
            fill_depth, price_from_depth, external_total_BTC = self.price_from_depth_base(depth["asks"], total_usd)

            # we should pick minimum money available internal market, and external market
            pays_amount_btc_limit = amount

            #print("min?", pays_amount_usd_limit, total_USD, pays_amount_usd)
            btc_limit = min(pays_amount_btc_limit, external_total_BTC, internal_pays_amount_btc)
            usd_limit = price * btc_limit

            if btc_limit < self.minimum_amount:
                #print("buy amount is too small ", btc_limit)
                continue

            fill_depth, price_from_depth, btc_filled = self.price_from_depth_base(depth["asks"], usd_limit)
            expected_btc_give = btc_limit
            expected_btc_take = btc_filled
            expected_profit = expected_btc_take - expected_btc_give
            print("Estimated profit={:.4f} {} (~{:.2f} {}) sell_at={}, buy_at={}".format(expected_profit, self.pair_i[0], expected_profit* price, self.pair_i[1], price, price_from_depth))

            sell_orders.append([price, btc_limit])
            current_balance_internal[self.pair_i[0]] -= btc_limit
            current_balance_external[self.pair_e[1]] -= usd_limit

        return buy_orders, sell_orders

    def update(self, depth, min_spread, balanceI, balanceE):
        depth, raw_depth, num_dec = self.calculate_depth(depth)
        center_price = (depth['bids'][0][0] + depth['asks'][0][0]) / 2
        spread,new_spread, lowest_price, highest_price = self.calculate_spread(min_spread, depth, center_price,num_dec)
        new_depth = self.filter_depth(depth, lowest_price, highest_price)

        # create order based on our projected depth
        buy_orders, sell_orders = self.calculate_orders(raw_depth, new_depth, balanceI, balanceE)

        return buy_orders, sell_orders

