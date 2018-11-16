import importlib
import sys
import logging
import os.path

from random import randint
import time

import dexbot.errors as errors
from dexbot.strategies.base import StrategyBase

from bitshares.notify import Notify
from bitshares.instance import shared_bitshares_instance
from PyQt5.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

log = logging.getLogger(__name__)
log_workers = logging.getLogger('dexbot.per_worker')
# NOTE this is the  special logger for per-worker events
# it returns LogRecords with extra fields: worker_name, account, market and is_disabled
# is_disabled is a callable returning True if the worker is currently disabled.
# GUIs can add a handler to this logger to get a stream of events of the running workers.


# class Worker(QThread):  # Change to QObject later
class Worker(QObject):
    """ Must derive from QObject in order to emit signals, connect slots to other signals, and operate in a QThread.
    """

    sig_step = pyqtSignal(str)  # worker id, step description: emitted every step through work() loop
    sig_done = pyqtSignal()  # worker id: emitted at end of work()
    sig_msg = pyqtSignal(str)  # message to be shown to user

    def __init__(self, worker_name, worker_config, bitshares_instance=None, view=None):
        super().__init__()
        self.__worker_name = worker_name
        self.config = worker_config
        self.bitshares_instance = bitshares_instance
        self.view = view
        self.__abort = False

    @pyqtSlot(name='run')
    def run(self):
        # This is same as run in DEXBot
        """
        Pretend this worker method does work that takes a long time. During this time, the thread's
        event loop is blocked, except if the application's processEvents() is called: this gives every
        thread (incl. main) a chance to process events, which in this sample means processing signals
        received from GUI (such as abort).
        """
        thread_name = QThread.currentThread().objectName()
        thread_id = int(QThread.currentThreadId())  # cast to int() is necessary
        self.sig_msg.emit('Running worker #{} from thread "{}" (#{})'.format(self.__worker_name, thread_name, thread_id))

        for step in range(100):
            sleep_time = randint(1, 10)

            if self.__abort:
                # note that "step" value will not necessarily be same for every thread
                self.sig_msg.emit('Worker {} aborting work at step {}'.format(self.__worker_name, step))
                break

            # app.processEvents()  # this could cause change to self.__abort
            for sleep in range(sleep_time):
                time.sleep(1)
                self.sig_step.emit('Current step is {} \nTime to next step {} seconds'.format(step, sleep_time - sleep))
            # check if we need to abort the loop; need to process events to receive signals;

        self.sig_done.emit(self.__worker_name)

    @pyqtSlot(name='stop')
    def stop(self):
        self.sig_msg.emit('Worker #{} notified to abort'.format(self.__worker_name))
        self.__abort = True

    # -----------------

    # # Todo: Add a que for each thread that can que up the incoming tasks
    #
    # signal_tick = pyqtSignal(int, str)  # worker id, step description: emitted every step through work() loop
    # signal_done = pyqtSignal(int)  # worker id: emitted at end of work()
    # signal_percentage = pyqtSignal(str)  # message to be shown to user
    #
    # def __init__(self, worker_name, worker_config, bitshares_instance=None, view=None):
    #     super().__init__()
    #
    #     # Parameters
    #     self.worker_name = worker_name
    #     self.worker_config = worker_config[worker_name]
    #     self.bitshares = bitshares_instance or shared_bitshares_instance()
    #     self.view = view
    #
    #     self.jobs = set()
    #     self.notify = None
    #
    #     # Strategy of the worker
    #     self.strategy = {}
    #
    #     self.account = set()
    #     self.market = set()
    #
    #     # Stop flag
    #     self.__abort = False
    #
    #     # Set the module search path
    #     user_worker_path = os.path.expanduser("~/bots")
    #     if os.path.exists(user_worker_path):
    #         sys.path.append(user_worker_path)
    #
    # # def init_worker(self, worker_name, worker_config):
    # #     """ Initialize the worker :)
    # #
    # #         Calls strategy __init__
    # #     """
    #     # worker_config = worker_config[worker_name]
    #
    #     # Check that config includes account and market before moving on
    #     if "account" not in self.worker_config:
    #         log_workers.critical("Worker has no account", extra={
    #             'worker_name': self.worker_name,
    #             'account': 'unknown',
    #             'market': 'unknown',
    #             'is_disabled': (lambda: True)
    #         })
    #
    #     if "market" not in self.worker_config:
    #         log_workers.critical("Worker has no market", extra={
    #             'worker_name': self.worker_name,
    #             'account': self.worker_config['account'],
    #             'market': 'unknown',
    #             'is_disabled': (lambda: True)
    #         })
    #
    #     try:
    #         # Get the strategy class using module in the config
    #         strategy_class = getattr(
    #             importlib.import_module(self.worker_config["module"]),
    #             'Strategy'
    #         )
    #
    #         # Call strategy init here
    #         self.strategy[self.worker_name] = strategy_class(
    #             config=self.worker_config,
    #             name=self.worker_name,
    #             bitshares_instance=self.bitshares,
    #             view=self.view
    #         )
    #
    #         self.market.add(self.worker_config['market'])
    #         self.account.add(self.worker_config['account'])
    #
    #     except BaseException:
    #         log_workers.exception("Worker initialisation", extra={
    #             'worker_name': self.worker_name,
    #             'account': self.worker_config['account'],
    #             'market': 'unknown',
    #             'is_disabled': (lambda: True)
    #         })
    #
    # def update_notify(self):
    #     if not self.worker_config:
    #         log.critical("No worker configured to launch, exiting")
    #         raise errors.NoWorkersAvailable()
    #     if not self.strategy:
    #         log.critical("No worker actually running")
    #         raise errors.NoWorkersAvailable()
    #     if self.notify:
    #         # Update the notification instance
    #         self.notify.reset_subscriptions(list(self.account), list(self.market))
    #     else:
    #         # Initialize the notification instance
    #         self.notify = Notify(
    #             markets=list(self.market),
    #             accounts=list(self.account),
    #             on_market=self.on_market,
    #             on_account=self.on_account,
    #             on_block=self.on_block,
    #             bitshares_instance=self.bitshares
    #         )
    #
    # # Events
    # def on_block(self, data):
    #     print('on_block: {}'.format(self.worker_name))
    #     if self.jobs:
    #         try:
    #             for job in self.jobs:
    #                 job()
    #         finally:
    #             self.jobs = set()
    #
    #     try:
    #         self.strategy[self.worker_name].ontick(data)
    #     except Exception as e:
    #         self.strategy[self.worker_name].log.exception("in ontick()")
    #         try:
    #             self.strategy[self.worker_name].error_ontick(e)
    #         except Exception:
    #             self.strategy[self.worker_name].log.exception("in error_ontick()")
    #
    # def on_market(self, data):
    #     print('on_market: {}'.format(self.worker_name))
    #     if data.get("deleted", False):  # No info available on deleted orders
    #         return
    #
    #     if self.strategy[self.worker_name].disabled:
    #         self.strategy[self.worker_name].log.debug('Worker "{}" is disabled'.format(self.worker_name))
    #         return
    #     if self.worker_config['market'] == data.market:
    #         try:
    #             self.strategy[self.worker_name].onMarketUpdate(data)
    #         except Exception as e:
    #             self.strategy[self.worker_name].log.exception("in onMarketUpdate()")
    #             try:
    #                 self.strategy[self.worker_name].error_onMarketUpdate(e)
    #             except Exception:
    #                 self.strategy[self.worker_name].log.exception("in error_onMarketUpdate()")
    #
    # def on_account(self, account_update):
    #     print('on_account: {}'.format(self.worker_name))
    #     account = account_update.account
    #
    #     if self.strategy[self.worker_name].disabled:
    #         self.strategy[self.worker_name].log.info('Worker "{}" is disabled'.format(self.worker_name))
    #         return
    #     if self.strategy["account"] == account["name"]:
    #         try:
    #             self.strategy[self.worker_name].onAccount(account_update)
    #         except Exception as e:
    #             self.strategy[self.worker_name].log.exception("in onAccountUpdate()")
    #             try:
    #                 self.strategy[self.worker_name].error_onAccount(e)
    #             except Exception:
    #                 self.strategy[self.worker_name].log.exception("in error_onAccountUpdate()")
    #
    # @pyqtSlot()
    # def run(self):
    #     # self.init_worker(self.worker_name, self.worker_config)
    #     self.update_notify()
    #     self.notify.listen()
    #     # Todo: Create thread here. Keep list of workers else where and signal the view
    #
    # def stop(self, worker_name, pause=False):
    #     """ Used to stop the worker
    #
    #         :param str worker_name: name of the worker to stop
    #         :param bool pause: optional argument which tells worker if it was stopped or just paused
    #     """
    #     try:
    #         # Kill only the specified worker
    #         # Todo: Is this needed here anymore, since the list of workers is else where
    #         self.market.remove(self.worker_config['market'])
    #     except KeyError:
    #         # Worker was not found meaning it does not exist or it is paused already
    #         return
    #
    #     self.account.remove(self.worker_config['account'])
    #
    #     # Close the websocket connection for this worker (?)
    #     # Todo: Move this to a better place
    #     self.notify.websocket.close()
    #
    # def remove_worker(self, worker_name):
    #     """ Removes the worker """
    #     self.strategy[worker_name].purge()
    #
    # @staticmethod
    # def remove_offline_worker(worker_name, worker_config, bitshares_instance):
    #     # Initialize the base strategy to get control over the data
    #     strategy = StrategyBase(worker_name, worker_config, bitshares_instance=bitshares_instance)
    #     # Purge all worker data and cancel orders
    #     strategy.purge()
    #
    # @staticmethod
    # def remove_offline_worker_data(worker_name):
    #     # Remove all worker data, but don't cancel orders
    #     StrategyBase.purge_all_local_worker_data(worker_name)
    #
    # def do_next_tick(self, job):
    #     """ Add a callable to be executed on the next tick """
    #     self.jobs.add(job)
