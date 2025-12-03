"""
Logging Module

Handles application logging setup and configuration.
"""

import logging
from pathlib import Path


def setup_logging(log_file_path: Path) -> logging.Logger:
    """
    Sets up a robust logger that writes to a file.
    
    Args:
        log_file_path: Path object for the log file location
        
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Clear existing handlers to avoid duplicate logs
    if logger.hasHandlers():
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
    
    try:
        # Create file handler
        file_handler = logging.FileHandler(log_file_path, mode='a', encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        
        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        
        # Add handler to logger
        logger.addHandler(file_handler)
        
        logging.info(f"Logging initialized. Log file: {log_file_path}")
        
    except Exception as e:
        print(f"Error setting up logging: {e}")
        logging.warning(f"Could not set up file logging: {e}")
    
    return logger


def get_logger():
    """Get the current logger instance."""
    return logging.getLogger()
