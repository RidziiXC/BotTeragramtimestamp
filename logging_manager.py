import logging
import os

def setup_logging(log_filename="bot_activity.log"):
    """
    Sets up logging to output to both console and a specified log file.
    This function should be called once at the start of the application.
    """
    if not logging.root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_filename, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
    logging.info(f"Logging configured. Outputting to console and '{log_filename}'.")