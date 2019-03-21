
import bitshares
from bitshares.instance import shared_bitshares_instance
from bitshares.asset import Asset
from bitshares.account import Account
from bitshares.exceptions import KeyAlreadyInStoreException
from bitsharesbase.account import PrivateKey

import sys

class WalletManager:

    def __init__(self, bitshares_instance):
        self.bitshares = bitshares_instance or shared_bitshares_instance()

    def wallet_created(self):
        return self.bitshares.wallet.created()

    def create_wallet(self, password, confirm_password):
        if password == confirm_password:
            self.bitshares.wallet.create(password)
            return True
        else:
            return False

    def unlock_wallet(self, password):
        try:
            self.bitshares.wallet.unlock(password)
            return True
        except bitshares.exceptions.WrongMasterPasswordException:
            return False

    def add_private_key(self, private_key):
        wallet = self.bitshares.wallet
        try:
            wallet.addPrivateKey(private_key)
        except KeyAlreadyInStoreException:
            # Private key already added
            pass

if __name__ == '__main__':
    server = sys.argv[1]
    pw = sys.argv[2]
    key = sys.argv[3]

    if server == "":
        server = "ws://testnet-01.quantachain.io:8090"

    bitshares = bitshares.BitShares(
        server,
        num_retries=-1
    )
    wm = WalletManager(bitshares)
    if wm.wallet_created():
        wm.unlock_wallet(pw)
    else:
        wm.create_wallet(pw, pw)

    wm.add_private_key(key)