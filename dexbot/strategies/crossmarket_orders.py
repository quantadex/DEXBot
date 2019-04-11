import math
from datetime import datetime, timedelta

from dexbot.strategies.base import StrategyBase, ConfigElement, DetailElement, EXCHANGES
from dexbot.qt_queue.idle_queue import idle_add
from dexbot.strategies.crossmarket.strategy import CrossMarketStrategy,CrossMarketUserData
from dexbot.strategies.crossmarket.external_market import ExternalMarket
from dexbot.strategies.crossmarket.internal_market import InternalMarket
from bitshares.amount import Amount, Asset
import time
from dexbot.strategies.external_feeds.price_feed import PriceFeed

class Strategy(StrategyBase):
    """ Relative Orders strategy
    """

    @classmethod
    def configure(cls, return_base_config=True):
        return StrategyBase.configure(return_base_config) + [
            # ConfigElement('amount', 'float', 1, 'Order Size',
            #               'Fixed order size, expressed in quote asset, unless "relative order size" selected',
            #               (0, None, 8, '')),
            #ConfigElement('relative_order_size', 'bool', False, 'Relative order size',
            #              'Amount is expressed as a percentage of the account balance of quote/base asset', None),
            ConfigElement('spread', 'float', 5, 'Min Spread',
                          'Minimum spread between the external, and our own orders', (0, 100, 2, '%')),
            ConfigElement('external_price_source', 'choice', EXCHANGES[0], 'External price source',
                          'The bot will try to get price information from this source', EXCHANGES),
            ConfigElement('external_market_ticker', 'string', '', 'External market ticker if differ',
                          "External market ticket separated with /", None),
            ConfigElement('external_market_api_key', 'string', '', 'External API Key',
                          "External market ticket separated with /", None),
            ConfigElement('external_market_api_secret', 'string', '', 'External API Secret',
                          "External market ticket separated with /", None),
            ConfigElement('limit_order_depth_multiplier', 'float', 1, 'Limit Order Depth Multiplier',
                          'The multiplier of depth required to place an order', (1, 10, 0, 'X')),
            # ConfigElement('center_price_depth', 'float', 0, 'Measurement depth',
            #               'Cumulative quote amount from which depth center price will be measured',
            #               (0.00000001, 1000000000, 8, '')),
            ConfigElement('center_price_offset', 'bool', False, 'Center price offset based on asset balances',
                          'Automatically adjust orders up or down based on the imbalance of your assets', None),
            ConfigElement('manual_offset', 'float', 0, 'Manual center price offset',
                          "Manually adjust orders up or down. "
                          "Works independently of other offsets and doesn't override them", (-50, 100, 2, '%')),
            ConfigElement('reset_on_price_change', 'bool', False, 'Reset orders on center price change',
                          'Reset orders when center price is changed more than threshold '
                          '(set False for external feeds)', None),
            ConfigElement('price_change_threshold', 'float', 50, 'Price change threshold',
                          'Define center price threshold to react on', (0, 100, 2, '%')),
            ConfigElement('custom_expiration', 'bool', False, 'Custom expiration',
                          'Override order expiration time to trigger a reset', None),
            ConfigElement('expiration_time', 'int', 157680000, 'Order expiration time',
                          'Define custom order expiration time to force orders reset more often, seconds',
                          (30, 157680000, ''))
        ]

    @classmethod
    def configure_details(cls, include_default_tabs=True):
        return StrategyBase.configure_details(include_default_tabs) + []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.log.info("Initializing CrossMarketOrders")

        # don't clear your orders history
        self.clear_enabled = False

        # Tick counter
        self.counter = 0
        self.fill_history = {}

        # Define Callbacks
        self.ontick += self.tick
        self.onMarketUpdate += self.check_orders
        self.onAccount += self.check_orders

        self.error_ontick = self.error
        self.error_onMarketUpdate = self.error
        self.error_onAccount = self.error

        # Market status
        self.empty_market = False

        # Get market center price from Bitshares
        self.market_center_price = None # self.get_market_center_price(suppress_errors=True)

        # Set external price source, defaults to False if not found
        self.external_feed = self.worker.get('external_feed', True)
        self.external_price_source = self.worker.get('external_price_source', None)
        self.external_market_ticker = self.worker.get('external_market_ticker', self.market.get_string("/"))
        self.percent_depth = self.worker.get('limit_order_depth_multiplier', 10.0)
        self.strategy = CrossMarketStrategy(self.market.get_string("/"), self.external_market_ticker, {"percent_depth": self.percent_depth})
        self.external_market = ExternalMarket(self.worker.get('external_price_source', ''),
                                                {
                                                    "api_key": self.worker.get('external_market_api_key', ''),
                                                    "api_secret": self.worker.get('external_market_api_secret', ''),
                                             })
        self.internal_market = InternalMarket()

        if self.external_feed:
            # Get external center price from given source
            self.external_market_center_price = self.get_center_simple(self.external_price_source,self.external_market_ticker)

        if not self.market_center_price:
            # Bitshares has no center price making it an empty market or one that has only one sided orders
            self.empty_market = True

        # Worker parameters
        self.is_center_price_dynamic = self.worker.get('center_price_dynamic', True)

        if self.is_center_price_dynamic:
            self.center_price = None
            self.center_price_depth = self.worker.get('center_price_depth', 0)
        else:
            # Use manually set center price
            self.center_price = self.worker["center_price"]
            
        #self.is_relative_order_size = self.worker.get('relative_order_size', False)
        self.is_asset_offset = self.worker.get('center_price_offset', False)
        self.manual_offset = self.worker.get('manual_offset', 0) / 100
        #self.order_size = float(self.worker.get('amount', 1))

        # Spread options
        self.spread = self.worker.get('spread')
        self.market_depth_amount = self.worker.get('market_depth_amount', 0)

        self.is_reset_on_partial_fill = self.worker.get('reset_on_partial_fill', True)
        self.partial_fill_threshold = self.worker.get('partial_fill_threshold', 30) / 100
        self.is_reset_on_price_change = self.worker.get('reset_on_price_change', False)
        self.price_change_threshold = self.worker.get('price_change_threshold', 2) / 100
        self.is_custom_expiration = self.worker.get('custom_expiration', False)

        if self.is_custom_expiration:
            self.expiration = self.worker.get('expiration_time', self.expiration)

        self.last_check = datetime.now()
        self.min_check_interval = 8

        self.buy_price = None
        self.sell_price = None
        self.initializing = True

        self.initial_balance = self['initial_balance'] or 0
        self.worker_name = kwargs.get('name')
        self.view = kwargs.get('view')

        # Check for conflicting settings
        if self.is_reset_on_price_change and not self.is_center_price_dynamic:
            self.log.error('"Reset orders on center price change" requires "Dynamic Center Price"')
            self.disabled = True
            return

        # Check if market has center price when using dynamic center price
        if not self.external_feed and self.empty_market and (self.is_center_price_dynamic or self.dynamic_spread):
            self.log.info('Market is empty and using dynamic market parameters. Waiting for market change...')
            return

        # Check old orders from previous run (from force-interruption) only whether we are not using
        # "Reset orders on center price change" option
        if self.is_reset_on_price_change:
            self.log.info('"Reset orders on center price change" is active, placing fresh orders')
            self.update_orders()
        else:
            self.check_orders()

    def error(self, *args, **kwargs):
        self.disabled = True

    def tick(self, d):
        """ Ticks come in on every block. We need to periodically check orders because cancelled orders
            do not triggers a market_update event
        """
        if (self.is_reset_on_price_change and not
                self.counter % 5):
            self.log.debug('Checking orders by tick threshold')
            self.check_orders()
        self.counter += 1

    def get_center_simple(self, external_price_source, external_ticker):
        market = external_ticker or self.market.get_string('/')
        self.log.debug('market: {}  '.format(market))
        price_feed = PriceFeed(external_price_source, market)
        price_feed.filter_symbols()
        center_price = price_feed.get_center_price(None)
        return center_price

    def calculate_order_prices(self):
        depth = self.external_market.getDepth(self.external_market_ticker)
        self.center_price = self.get_external_market_center_price(self.external_price_source,self.external_market_ticker)
        depth,raw_depth, num_dec = self.strategy.calculate_depth(depth)
        spread,new_spread, lowest_price, highest_price = self.strategy.calculate_spread(self.spread, depth, self.center_price,num_dec)
        self.log.info("center_price={} spread={} new_spread={} lowest_price={} highest_price={}".format(self.center_price, spread, new_spread, lowest_price, highest_price))

        # step 3: with spread, let's filter the depth to only our interested spread
        new_depth = self.strategy.filter_depth(depth, lowest_price, highest_price)
        #self.log.info("filter_depth={}".format(new_depth))

        balanceI = { self.market['quote'].symbol: self.balance(self.market['quote']).amount,
                     self.market['base'].symbol: self.balance(self.market['base']).amount}

        balance = self.external_market.get_balance()
        balanceE = {k : balance['free'][k] for k in balance['free'] if (k in self.strategy.pair_e)}
        balanceET = {k : balance['total'][k] for k in balance['total']  if (k in self.strategy.pair_e)}

        self.log.info("QUANTA balance {}".format(balanceI))
        self.log.info("{} balance used={} total={}".format(self.external_price_source, balanceE, balanceET))

        self.buy_orders, self.sell_orders = self.strategy.calculate_orders(raw_depth, new_depth, balanceI, balanceE)
        self.log.info("buys={} sells={}".format(self.buy_orders, self.sell_orders))

    def update_orders(self):
        self.log.info('Starting to update orders')

        # Cancel the orders before redoing them
        self.cancel_all_orders()

        # soft remove
        for order_id in self.all_own_orders:
            res = self.remove_order({ "id": order_id})
            self.log.info("update order to cancelled {} {}".format(order_id, res))

        #self.clear_orders()

        # Recalculate buy and sell order prices
        self.calculate_order_prices()

        order_ids = []
        expected_num_orders = 0

        for order in self.buy_orders:
            buy_order = self.place_market_buy_order(order[1], order[0], True)
            if buy_order:
                self.save_order(buy_order)
                order_ids.append(buy_order['id'])
            expected_num_orders += 1

        # Sell Side
        for order in self.sell_orders:
            sell_order = self.place_market_sell_order(order[1], order[0], True)
            if sell_order:
                self.save_order(sell_order)
                order_ids.append(sell_order['id'])
            expected_num_orders += 1

        self['order_ids'] = order_ids
        self.log.info("Done placing orders {}".format(order_ids))

        # Some orders weren't successfully created, redo them
        if len(order_ids) < expected_num_orders and not self.disabled:
            self.update_orders()

    def _calculate_center_price(self, suppress_errors=False):
        highest_bid = float(self.ticker().get('highestBid'))
        lowest_ask = float(self.ticker().get('lowestAsk'))

        if highest_bid is None or highest_bid == 0.0:
            if not suppress_errors:
                self.log.critical(
                    "Cannot estimate center price, there is no highest bid."
                )
                #self.disabled = True
            return None
        elif lowest_ask is None or lowest_ask == 0.0:
            if not suppress_errors:
                self.log.critical(
                    "Cannot estimate center price, there is no lowest ask."
                )
                #self.disabled = True
            return None

        # Calculate center price between two closest orders on the market
        return highest_bid * math.sqrt(lowest_ask / highest_bid)

    def calculate_center_price(self, center_price=None, asset_offset=False, spread=None,
                               order_ids=None, manual_offset=0, suppress_errors=True):
        """ Calculate center price which shifts based on available funds
        """
        if center_price is None:
            # No center price was given so we simply calculate the center price
            calculated_center_price = self._calculate_center_price(suppress_errors)
        else:
            # Center price was given so we only use the calculated center price for quote to base asset conversion
            calculated_center_price = self._calculate_center_price(True)
            if not calculated_center_price:
                calculated_center_price = center_price

        if center_price:
            calculated_center_price = center_price

        # Calculate asset based offset to the center price
        if asset_offset:
            calculated_center_price = self.calculate_asset_offset(calculated_center_price, order_ids, spread)

        # Calculate final_offset_price if manual center price offset is given
        if manual_offset:
            calculated_center_price = self.calculate_manual_offset(calculated_center_price, manual_offset)

        return calculated_center_price

    def calculate_asset_offset(self, center_price, order_ids, spread):
        """ Adds offset based on the asset balance of the worker to the center price

            :param float | center_price: Center price
            :param list | order_ids: List of order ids that are used to calculate balance
            :param float | spread: Spread percentage as float (eg. 0.01)
            :return: Center price with asset offset
        """
        total_balance = self.count_asset(order_ids)
        total = (total_balance['quote'] * center_price) + total_balance['base']

        if not total:  # Prevent division by zero
            base_percent = quote_percent = 0.5
        else:
            base_percent = total_balance['base'] / total
            quote_percent = 1 - base_percent

        highest_bid = float(self.ticker().get('highestBid'))
        lowest_ask = float(self.ticker().get('lowestAsk'))

        lowest_price = center_price / (1 + spread)
        highest_price = center_price * (1 + spread)

        # Use highest_bid price if spread-based price is lower. This limits offset aggression.
        lowest_price = max(lowest_price, highest_bid)
        # Use lowest_ask price if spread-based price is higher
        highest_price = min(highest_price, lowest_ask)

        return math.pow(highest_price, base_percent) * math.pow(lowest_price, quote_percent)

    @staticmethod
    def calculate_manual_offset(center_price, manual_offset):
        """ Adds manual offset to given center price

            :param float | center_price:
            :param float | manual_offset:
            :return: Center price with manual offset

            Adjust center price by given percent in symmetrical way. Thus, -1% adjustement on BTS:USD market will be
            same as adjusting +1% on USD:BTS market.
        """
        if manual_offset < 0:
            return center_price / (1 + abs(manual_offset))
        else:
            return center_price * (1 + manual_offset)

    def counter_fill(self, changed):
        # update cross order status where possible
        new_orders = {}

        # place new counter fill orders
        for order in changed:
            if order["type"] == "buy":
                self.log.info("Counterfill: {}".format(order))
                # sell on crossmarket
                order_res = self.external_market.sell_order(self.external_market_ticker, 0, order['quote']['amount'])
                new_orders[order_res["id"]] = order
            elif order["type"] == "sell":
                self.log.info("Sell {}".format(order))
                order_res = self.external_market.buy_order(self.external_market_ticker, 0, order['quote']['amount'])
                new_orders[order_res["id"]] = order

        # probably orders executed in 2 sec.
        time.sleep(2)

        # update counter status
        # might need to convert base/counter => basecounter
        external_orders = self.external_market.fetch_closed_trades(self.external_market_ticker)
        for order_fetched in external_orders:
            if order_fetched["id"] in new_orders:
                # fetch in db
                order = new_orders[order_fetched["id"]]
                res = self.fetch_order(order.order_id)
                if res:
                    self.log.info("order updated - filled " + order_fetched["id"])
                    user_data = CrossMarketUserData.fromJSON(res.userdata)
                    user_data.fill_orders[order_fetched["id"]] = order_fetched
                    self.update_order(order.order_id, user_data.to_json())
                else:
                    self.log.info("order " + order_fetched["id"] + " did not fill after 2 sec")
                    self.log.info("could not find order in db " + order_fetched["id"])


    def check_orders(self, *args, **kwargs):
        """ Tests if the orders need updating
        """

        # wait for api to catch up
        time.sleep(1)

        delta = datetime.now() - self.last_check

        # Store current available balance and balance in orders to the database for profit calculation purpose
        self.store_profit_estimation_data()

        # Only allow to check orders whether minimal time passed
        if delta < timedelta(seconds=self.min_check_interval) and not self.initializing:
            self.log.debug('Ignoring market_update event as min_check_interval is not passed')
            return

        orders = self.fetch_orders(raw=True)

        # Detect complete fill, order expiration, manual cancel, or just init
        need_update = False
        if not orders:
            need_update = True
        else:
            self.log.info("checking filled orders")

            # get filled orders
            ops = self.internal_market.get_account_orders_by_operation_type(self.account.identifier, "4")
            filled = self.internal_market.transform_to_order(ops, self.market['base']['id'])
            #print("Checking ops", len(ops),len(filled))

            filled_ids = list(map(lambda x: x.order_id, filled))
            #print("filled", filled_ids)

            changed_set = []
            current_active_orders = 0
            # Loop trough the orders and look for changes
            for order in orders:
                order_id = order.order_id
                current_order = self.get_order(order_id)

                if current_order:
                    current_active_orders += 1

                filtered = list(filter(lambda x: x.order_id == order_id, filled))
                # self.log.info("filtered found {} for order_id={}".format(len(filtered), order_id))
                # if database value do not match with our value

                try:
                    user_data = CrossMarketUserData.fromJSON(order.userdata)
                    changed = user_data.update(filtered)
                    if len(changed) > 0:
                        self.update_order(order_id, user_data.to_json())
                        changed_set.extend(changed)
                except Exception as e:
                    print(type(e).__name__, e.args, 'Parsing error (ignoring)')

            if current_active_orders <= 0:
                need_update = True

            if len(changed_set) > 0:
                try:
                    self.log.info('total orders fill updated = {} active_orders={}'.format(len(changed_set), current_active_orders))
                    self.counter_fill(changed_set)
                except Exception as x:
                    self.log.info(str(x))

        # Check center price change when using market center price with reset option on change
        if self.is_reset_on_price_change and self.is_center_price_dynamic:
            # This doesn't use external price feed because it is not allowed to be active
            # same time as reset_on_price_change
            spread = self.spread

            # center_price = self.calculate_center_price(
            #     None,
            #     self.is_asset_offset,
            #     spread,
            #     self['order_ids'],
            #     self.manual_offset
            # )
            center_price = self.get_center_simple(self.external_price_source,
                                                                      self.external_market_ticker)
            diff = abs((self.center_price - center_price) / self.center_price)
            if diff >= self.price_change_threshold:
                self.log.debug('Center price changed, updating orders. Diff: {:.2%}'.format(diff))
                need_update = True

        if need_update:
            self.update_orders()
        elif self.initializing:
            self.log.info("Orders correct on market")

        self.initializing = False

        if self.view:
            self.update_gui_slider()
            self.update_gui_profit()

        self.last_check = datetime.now()
