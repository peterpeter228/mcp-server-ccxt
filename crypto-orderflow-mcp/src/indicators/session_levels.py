"""
Session high/low level calculator.
Tracks highs and lows for Tokyo, London, and New York trading sessions.
"""

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

from ..config import SessionConfig, get_config
from ..data.trade_aggregator import AggregatedTrade
from ..utils import (
    get_logger,
    get_utc_now,
    get_utc_now_ms,
    ms_to_datetime,
    is_time_in_session,
    get_session_bounds_for_day,
)

logger = get_logger(__name__)


@dataclass
class SessionLevels:
    """High/Low levels for a single session."""
    
    name: str
    date: datetime
    start_time: int  # ms
    end_time: int  # ms
    high: Decimal | None = None
    low: Decimal | None = None
    is_complete: bool = False
    trade_count: int = 0
    
    def add_trade(self, trade: AggregatedTrade) -> None:
        """Update levels with a trade."""
        if self.high is None or trade.price > self.high:
            self.high = trade.price
        if self.low is None or trade.price < self.low:
            self.low = trade.price
        self.trade_count += 1
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "date": self.date.strftime("%Y-%m-%d"),
            "startTime": self.start_time,
            "endTime": self.end_time,
            "high": str(self.high) if self.high else None,
            "low": str(self.low) if self.low else None,
            "isComplete": self.is_complete,
            "tradeCount": self.trade_count,
        }


