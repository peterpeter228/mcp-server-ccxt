"""
Time utility functions for the Crypto Orderflow MCP Server.
All times are handled in UTC unless otherwise specified.
"""

from datetime import datetime, time, timedelta, timezone
from typing import Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from src.config import SessionConfig


def get_utc_now() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


def get_utc_now_ms() -> int:
    """Get current UTC timestamp in milliseconds."""
    return int(get_utc_now().timestamp() * 1000)


def ms_to_datetime(ms: int) -> datetime:
    """Convert milliseconds timestamp to UTC datetime."""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def datetime_to_ms(dt: datetime) -> int:
    """Convert datetime to milliseconds timestamp."""
    return int(dt.timestamp() * 1000)


def get_day_start_ms(dt: datetime | None = None) -> int:
    """
    Get the start of day (00:00:00 UTC) in milliseconds.
    
    Args:
        dt: Datetime to get day start for. If None, uses current UTC time.
        
    Returns:
        Timestamp in milliseconds for start of day.
    """
    if dt is None:
        dt = get_utc_now()
    
    day_start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return datetime_to_ms(day_start)


def get_previous_day_start_ms(dt: datetime | None = None) -> int:
    """
    Get the start of previous day in milliseconds.
    
    Args:
        dt: Reference datetime. If None, uses current UTC time.
        
    Returns:
        Timestamp in milliseconds for start of previous day.
    """
    if dt is None:
        dt = get_utc_now()
    
    previous_day = dt - timedelta(days=1)
    return get_day_start_ms(previous_day)


def get_day_end_ms(dt: datetime | None = None) -> int:
    """
    Get the end of day (23:59:59.999 UTC) in milliseconds.
    
    Args:
        dt: Datetime to get day end for. If None, uses current UTC time.
        
    Returns:
        Timestamp in milliseconds for end of day.
    """
    if dt is None:
        dt = get_utc_now()
    
    day_end = dt.replace(hour=23, minute=59, second=59, microsecond=999999)
    return datetime_to_ms(day_end)


def is_time_in_session(
    dt: datetime,
    session_start: time,
    session_end: time,
) -> bool:
    """
    Check if datetime falls within a session time range.
    
    Handles sessions that cross midnight (e.g., session_start > session_end).
    
    Args:
        dt: Datetime to check.
        session_start: Session start time (UTC).
        session_end: Session end time (UTC).
        
    Returns:
        True if dt is within the session.
    """
    current_time = dt.time()
    
    if session_start <= session_end:
        # Session doesn't cross midnight
        return session_start <= current_time <= session_end
    else:
        # Session crosses midnight
        return current_time >= session_start or current_time <= session_end


def get_session_bounds_for_day(
    date: datetime,
    session_start: time,
    session_end: time,
) -> Tuple[int, int]:
    """
    Get session start and end timestamps for a specific day.
    
    Args:
        date: The date for which to get session bounds.
        session_start: Session start time (UTC).
        session_end: Session end time (UTC).
        
    Returns:
        Tuple of (start_ms, end_ms) timestamps.
    """
    # Session start datetime
    start_dt = date.replace(
        hour=session_start.hour,
        minute=session_start.minute,
        second=0,
        microsecond=0,
    )
    
    # Session end datetime
    end_dt = date.replace(
        hour=session_end.hour,
        minute=session_end.minute,
        second=0,
        microsecond=0,
    )
    
    # If session crosses midnight, end is next day
    if session_end < session_start:
        end_dt = end_dt + timedelta(days=1)
    
    return datetime_to_ms(start_dt), datetime_to_ms(end_dt)


