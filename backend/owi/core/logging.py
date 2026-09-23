"""
Structured logging module for OWI.
Automatically redacts sensitive information such as secrets, auth tokens, and passwords.
"""

import logging
import re
import sys
from pathlib import Path
from owi.config import settings

# Sensitive keys and patterns to redact
SENSITIVE_PATTERNS = [
    re.compile(r'(?i)(token|bearer|password|secret|key|api[_-]?key)[\s:=]+["\']?([a-zA-Z0-9_\-\.]{8,})["\']?'),
]

class RedactingFormatter(logging.Formatter):
    """Log formatter that automatically masks sensitive tokens and secrets."""
    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        for pattern in SENSITIVE_PATTERNS:
            msg = pattern.sub(r'\1: [REDACTED]', msg)
        return msg

def setup_logger(name: str = "owi") -> logging.Logger:
    """Setup and configure a logger instance."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
        
    logger.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)
    
    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    formatter = RedactingFormatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # File Handler
    log_file = settings.DATA_DIR / "logs" / "owi.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    return logger

logger = setup_logger()

def export_diagnostics() -> str:
    """Export recent sanitized logs for system diagnostics."""
    log_file = settings.DATA_DIR / "logs" / "owi.log"
    if not log_file.exists():
        return "No diagnostic log entries recorded yet."
    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
        # Return last 500 lines
        return "".join(lines[-500:])
