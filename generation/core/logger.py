import logging
import traceback


class Logger:

    logger = None

    def __init__(self, name, level):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)

        if not self.logger.handlers:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(level)

            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S')
            console_handler.setFormatter(formatter)

            self.logger.addHandler(console_handler)

    def ensure_max_length(self, message, limit=True):
        return message

    def log_info(self, message, limit=True):
        self.logger.info(self.ensure_max_length(message, limit))

    def log_error(self, message):
        self.logger.error(f"{message}. Traceback: { traceback.format_exc()}")

    def log_debug(self, message):
        self.logger.debug(self.ensure_max_length(message))