def get_timeframe_ms(timeframe: str) -> int:
    """
    Convert timeframe string to milliseconds.
    
    Args:
        timeframe: Timeframe string (1m, 5m, 15m, 30m, 1h, 4h, 1d)
        
    Returns:
        Timeframe duration in milliseconds.
        
    Raises:
        ValueError: If timeframe is not recognized.
    """
    timeframe_map = {
        "1m": 60 * 1000,
        "3m": 3 * 60 * 1000,
        "5m": 5 * 60 * 1000,
        "15m": 15 * 60 * 1000,
        "30m": 30 * 60 * 1000,
        "1h": 60 * 60 * 1000,
        "2h": 2 * 60 * 60 * 1000,
        "4h": 4 * 60 * 60 * 1000,
        "6h": 6 * 60 * 60 * 1000,
        "8h": 8 * 60 * 60 * 1000,
        "12h": 12 * 60 * 60 * 1000,
        "1d": 24 * 60 * 60 * 1000,
    }
    
    if timeframe not in timeframe_map:
        raise ValueError(f"Unknown timeframe: {timeframe}. Valid: {list(timeframe_map.keys())}")
    
    return timeframe_map[timeframe]


def align_timestamp_to_timeframe(timestamp_ms: int, timeframe: str) -> int:
    """
    Align timestamp to the start of a timeframe period.
    
    Args:
        timestamp_ms: Timestamp in milliseconds.
        timeframe: Timeframe string.
        
    Returns:
        Aligned timestamp in milliseconds.
    """
    timeframe_ms = get_timeframe_ms(timeframe)
    return (timestamp_ms // timeframe_ms) * timeframe_ms


def get_timeframe_range(
    start_ms: int,
    end_ms: int,
    timeframe: str,
) -> list[Tuple[int, int]]:
    """
    Get list of timeframe periods between start and end.
    
    Args:
        start_ms: Start timestamp in milliseconds.
        end_ms: End timestamp in milliseconds.
        timeframe: Timeframe string.
        
    Returns:
        List of (period_start_ms, period_end_ms) tuples.
    """
    timeframe_ms = get_timeframe_ms(timeframe)
    aligned_start = align_timestamp_to_timeframe(start_ms, timeframe)
    
    periods = []
    current = aligned_start
    while current < end_ms:
        period_end = current + timeframe_ms
        periods.append((current, min(period_end, end_ms)))
        current = period_end
    
    return periods


def get_session_start_end(
    session: "SessionConfig",
    reference_time_ms: int | None = None,
) -> Tuple[int, int]:
    """
    Get session start and end timestamps for the session containing the reference time.
    
    Args:
        session: SessionConfig with start/end time objects or start_hour/start_minute etc.
        reference_time_ms: Reference timestamp in ms. If None, uses current UTC time.
        
    Returns:
        Tuple of (start_ms, end_ms) timestamps.
    """
    if reference_time_ms is None:
        ref_dt = get_utc_now()
    else:
        ref_dt = ms_to_datetime(reference_time_ms)
    
    # Handle SessionConfig with start/end time objects or hour/minute attributes
    if hasattr(session, 'start') and isinstance(session.start, time):
        session_start = session.start
        session_end = session.end
        start_hour, start_minute = session_start.hour, session_start.minute
        end_hour, end_minute = session_end.hour, session_end.minute
    else:
        session_start = time(session.start_hour, session.start_minute)
        session_end = time(session.end_hour, session.end_minute)
        start_hour, start_minute = session.start_hour, session.start_minute
        end_hour, end_minute = session.end_hour, session.end_minute
    
    # Get today's session bounds
    today_start_dt = ref_dt.replace(
        hour=start_hour,
        minute=start_minute,
        second=0,
        microsecond=0,
    )
    today_end_dt = ref_dt.replace(
        hour=end_hour,
        minute=end_minute,
        second=0,
        microsecond=0,
    )
    
    # Handle sessions that cross midnight
    if session_end < session_start:
        today_end_dt = today_end_dt + timedelta(days=1)
    
    start_ms = datetime_to_ms(today_start_dt)
    end_ms = datetime_to_ms(today_end_dt)
    
    # If reference time is before today's session, use yesterday's session
    if reference_time_ms is not None and reference_time_ms < start_ms:
        start_ms -= 24 * 60 * 60 * 1000
        end_ms -= 24 * 60 * 60 * 1000
    
    return start_ms, end_ms