@dataclass
class SessionLevelCalculator:
    """
    Calculator for session high/low levels.
    
    Tracks Tokyo, London, and New York session highs and lows.
    Sessions are defined by UTC time ranges.
    """
    
    symbol: str
    sessions: list[SessionConfig] = field(default_factory=list)
    
    # Current sessions (today)
    _current_sessions: dict[str, SessionLevels] = field(default_factory=dict)
    # Yesterday's completed sessions
    _previous_sessions: dict[str, SessionLevels] = field(default_factory=dict)
    
    _current_date: datetime | None = field(default=None, init=False)
    
    def __post_init__(self) -> None:
        """Initialize sessions from config if not provided."""
        if not self.sessions:
            self.sessions = get_config().sessions
    
    def _get_current_date(self) -> datetime:
        """Get current UTC date."""
        return get_utc_now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    def _check_day_rollover(self) -> None:
        """Check if we've rolled over to a new day."""
        new_date = self._get_current_date()
        
        if self._current_date != new_date:
            if self._current_date is not None:
                # Move current sessions to previous (mark as complete)
                for name, session in self._current_sessions.items():
                    session.is_complete = True
                    self._previous_sessions[name] = session
            
            # Create new sessions for today
            self._current_sessions.clear()
            for session_config in self.sessions:
                start_ms, end_ms = get_session_bounds_for_day(
                    new_date,
                    session_config.start,
                    session_config.end,
                )
                self._current_sessions[session_config.name] = SessionLevels(
                    name=session_config.name,
                    date=new_date,
                    start_time=start_ms,
                    end_time=end_ms,
                )
            
            self._current_date = new_date
            logger.info(
                "Session levels day rollover",
                symbol=self.symbol,
                date=new_date.strftime("%Y-%m-%d"),
            )
    
    def _is_trade_in_session(
        self,
        trade: AggregatedTrade,
        session_config: SessionConfig,
    ) -> bool:
        """Check if trade falls within a session's time range."""
        trade_dt = ms_to_datetime(trade.timestamp)
        return is_time_in_session(
            trade_dt,
            session_config.start,
            session_config.end,
        )
    
    def add_trade(self, trade: AggregatedTrade) -> None:
        """
        Add a trade and update relevant session levels.
        
        Args:
            trade: Trade to process
        """
        self._check_day_rollover()
        
        trade_dt = ms_to_datetime(trade.timestamp)
        trade_date = trade_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Only process trades from today
        if trade_date != self._current_date:
            return
        
        # Check each session
        for session_config in self.sessions:
            if self._is_trade_in_session(trade, session_config):
                session = self._current_sessions.get(session_config.name)
                if session and not session.is_complete:
                    session.add_trade(trade)
    
    def add_trades(self, trades: list[AggregatedTrade]) -> None:
        """Add multiple trades."""
        for trade in trades:
            self.add_trade(trade)
    
    def check_session_completions(self) -> None:
        """Mark sessions as complete if their time has passed."""
        now_ms = get_utc_now_ms()
        
        for session in self._current_sessions.values():
            if not session.is_complete and now_ms > session.end_time:
                session.is_complete = True
                logger.info(
                    "Session completed",
                    symbol=self.symbol,
                    session=session.name,
                    high=str(session.high),
                    low=str(session.low),
                )
    
    def get_session(self, name: str, previous: bool = False) -> SessionLevels | None:
        """
        Get session levels by name.
        
        Args:
            name: Session name (Tokyo, London, NY)
            previous: If True, get previous day's session
            
        Returns:
            SessionLevels or None
        """
        sessions = self._previous_sessions if previous else self._current_sessions
        return sessions.get(name)
    
    def get_all_sessions(self) -> dict:
        """
        Get all session levels (current and previous).
        
        Returns:
            Dict with current and previous session data
        """
        self._check_day_rollover()
        self.check_session_completions()
        
        result = {
            "symbol": self.symbol,
            "timestamp": get_utc_now_ms(),
            "currentDate": self._current_date.strftime("%Y-%m-%d") if self._current_date else None,
            "current": {},
            "previous": {},
        }
        
        for name, session in self._current_sessions.items():
            result["current"][name] = session.to_dict()
        
        for name, session in self._previous_sessions.items():
            result["previous"][name] = session.to_dict()
        
        return result
    
    def get_levels_flat(self) -> dict:
        """
        Get session levels in a flat format for easy access.
        
        Returns:
            Dict with TokyoH/L, LondonH/L, NYH/L keys
        """
        self._check_day_rollover()
        self.check_session_completions()
        
        result = {
            "symbol": self.symbol,
            "timestamp": get_utc_now_ms(),
        }
        
        # Current sessions
        for name in ["Tokyo", "London", "NY"]:
            session = self._current_sessions.get(name)
            if session:
                result[f"{name}H"] = str(session.high) if session.high else None
                result[f"{name}L"] = str(session.low) if session.low else None
                result[f"{name}Complete"] = session.is_complete
            else:
                result[f"{name}H"] = None
                result[f"{name}L"] = None
                result[f"{name}Complete"] = False
        
        # Previous sessions (prefixed with 'p')
        for name in ["Tokyo", "London", "NY"]:
            session = self._previous_sessions.get(name)
            if session:
                result[f"p{name}H"] = str(session.high) if session.high else None
                result[f"p{name}L"] = str(session.low) if session.low else None
            else:
                result[f"p{name}H"] = None
                result[f"p{name}L"] = None
        
        return result
    
    def initialize_from_trades(
        self,
        current_day_trades: list[AggregatedTrade],
        previous_day_trades: list[AggregatedTrade] | None = None,
    ) -> None:
        """
        Initialize session levels from historical trades.
        
        Args:
            current_day_trades: Today's trades
            previous_day_trades: Yesterday's trades (optional)
        """
        # Initialize current date
        self._current_date = self._get_current_date()
        
        # Create current sessions
        for session_config in self.sessions:
            start_ms, end_ms = get_session_bounds_for_day(
                self._current_date,
                session_config.start,
                session_config.end,
            )
            self._current_sessions[session_config.name] = SessionLevels(
                name=session_config.name,
                date=self._current_date,
                start_time=start_ms,
                end_time=end_ms,
            )
        
        # Process previous day trades
        if previous_day_trades:
            prev_date = self._current_date - timedelta(days=1)
            
            # Create previous sessions
            for session_config in self.sessions:
                start_ms, end_ms = get_session_bounds_for_day(
                    prev_date,
                    session_config.start,
                    session_config.end,
                )
                self._previous_sessions[session_config.name] = SessionLevels(
                    name=session_config.name,
                    date=prev_date,
                    start_time=start_ms,
                    end_time=end_ms,
                    is_complete=True,
                )
            
            # Add trades to previous sessions
            for trade in previous_day_trades:
                trade_dt = ms_to_datetime(trade.timestamp)
                for session_config in self.sessions:
                    if is_time_in_session(trade_dt, session_config.start, session_config.end):
                        session = self._previous_sessions.get(session_config.name)
                        if session:
                            session.add_trade(trade)
            
            logger.info(
                "Initialized previous day session levels",
                symbol=self.symbol,
                sessions={
                    name: {"high": str(s.high), "low": str(s.low)}
                    for name, s in self._previous_sessions.items()
                },
            )
        
        # Process current day trades
        for trade in current_day_trades:
            self.add_trade(trade)
        
        logger.info(
            "Initialized current day session levels",
            symbol=self.symbol,
            sessions={
                name: {"high": str(s.high), "low": str(s.low)}
                for name, s in self._current_sessions.items()
            },
        )
