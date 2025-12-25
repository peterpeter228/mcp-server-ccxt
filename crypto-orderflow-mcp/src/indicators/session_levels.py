"""Session High/Low calculator for Tokyo, London, New York sessions."""

from typing import Any
from dataclasses import dataclass

from src.data.storage import DataStorage
from src.config import get_settings, SessionTime
from src.utils import get_logger, timestamp_ms, ms_to_datetime
from src.utils.helpers import get_day_start_ms


@dataclass
class SessionRange:
    """Session time range and levels."""
    name: str
    high: float | None = None
    low: float | None = None
    high_time: int | None = None
    low_time: int | None = None
    volume: float = 0.0
    is_active: bool = False


class SessionLevelsCalculator:
    """Calculate session high/low levels for Tokyo, London, NY."""
    
    def __init__(self, storage: DataStorage):
        self.storage = storage
        self.settings = get_settings()
        self.logger = get_logger("indicators.session_levels")
        
        # In-memory tracking for current day
        self._sessions: dict[str, dict[str, SessionRange]] = {}
    
    def _get_session_for_time(self, timestamp: int) -> list[str]:
        """Determine which session(s) are active at given time.
        
        Args:
            timestamp: Timestamp in milliseconds (UTC)
        
        Returns:
            List of active session names
        """
        dt = ms_to_datetime(timestamp)
        minutes_of_day = dt.hour * 60 + dt.minute
        
        active_sessions = []
        
        # Tokyo session
        tokyo = self.settings.tokyo
        if tokyo.start_minutes <= minutes_of_day < tokyo.end_minutes:
            active_sessions.append("tokyo")
        
        # London session
        london = self.settings.london
        if london.start_minutes <= minutes_of_day < london.end_minutes:
            active_sessions.append("london")
        
        # NY session
        ny = self.settings.ny
        if ny.start_minutes <= minutes_of_day < ny.end_minutes:
            active_sessions.append("ny")
        
        return active_sessions
    
    def _get_or_create_session(self, symbol: str, session_name: str) -> SessionRange:
        """Get or create session range for symbol."""
        symbol = symbol.upper()
        
        if symbol not in self._sessions:
            self._sessions[symbol] = {}
        
        if session_name not in self._sessions[symbol]:
            self._sessions[symbol][session_name] = SessionRange(name=session_name)
        
        return self._sessions[symbol][session_name]
    
    async def update(
        self,
        symbol: str,
        price: float,
        volume: float,
        timestamp: int,
    ) -> None:
        """Update session levels with new trade data.
        
        Args:
            symbol: Trading pair symbol
            price: Trade price
            volume: Trade volume
            timestamp: Trade timestamp in milliseconds
        """
        symbol = symbol.upper()
        date = get_day_start_ms(timestamp)
        active_sessions = self._get_session_for_time(timestamp)
        
        for session_name in active_sessions:
            session = self._get_or_create_session(symbol, session_name)
            session.is_active = True
            session.volume += volume
            
            # Update high
            if session.high is None or price > session.high:
                session.high = price
                session.high_time = timestamp
            
            # Update low
            if session.low is None or price < session.low:
                session.low = price
                session.low_time = timestamp
            
            # Persist to storage
            await self.storage.update_session_levels(
                symbol=symbol,
                date=date,
                session=session_name,
                price=price,
                timestamp=timestamp,
                volume=volume,
            )
        
        # Mark inactive sessions
        for session_name in ["tokyo", "london", "ny"]:
            if session_name not in active_sessions:
                session = self._get_or_create_session(symbol, session_name)
                session.is_active = False
    
    async def get_today_levels(self, symbol: str) -> dict[str, dict[str, Any]]:
        """Get today's session levels from memory.
        
        Args:
            symbol: Trading pair symbol
        
        Returns:
            Dict with session levels
        """
        symbol = symbol.upper()
        
        if symbol not in self._sessions:
            return {}
        
        result = {}
        for session_name, session in self._sessions[symbol].items():
            result[session_name] = {
                "high": session.high,
                "low": session.low,
                "highTime": session.high_time,
                "lowTime": session.low_time,
                "volume": session.volume,
                "isActive": session.is_active,
            }
        
        return result
    
    async def get_yesterday_levels(self, symbol: str) -> dict[str, dict[str, Any]]:
        """Get yesterday's session levels from storage.
        
        Args:
            symbol: Trading pair symbol
        
        Returns:
            Dict with session levels
        """
        symbol = symbol.upper()
        yesterday = get_day_start_ms(timestamp_ms()) - 86_400_000
        
        stored = await self.storage.get_session_levels(symbol, yesterday)
        
        result = {}
        for session_name, data in stored.items():
            result[session_name] = {
                "high": data["high"],
                "low": data["low"],
                "highTime": data["high_time"],
                "lowTime": data["low_time"],
                "volume": data["volume"],
                "isActive": False,
            }
        
        return result
    
    async def get_key_levels(self, symbol: str, date: int | None = None) -> dict[str, Any]:
        """Get all session key levels.
        
        Args:
            symbol: Trading pair symbol
            date: Date to calculate for (defaults to today)
        
        Returns:
            Dict with Tokyo/London/NY high/low levels
        """
        symbol = symbol.upper()
        
        today_levels = await self.get_today_levels(symbol)
        yesterday_levels = await self.get_yesterday_levels(symbol)
        
        # Format response
        result = {
            "symbol": symbol,
            "timestamp": timestamp_ms(),
            "sessions": {
                "timezone": "UTC",
                "tokyo": {
                    "hours": self.settings.tokyo_session,
                },
                "london": {
                    "hours": self.settings.london_session,
                },
                "ny": {
                    "hours": self.settings.ny_session,
                },
            },
            "today": {},
            "yesterday": {},
            "unit": "USDT",
        }
        
        # Add today's levels
        for session_name in ["tokyo", "london", "ny"]:
            if session_name in today_levels:
                data = today_levels[session_name]
                result["today"][f"{session_name}H"] = data["high"]
                result["today"][f"{session_name}L"] = data["low"]
                result["today"][f"{session_name}Volume"] = data["volume"]
                result["today"][f"{session_name}Active"] = data["isActive"]
        
        # Add yesterday's levels
        for session_name in ["tokyo", "london", "ny"]:
            if session_name in yesterday_levels:
                data = yesterday_levels[session_name]
                result["yesterday"][f"{session_name}H"] = data["high"]
                result["yesterday"][f"{session_name}L"] = data["low"]
                result["yesterday"][f"{session_name}Volume"] = data["volume"]
        
        return result
    
    def reset_day(self, symbol: str) -> None:
        """Reset daily session levels (called at day rollover)."""
        symbol = symbol.upper()
        self._sessions[symbol] = {}
        self.logger.info("sessions_reset", symbol=symbol)
    
    def get_current_active_session(self) -> list[str]:
        """Get currently active sessions."""
        return self._get_session_for_time(timestamp_ms())
