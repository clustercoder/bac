import sys
from loguru import logger

logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{module}</cyan> - <level>{message}</level>",
    level="INFO",
    colorize=True,
)
logger.add(
    "logs/agent_{time:YYYY-MM-DD}.log",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {module} - {message}",
    level="DEBUG",
    rotation="1 day",
    retention="7 days",
    compression="zip",
)

__all__ = ["logger"]
