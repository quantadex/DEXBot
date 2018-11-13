import importlib
import sys
import logging
import os.path
import threading

import dexbot.errors as errors
from dexbot.strategies.base import StrategyBase

from bitshares.notify import Notify
from bitshares.instance import shared_bitshares_instance
from PyQt5.QtCore import QThread, pyqtSignal

log = logging.getLogger(__name__)
log_workers = logging.getLogger('dexbot.per_worker')
# NOTE this is the  special logger for per-worker events
# it returns LogRecords with extra fields: worker_name, account, market and is_disabled
# is_disabled is a callable returning True if the worker is currently disabled.
# GUIs can add a handler to this logger to get a stream of events of the running workers.


class WorkerThread(QThread):

    def __init__(self, worker_name, worker_config, bitshares_instance=None, view=None):
        super().__init__()

        # Parameters
        self.worker_name = worker_name
        self.worker_config = worker_config
        self.bitshares = bitshares_instance or shared_bitshares_instance()
        self.view = view

        self.jobs = set()
        self.notify = None

        # Active worker
        self.worker = {}

        self.account = set()
        self.market = set()

        # Set the module search path
        user_worker_path = os.path.expanduser("~/bots")
        if os.path.exists(user_worker_path):
            sys.path.append(user_worker_path)

    def init_worker(self, worker_name, worker_config):
        """ Initialize the worker
        """
        worker_config = worker_config[worker_name]

        if "account" not in worker_config:
            log_workers.critical("Worker has no account", extra={
                'worker_name': worker_name,
                'account': 'unknown',
                'market': 'unknown',
                'is_disabled': (lambda: True)
            })

        if "market" not in worker_config:
            log_workers.critical("Worker has no market", extra={
                'worker_name': worker_name,
                'account': worker_config['account'],
                'market': 'unknown',
                'is_disabled': (lambda: True)
            })

        try:
            strategy_class = getattr(
                importlib.import_module(worker_config["module"]),
                'Strategy'
            )

            self.worker[worker_name] = strategy_class(
                config=worker_config,
                name=worker_name,
                bitshares_instance=self.bitshares,
                view=self.view
            )

            self.market.add(worker_config['market'])
            self.account.add(worker_config['account'])
        except BaseException:
            log_workers.exception("Worker initialisation", extra={
                'worker_name': worker_name,
                'account': worker_config['account'],
                'market': 'unknown',
                'is_disabled': (lambda: True)
            })

    def update_notify(self):
        if not self.worker_config:
            log.critical("No worker configured to launch, exiting")
            raise errors.NoWorkersAvailable()
        if not self.worker:
            log.critical("No worker actually running")
            raise errors.NoWorkersAvailable()
        if self.notify:
            # Update the notification instance
            self.notify.reset_subscriptions(list(self.account), list(self.market))
        else:
            # Initialize the notification instance
            self.notify = Notify(
                markets=list(self.market),
                accounts=list(self.account),
                on_market=self.on_market,
                on_account=self.on_account,
                on_block=self.on_block,
                bitshares_instance=self.bitshares
            )

    # Events
    def on_block(self, data):
        print('on_block: {}'.format(self.worker_name))
        if self.jobs:
            try:
                for job in self.jobs:
                    job()
            finally:
                self.jobs = set()

        try:
            self.worker[self.worker_name].ontick(data)
        except Exception as e:
            self.worker[self.worker_name].log.exception("in ontick()")
            try:
                self.worker[self.worker_name].error_ontick(e)
            except Exception:
                self.worker[self.worker_name].log.exception("in error_ontick()")

    def on_market(self, data):
        print('on_market: {}'.format(self.worker_name))
        if data.get("deleted", False):  # No info available on deleted orders
            return

        if self.worker[self.worker_name].disabled:
            self.worker[self.worker_name].log.debug('Worker "{}" is disabled'.format(self.worker_name))
            return
        if self.worker_config[self.worker_name]['market'] == data.market:
            try:
                self.worker[self.worker_name].onMarketUpdate(data)
            except Exception as e:
                self.worker[self.worker_name].log.exception("in onMarketUpdate()")
                try:
                    self.worker[self.worker_name].error_onMarketUpdate(e)
                except Exception:
                    self.worker[self.worker_name].log.exception("in error_onMarketUpdate()")

    def on_account(self, account_update):
        print('on_account: {}'.format(self.worker_name))
        account = account_update.account

        if self.worker[self.worker_name].disabled:
            self.worker[self.worker_name].log.info('Worker "{}" is disabled'.format(self.worker_name))
            return
        if self.worker["account"] == account["name"]:
            try:
                self.worker[self.worker_name].onAccount(account_update)
            except Exception as e:
                self.worker[self.worker_name].log.exception("in onAccountUpdate()")
                try:
                    self.worker[self.worker_name].error_onAccount(e)
                except Exception:
                    self.worker[self.worker_name].log.exception("in error_onAccountUpdate()")

    def run(self):
        """ Thread run
            Overrides threading.Thread.run()
        """
        self.init_worker(self.worker_name, self.worker_config)
        self.update_notify()
        self.notify.listen()

    def stop(self, worker_name, pause=False):
        """ Used to stop the worker(s)

            :param str worker_name: name of the worker to stop
            :param bool pause: optional argument which tells worker if it was stopped or just paused
        """
        try:
            # Kill only the specified worker
            self.remove_market(worker_name)
        except KeyError:
            # Worker was not found meaning it does not exist or it is paused already
            return

        account = self.worker_config[worker_name]['account']
        self.account.remove(account)

        # if pause:
        #     self.worker[worker_name].pause()
        # self.worker.pop(worker_name, None)

        # Update other workers
        # if len(self.worker) > 0:
        #     self.update_notify()
        # else:

        # Close the websocket connection for this worker (?)
        self.notify.websocket.close()

    def remove_worker(self, worker_name=None):
        if worker_name:
            self.worker[worker_name].purge()
        else:
            for worker in self.worker:
                self.worker[worker].purge()

    def remove_market(self, worker_name):
        """ Remove the market only if the worker is the only one using it
        """
        # with self.config_lock:
        market = self.worker_config[worker_name]['market']
        self.market.remove(market)

    @staticmethod
    def remove_offline_worker(worker_name, worker_config, bitshares_instance):
        # Initialize the base strategy to get control over the data
        strategy = StrategyBase(worker_name, worker_config, bitshares_instance=bitshares_instance)
        # Purge all worker data and cancel orders
        strategy.purge()

    @staticmethod
    def remove_offline_worker_data(worker_name):
        # Remove all worker data, but don't cancel orders
        StrategyBase.purge_all_local_worker_data(worker_name)

    def do_next_tick(self, job):
        """ Add a callable to be executed on the next tick """
        self.jobs.add(job)
