"""
KADAS Altair Plugin - Logging System

Centralized logging configuration for the plugin.
Logs are saved to ~/.kadas/altair_plugin.log with rotation.
"""

import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
from datetime import datetime


class AltairLogger:
    """Centralized logger for KADAS Altair plugin"""
    
    _instance = None
    _initialized = False
    
    def __new__(cls):
        """Singleton pattern - one logger instance for entire plugin"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize logger only once"""
        if self._initialized:
            return
        
        self.logger = None
        self.log_file_path = None
        self._initialized = True
    
    def setup(self, user_profile_path: str = None):
        """
        Setup logging configuration.
        
        Args:
            user_profile_path: Path to user profile directory. 
                             If None, will use default location.
        """
        if self.logger is not None:
            # Already configured
            return self.logger
        
        # Determine log directory
        if user_profile_path:
            log_dir = Path(user_profile_path) / ".kadas"
        else:
            # Fallback to home directory
            log_dir = Path.home() / ".kadas"
        
        # Create log directory if it doesn't exist
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"Warning: Could not create log directory {log_dir}: {e}")
            # Fallback to temp directory
            import tempfile
            log_dir = Path(tempfile.gettempdir()) / ".kadas"
            log_dir.mkdir(parents=True, exist_ok=True)
        
        # Log file path
        self.log_file_path = log_dir / "altair_plugin.log"
        
        # Create logger
        self.logger = logging.getLogger('kadas_altair')
        self.logger.setLevel(logging.DEBUG)
        
        # Remove any existing handlers
        self.logger.handlers.clear()
        
        # File handler with rotation (max 5MB, keep 5 backup files)
        try:
            file_handler = RotatingFileHandler(
                self.log_file_path,
                maxBytes=5 * 1024 * 1024,  # 5 MB
                backupCount=5,
                encoding='utf-8'
            )
            file_handler.setLevel(logging.DEBUG)
            
            # Detailed format for file
            file_formatter = logging.Formatter(
                '%(asctime)s | %(levelname)-8s | %(name)s | %(filename)s:%(lineno)d | %(funcName)s() | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            file_handler.setFormatter(file_formatter)
            self.logger.addHandler(file_handler)
            
        except Exception as e:
            print(f"Error setting up file logging: {e}")
        
        # Console handler (for development/debugging)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        
        # Simpler format for console
        console_formatter = logging.Formatter(
            '%(levelname)-8s | %(name)s | %(message)s'
        )
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)
        
        # Log initialization
        self.logger.info("=" * 80)
        self.logger.info(f"KADAS Altair Plugin - Logging initialized")
        self.logger.info(f"Log file: {self.log_file_path}")
        self.logger.info(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.logger.info("=" * 80)
        
        return self.logger
    
    def get_logger(self, name: str = None) -> logging.Logger:
        """
        Get logger instance for a specific module.
        
        Args:
            name: Module name (will be appended to 'kadas_altair')
        
        Returns:
            Logger instance
        """
        if self.logger is None:
            self.setup()
        
        if name:
            # Create child logger
            return logging.getLogger(f'kadas_altair.{name}')
        else:
            return self.logger
    
    def get_log_file_path(self) -> Path:
        """Get path to log file"""
        return self.log_file_path
    
    def set_level(self, level: str):
        """
        Set logging level.
        
        Args:
            level: 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'
        """
        if self.logger is None:
            self.setup()
        
        level_map = {
            'DEBUG': logging.DEBUG,
            'INFO': logging.INFO,
            'WARNING': logging.WARNING,
            'ERROR': logging.ERROR,
            'CRITICAL': logging.CRITICAL
        }
        
        log_level = level_map.get(level.upper(), logging.INFO)
        self.logger.setLevel(log_level)
        
        # Update all handlers level
        for handler in self.logger.handlers:
            if isinstance(handler, RotatingFileHandler):
                handler.setLevel(log_level)
            elif isinstance(handler, logging.StreamHandler):
                # Console handler: keep at INFO minimum to avoid spam
                handler.setLevel(max(log_level, logging.INFO))
        
        self.logger.info(f"Logging level set to: {level.upper()}")
        
        if log_level == logging.DEBUG:
            self.logger.warning("DEBUG logging enabled - may impact performance during intensive operations")
    
    def log_event(self, event_type: str, message: str, **kwargs):
        """
        Log a structured event.
        
        Args:
            event_type: Type of event (e.g., 'search', 'auth', 'load')
            message: Event message
            **kwargs: Additional context data
        """
        if self.logger is None:
            self.setup()
        
        context = " | ".join([f"{k}={v}" for k, v in kwargs.items()])
        full_message = f"[{event_type.upper()}] {message}"
        if context:
            full_message += f" | {context}"
        
        self.logger.info(full_message)
    
    def log_performance(self, operation: str, duration: float, **kwargs):
        """
        Log performance metrics.
        
        Args:
            operation: Operation name
            duration: Duration in seconds
            **kwargs: Additional metrics
        """
        if self.logger is None:
            self.setup()
        
        context = " | ".join([f"{k}={v}" for k, v in kwargs.items()])
        message = f"[PERFORMANCE] {operation} completed in {duration:.3f}s"
        if context:
            message += f" | {context}"
        
        self.logger.info(message)
    
    def clear_old_logs(self, days: int = 30):
        """
        Clear log files older than specified days.
        
        Args:
            days: Number of days to keep
        """
        if self.log_file_path is None:
            return
        
        try:
            log_dir = self.log_file_path.parent
            cutoff_time = datetime.now().timestamp() - (days * 24 * 60 * 60)
            
            removed_count = 0
            for log_file in log_dir.glob("altair_plugin.log*"):
                if log_file.stat().st_mtime < cutoff_time:
                    log_file.unlink()
                    removed_count += 1
            
            if removed_count > 0:
                self.logger.info(f"Removed {removed_count} old log file(s)")
        
        except Exception as e:
            self.logger.error(f"Error clearing old logs: {e}")


# Global instance
_altair_logger = AltairLogger()


def setup_logging(user_profile_path: str = None) -> logging.Logger:
    """
    Setup plugin logging (call once at plugin initialization).
    
    Args:
        user_profile_path: Path to user profile directory
    
    Returns:
        Logger instance
    """
    return _altair_logger.setup(user_profile_path)


def get_logger(name: str = None) -> logging.Logger:
    """
    Get logger for a module.
    
    Args:
        name: Module name (e.g., 'connectors.copernicus')
    
    Returns:
        Logger instance
    
    Example:
        >>> from kadas_altair_plugin.logger import get_logger
        >>> logger = get_logger('gui.dock')
        >>> logger.info("Dock widget initialized")
    """
    return _altair_logger.get_logger(name)


def get_log_file_path() -> Path:
    """Get path to current log file"""
    return _altair_logger.get_log_file_path()


def set_log_level(level: str):
    """
    Set logging level for entire plugin.
    
    Args:
        level: 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'
    """
    _altair_logger.set_level(level)


def log_event(event_type: str, message: str, **kwargs):
    """
    Log a structured event.
    
    Args:
        event_type: Event type (e.g., 'search', 'auth', 'download')
        message: Event message
        **kwargs: Additional context
    
    Example:
        >>> log_event('search', 'Started search', collection='sentinel-2', bbox=[...])
    """
    _altair_logger.log_event(event_type, message, **kwargs)


def log_performance(operation: str, duration: float, **kwargs):
    """
    Log performance metrics.
    
    Args:
        operation: Operation name
        duration: Duration in seconds
        **kwargs: Additional metrics
    
    Example:
        >>> log_performance('search_copernicus', 2.345, results=42, collection='sentinel-2-l2a')
    """
    _altair_logger.log_performance(operation, duration, **kwargs)


# Convenience decorators
def log_function_call(func):
    """
    Decorator to automatically log function calls.
    
    Example:
        >>> @log_function_call
        >>> def search_imagery(bbox, dates):
        >>>     ...
    """
    import functools
    import time
    
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        logger = get_logger(func.__module__)
        
        # Log function entry
        args_repr = [repr(a) for a in args]
        kwargs_repr = [f"{k}={v!r}" for k, v in kwargs.items()]
        signature = ", ".join(args_repr + kwargs_repr)
        logger.debug(f"Calling {func.__name__}({signature})")
        
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            duration = time.time() - start_time
            logger.debug(f"{func.__name__} completed in {duration:.3f}s")
            return result
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"{func.__name__} failed after {duration:.3f}s: {e}", exc_info=True)
            raise
    
    return wrapper


def log_method_call(method):
    """
    Decorator to automatically log method calls (includes class name).
    
    Example:
        >>> class MyClass:
        >>>     @log_method_call
        >>>     def my_method(self, arg):
        >>>         ...
    """
    import functools
    import time
    
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        logger = get_logger(method.__module__)
        
        class_name = self.__class__.__name__
        
        # Log method entry
        args_repr = [repr(a) for a in args]
        kwargs_repr = [f"{k}={v!r}" for k, v in kwargs.items()]
        signature = ", ".join(args_repr + kwargs_repr)
        logger.debug(f"Calling {class_name}.{method.__name__}({signature})")
        
        start_time = time.time()
        try:
            result = method(self, *args, **kwargs)
            duration = time.time() - start_time
            logger.debug(f"{class_name}.{method.__name__} completed in {duration:.3f}s")
            return result
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"{class_name}.{method.__name__} failed after {duration:.3f}s: {e}", exc_info=True)
            raise
    
    return wrapper


# Module-level logger instance for convenience
# This allows: from kadas_altair_plugin.logger import logger
logger = get_logger()
