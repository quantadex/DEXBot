import json
import urllib.request
from bitshares.price import FilledOrder, Order

DEFAULT_URL = "https://wya99cec1d.execute-api.us-east-1.amazonaws.com/testnet/account"

class InternalMarket:
    def __init__(self, url=DEFAULT_URL):
        self.url = url

    def get_account_orders_by_operation_type(self, accountId, operationTypes, size=50):
        call_url = "{}?filter_field=operation_type&filter_value={}&size={}&account_id={}".format(self.url, operationTypes, size, accountId)
        webURL = urllib.request.urlopen(call_url)
        data = webURL.read()
        encoding = webURL.info().get_content_charset('utf-8')
        JSON_object = json.loads(data.decode(encoding))
        return JSON_object

    def transform_to_order(self, operations, base_asset):
        found = []
        for x in operations:
            if 'operation_history' in x:
                if 'op_object' in x['operation_history']:
                    order = Order(x['operation_history']['op_object'], base_asset=base_asset)
                    order_id = x['operation_history']['op_object']['order_id']
                    order.order_id = order_id
                    order.virtual_op = x['operation_history']['virtual_op']

                    found.append(order)
        return found

    def find_orderid(self, operations, order_id, base_asset):
        found = []
        for x in operations:
            if 'operation_history' in x:
                if 'op_object' in x['operation_history']:
                    if 'order_id' in x['operation_history']['op_object']:
                        if x['operation_history']['op_object']['order_id'] == order_id:
                            order = Order(x['operation_history']['op_object'], base_asset=base_asset)
                            order.order_id = order_id
                            order.virtual_op = x['operation_history']['virtual_op']
                            found.append(order)
        return found
