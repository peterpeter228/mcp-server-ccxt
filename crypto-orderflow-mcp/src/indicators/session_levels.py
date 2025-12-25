"""
Session high/low level calculator.
Tracks highs and lows for Tokyo, London, and New York trading sessions.
"""

import sys
from pathlib import Path
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.config import Config, SessionConfig
from src.data.trade_aggregator import AggregatedTrade
from src.utils.logging import get_logger
from src.utils.time_utils import (
    get_utc_now_ms,
    get_session_start_end,
    ms_to_datetime,
)

logger = get_logger(__name__)


@dataclass
class SessionLevel:
    """Session high/low data."""
    
    session_name: str
    high: Decimal | None = None
    low: Decimal | None = None
    high_time: int | None = None
    low_time: int | None = None
    start_time: int = 0
    end_time: int = 0
    is_active: bool = False
    trade_count: int = 0
    
    def update(self, price: Decimal, timestamp: int) -> None:
        """Update high/low with new price."""
        if self.high is None or price > self.high:
            self.high = price
            self.high_time = timestamp
        if self.low is None or price < self.low:
            self.low = price
            self.low_time = timestamp
        self.trade_count += 1
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "sessionName": self.session_name,
            "high": str(self.high) if self.high else None,
            "low": str(self.low) if self.low else None,
            "highTime": self.high_time,
            "lowTime": self.low_time,
            "startTime": self.start_time,
            "endTime": self.end_time,
            "isActive": self.is_active,
            "tradeCount": self.trade_count,
        }


@dataclass
class SessionLevelCalculator:
    """Calculator for session high/low levels."""
    
    symbol: str
    sessions: dict[str, SessionConfig] = field(default_factory=dict)
    
    _current_sessions: dict[str, SessionLevel] = field(default_factory=dict, init=False)
    _previous_sessions: dict[str, SessionLevel] = field(default_factory=dict, init=False)
    
    def __post_init__(self) -> None:
        """Initialize default sessions if not provided."""
        if not self.sessions:
            config = Config()
            self.sessions = {
                "tokyo": config.tokyo_session,
                "london": config.london_session,
                "newyork": config.newyork_session,
            }
    
    def _is_in_session(self, timestamp: int, session: SessionConfig) -> bool:
        """Check if timestamp is within session time."""
        dt = ms_to_datetime(timestamp)
        current_time = dt.time()
        
        # SessionConfig can have either start/end (time objects) or start_hour/start_minute etc.
        if hasattr(session, 'start') and isinstance(session.start, time):
            start_time = session.start
            end_time = session.end
        else:
            start_time = time(session.start_hour, session.start_minute)
            end_time = time(session.end_hour, session.end_minute)
        
        if start_time <= end_time:
            return start_time <= current_time < end_time
        else:
            return current_time >= start_time or current_time < end_time
    
    def _get_session_bounds(self, session_name: str, reference_time: int | None = None) -> tuple[int, int]:
        """Get session start/end times for today."""
        session = self.sessions.get(session_name)
        if not session:
            return 0, 0
        
        return get_session_start_end(session, reference_time)
    
    def add_trade(self, trade: AggregatedTrade) -> None:
        """Add a trade to session level tracking."""
        for name, session in self.sessions.items():
            start_ms, end_ms = self._get_session_bounds(name, trade.timestamp)
            
            if start_ms <= trade.timestamp < end_ms:
                if name not in self._current_sessions:
                    self._current_sessions[name] = SessionLevel(
                        session_name=name,
                        start_time=start_ms,
                        end_time=end_ms,
                        is_active=True,
                    )
                
                level = self._current_sessions[name]
                
                if level.start_time != start_ms:
                    if name in self._current_sessions:
                        self._previous_sessions[name] = self._current_sessions[name]
                        self._previous_sessions[name].is_active = False
                    
                    self._current_sessions[name] = SessionLevel(
                        session_name=name,
                        start_time=start_ms,
                        end_time=end_ms,
                        is_active=True,
                    )
                    level = self._current_sessions[name]
                
                level.update(trade.price, trade.timestamp)
    
    def add_trades(self, trades: list[AggregatedTrade]) -> None:
        """Add multiple trades."""
        for trade in trades:
            self.add_trade(trade)
    
    def check_session_status(self) -> None:
        """Update active status of current sessions."""
        now_ms = get_utc_now_ms()
        
        for name, level in self._current_sessions.items():
            session = self.sessions.get(name)
            if session:
                is_active = self._is_in_session(now_ms, session)
                
                if level.is_active and not is_active:
                    self._previous_sessions[name] = level
                    level.is_active = False
                    logger.info(
                        "Session ended",
                        session=name,
                        symbol=self.symbol,
                        high=str(level.high),
                        low=str(level.low),
                    )
    
    def get_current_session(self, session_name: str) -> SessionLevel | None:
        """Get current session level."""
        return self._current_sessions.get(session_name)
    
    def get_previous_session(self, session_name: str) -> SessionLevel | None:
        """Get previous session level."""
        return self._previous_sessions.get(session_name)
    
    def get_all_levels(self) -> dict:
        """Get all session levels."""
        self.check_session_status()
        
        result = {
            "symbol": self.symbol,
            "timestamp": get_utc_now_ms(),
            "sessions": {},
        }
        
        for name in self.sessions.keys():
            current = self._current_sessions.get(name)
            previous = self._previous_sessions.get(name)
            
            session_data = {
                "current": current.to_dict() if current else None,
                "previous": previous.to_dict() if previous else None,
            }
            
            if current:
                result[f"{name}H"] = str(current.high) if current.high else None
                result[f"{name}L"] = str(current.low) if current.low else None
            
            result["sessions"][name] = session_data
        
        return result
    
    def initialize_from_trades(self, trades: list[AggregatedTrade]) -> None:
        """Initialize session levels from historical trades."""
        sorted_trades = sorted(trades, key=lambda t: t.timestamp)
        
        for trade in sorted_trades:
            self.add_trade(trade)
        
        self.check_session_status()
        
        logger.info(
            "Initialized session levels",
            symbol=self.symbol,
            current_sessions=list(self._current_sessions.keys()),
            previous_sessions=list(self._previous_sessions.keys()),
        )
