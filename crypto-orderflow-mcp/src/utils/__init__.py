"""Utility modules for Crypto Orderflow MCP Server."""

import sys
from pathlib import Path

_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.utils.logging import get_logger, setup_logging
from src.utils.rate_limiter import RateLimiter
from src.utils.time_utils import (
    ms_to_datetime,
    datetime_to_ms,
    get_utc_now,
    get_utc_now_ms,
    get_day_start_ms,
    get_previous_day_start_ms,
    is_time_in_session,
    get_session_bounds_for_day,
    get_timeframe_ms,
    align_timestamp_to_timeframe,
    get_timeframe_range,
)

__all__ = [
    "get_logger",
    "setup_logging",
    "RateLimiter",
    "ms_to_datetime",
    "datetime_to_ms",
    "get_utc_now",
    "get_utc_now_ms",
    "get_day_start_ms",
    "get_previous_day_start_ms",
    "is_time_in_session",
    "get_session_bounds_for_day",
    "get_timeframe_ms",
    "align_timestamp_to_timeframe",
    "get_timeframe_range",
]
