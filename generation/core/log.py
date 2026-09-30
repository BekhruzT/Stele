import datetime
import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor as BaseThreadPoolExecutor
from contextvars import ContextVar, copy_context
from functools import wraps
from typing import Optional

import boto3

# Context variables to store logging context
_lesson_context: ContextVar[Optional[str]] = ContextVar('lesson_id', default=None)
_layer_context: ContextVar[Optional[str]] = ContextVar('layer', default=None)

class CloudWatchHandler(logging.Handler):
    def __init__(self, log_group_name: str, log_stream_name: str):
        super().__init__()
        self.cloudwatch_logs = boto3.client('logs')
        self.log_group_name = log_group_name
        self.log_stream_name = log_stream_name
        self._sequence_tokens = {}  # Store sequence tokens per stream
        self._lock = threading.Lock()
        
        with self._lock:
            # Create log group if it doesn't exist
            try:
                self.cloudwatch_logs.create_log_group(logGroupName=self.log_group_name)
            except self.cloudwatch_logs.exceptions.ResourceAlreadyExistsException:
                pass

            # Create log stream if it doesn't exist
            try:
                self.cloudwatch_logs.create_log_stream(logGroupName=self.log_group_name, logStreamName=self.log_stream_name)
            except self.cloudwatch_logs.exceptions.ResourceAlreadyExistsException:
                pass

            if self.log_stream_name not in self._sequence_tokens:
                self._sequence_tokens[self.log_stream_name] = None

    def emit(self, record):
        if not (self.log_stream_name and self.log_group_name):
            return  # Don't emit if no group or stream is set
        
        # Structure the message
        structured_message = {
            'msg': self.format(record),
            'metadata': {
                'lesson_id': _lesson_context.get(),
                'layer': _layer_context.get(),
                'filepath': f"./{os.path.relpath(record.pathname)}",
                'line_number': record.lineno,
                'function_name': record.funcName,
            }
        }

        timestamp = int(datetime.datetime.now().timestamp() * 1000)
        log_event = {
            'timestamp': timestamp,
            'message': json.dumps(structured_message)
        }

        # Send to CloudWatch
        try:
            kwargs = {
                'logGroupName': self.log_group_name,
                'logStreamName': self.log_stream_name,
                'logEvents': [log_event]
            }
            
            with self._lock:
                if self._sequence_tokens[self.log_stream_name]:
                    kwargs['sequenceToken'] = self._sequence_tokens[self.log_stream_name]
                    
                response = self.cloudwatch_logs.put_log_events(**kwargs)
                self._sequence_tokens[self.log_stream_name] = response['nextSequenceToken']
        except Exception as e:
            print(f"Error sending log to CloudWatch: {str(e)}")

class LoggingContext:
    def __init__(self, lesson_id: Optional[str] = None, layer: Optional[str] = None):
        self.lesson_id = lesson_id
        self.layer = layer
        self.lesson_token = None
        self.layer_token = None

    def __enter__(self):
        if self.lesson_id is not None:
            self.lesson_token = _lesson_context.set(self.lesson_id)
        if self.layer is not None:
            self.layer_token = _layer_context.set(self.layer)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.lesson_token is not None:
            _lesson_context.reset(self.lesson_token)
        if self.layer_token is not None:
            _layer_context.reset(self.layer_token)

class LibraryFilter(logging.Filter):
    def filter(self, record):
        if (record.levelno in [logging.INFO, logging.DEBUG] and ('site-packages' in record.pathname or 'dist-packages' in record.pathname)):
            return False
        return True

def setup_logging(cloudwatch: bool = False, level=logging.INFO, log_stream_name: str = None):
    """
    Initialize the logging system.
    For cloudwatch=True, CLOUDWATCH_LOG_GROUP environment variable must be set.
    """
    # Set up root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Custom formatter that includes file info only for errors
    class ContextualFormatter(logging.Formatter):
        def format(self, record):
            if record.levelno >= logging.ERROR:
                return f'[{record.levelname}|{record.filename}:{record.lineno}] {record.getMessage()}'
            return f'[{record.levelname}] {record.getMessage()}'

    formatter = ContextualFormatter()

    # Remove all existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    if cloudwatch:
        # Get log group from environment
        log_group_name = os.getenv("CLOUDWATCH_LOG_GROUP")
        if not log_group_name:
            print("CLOUDWATCH_LOG_GROUP environment variable not set. Falling back to console logging only.")
        else:
            # Get the caller's filename
            import inspect
            caller_frame = inspect.stack()[1]
            caller_filename = os.path.basename(caller_frame.filename)
            
            # Create log stream name using caller's filename
            log_stream_name = log_stream_name or f"{caller_filename}-{datetime.datetime.now().strftime('%Y-%m-%d_%H-%M')}"
            
            # Create and add CloudWatch handler
            cloudwatch_handler = CloudWatchHandler(log_group_name, log_stream_name)
            cloudwatch_handler.setFormatter(formatter)
            cloudwatch_handler.addFilter(LibraryFilter())
            root_logger.addHandler(cloudwatch_handler)
    
    # Adding console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(LibraryFilter())
    root_logger.addHandler(console_handler)


def with_logging_context(lesson_id: Optional[str] = None, layer: Optional[str] = None):
    """Decorator to set logging context"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            with LoggingContext(lesson_id, layer):
                return func(*args, **kwargs)
        return wrapper
    return decorator


class ContextAwareThreadPoolExecutor(BaseThreadPoolExecutor):
    def __init__(self, *args, **kwargs):
        self.context = copy_context()
        super().__init__(*args, **kwargs, initializer=self._set_child_context)

    def _set_child_context(self):
        for var, value in self.context.items():
            var.set(value)


# Example usage:
