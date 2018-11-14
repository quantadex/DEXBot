import os
import logging
import sys

from dexbot import VERSION, APP_NAME, AUTHOR
from dexbot.helper import initialize_orders_log, initialize_data_folders
from dexbot.worker import Worker
from dexbot.views.errors import PyQtHandler
from dexbot.storage import Storage

from appdirs import user_data_dir
from bitshares.instance import set_shared_bitshares_instance


class MainController:

    def __init__(self, bitshares_instance, config):
        self.bitshares_instance = bitshares_instance
        set_shared_bitshares_instance(bitshares_instance)

        # Global configuration which includes all the workers
        self.config = config

        # Worker Infrastructure
        self.worker_manager = []

        # Threading test
        self.workers = {}

        # Configure logging
        data_dir = user_data_dir(APP_NAME, AUTHOR)
        filename = os.path.join(data_dir, 'dexbot.log')
        formatter = logging.Formatter(
            '%(asctime)s - %(worker_name)s using account %(account)s on %(market)s - %(levelname)s - %(message)s')
        logger = logging.getLogger("dexbot.per_worker")
        fh = logging.FileHandler(filename)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
        logger.setLevel(logging.INFO)
        self.pyqt_handler = PyQtHandler()
        self.pyqt_handler.setLevel(logging.INFO)
        logger.addHandler(self.pyqt_handler)
        logger.info("DEXBot {} on python {} {}".format(VERSION, sys.version[:6], sys.platform), extra={
                    'worker_name': 'NONE', 'account': 'NONE', 'market': 'NONE'})

        # Configure orders logging
        initialize_orders_log()

        # Initialize folders
        initialize_data_folders()

    def set_info_handler(self, handler):
        self.pyqt_handler.set_info_handler(handler)

    def start_worker(self, worker_name, worker_config, view):
        # Start only one worker in it's own thread and add that thread to active workers list for this controller
        self.workers[worker_name] = Worker(worker_name, worker_config, self.bitshares_instance, view)
        # self.workers[worker_name].daemon = True

        try:
            # Start the Worker
            self.workers[worker_name].start()
        except RuntimeError:
            # start() already called for this Worker object
            pass

    def pause_worker(self, worker_name, config=None):
        # This check prevents pausing after edit if the worker isn't active
        if worker_name in self.workers:
            # Fixme: Worker doesn't pause
            # Pause worker thread
            self.workers[worker_name].stop(worker_name, pause=True)

            # Remove worker thread from the list
            self.workers.pop(worker_name)

    def remove_worker(self, worker_name):
        if worker_name in self.workers:
            self.workers[worker_name].remove_worker(worker_name)
            self.workers[worker_name].stop(worker_name)
        else:
            # Worker not running
            worker_config = self.config.get_worker_config(worker_name)[worker_name]
            Worker.remove_offline_worker(worker_name, worker_config, self.bitshares_instance)

    @staticmethod
    def create_worker(worker_name):
        # Todo: Rename this function to something better
        # In case worker is deleted only from config file, there are still information with the name in the database
        # This function removes all that data and cancels orders so that new worker can take the name in it's use
        Storage.clear_worker_data(worker_name)
