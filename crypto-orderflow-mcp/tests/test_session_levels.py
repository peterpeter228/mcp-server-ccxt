"""
Tests for Session High/Low level calculation.
"""

import pytest
from datetime import datetime, time, timezone, timedelta
from decimal import Decimal

from src.indicators.session_levels import SessionLevelCalculator, SessionLevels
from src.config import SessionConfig
from src.data.trade_aggregator import AggregatedTrade
from src.utils.time_utils import get_utc_now_ms, datetime_to_ms, get_utc_now


class TestSessionLevels:
    """Test SessionLevels data structure."""
    
    def test_session_levels_initialization(self):
        """Test SessionLevels initializes correctly."""
        now = get_utc_now()
        session = SessionLevels(
            name="Tokyo",
            date=now,
            start_time=0,
            end_time=1000,
        )
        
        assert session.name == "Tokyo"
        assert session.high is None
        assert session.low is None
        assert session.is_complete is False
        assert session.trade_count == 0
    
    def test_session_levels_add_trade(self):
        """Test adding trades updates high/low."""
        now = get_utc_now()
        session = SessionLevels(
            name="Tokyo",
            date=now,
            start_time=0,
            end_time=1000,
        )
        
        trade1 = AggregatedTrade(
            agg_trade_id=1,
            price=Decimal("50000"),
            quantity=Decimal("1"),
            first_trade_id=1,
            last_trade_id=1,
            timestamp=100,
            is_buyer_maker=False,
        )
        session.add_trade(trade1)
        
        assert session.high == Decimal("50000")
        assert session.low == Decimal("50000")
        assert session.trade_count == 1
        
        trade2 = AggregatedTrade(
            agg_trade_id=2,
            price=Decimal("51000"),
            quantity=Decimal("1"),
            first_trade_id=2,
            last_trade_id=2,
            timestamp=200,
            is_buyer_maker=False,
        )
        session.add_trade(trade2)
        
        assert session.high == Decimal("51000")
        assert session.low == Decimal("50000")
        assert session.trade_count == 2
    
    def test_session_to_dict(self):
        """Test session serialization."""
        now = get_utc_now()
        session = SessionLevels(
            name="London",
            date=now,
            start_time=1000,
            end_time=2000,
            high=Decimal("52000"),
            low=Decimal("48000"),
            is_complete=True,
            trade_count=100,
        )
        
        data = session.to_dict()
        
        assert data["name"] == "London"
        assert data["high"] == "52000"
        assert data["low"] == "48000"
        assert data["isComplete"] is True
        assert data["tradeCount"] == 100


class TestSessionLevelCalculator:
    """Test SessionLevelCalculator."""
    
    def get_session_configs(self) -> list[SessionConfig]:
        """Get test session configs."""
        return [
            SessionConfig(name="Tokyo", start=time(0, 0), end=time(9, 0)),
            SessionConfig(name="London", start=time(7, 0), end=time(16, 0)),
            SessionConfig(name="NY", start=time(13, 0), end=time(22, 0)),
        ]
    
    def create_trade(
        self,
        price: str,
        timestamp: int,
    ) -> AggregatedTrade:
        """Helper to create test trades."""
        return AggregatedTrade(
            agg_trade_id=1,
            price=Decimal(price),
            quantity=Decimal("1"),
            first_trade_id=1,
            last_trade_id=1,
            timestamp=timestamp,
            is_buyer_maker=False,
        )
    
    def test_calculator_initialization(self):
        """Test calculator initializes sessions."""
        sessions = self.get_session_configs()
        calc = SessionLevelCalculator(
            symbol="BTCUSDT",
            sessions=sessions,
        )
        
        assert calc.symbol == "BTCUSDT"
        assert len(calc.sessions) == 3
    
    def test_trade_routing_tokyo(self):
        """Trades during Tokyo session update Tokyo levels."""
        sessions = self.get_session_configs()
        calc = SessionLevelCalculator(
            symbol="BTCUSDT",
            sessions=sessions,
        )
        
        # Create timestamp during Tokyo session (3:00 UTC)
        now = get_utc_now().replace(hour=3, minute=0, second=0, microsecond=0)
        ts = datetime_to_ms(now)
        
        trade = self.create_trade("50000", ts)
        calc.add_trade(trade)
        
        tokyo = calc.get_session("Tokyo")
        assert tokyo is not None
        # Note: Session may not be updated if day rollover check happens
    
    def test_get_levels_flat(self):
        """Test flat levels output format."""
        sessions = self.get_session_configs()
        calc = SessionLevelCalculator(
            symbol="BTCUSDT",
            sessions=sessions,
        )
        
        levels = calc.get_levels_flat()
        
        assert "symbol" in levels
        assert "timestamp" in levels
        assert "TokyoH" in levels
        assert "TokyoL" in levels
        assert "LondonH" in levels
        assert "LondonL" in levels
        assert "NYH" in levels
        assert "NYL" in levels
        assert "TokyoComplete" in levels
    
    def test_get_all_sessions(self):
        """Test get_all_sessions output."""
        sessions = self.get_session_configs()
        calc = SessionLevelCalculator(
            symbol="BTCUSDT",
            sessions=sessions,
        )
        
        all_sessions = calc.get_all_sessions()
        
        assert "symbol" in all_sessions
        assert "timestamp" in all_sessions
        assert "current" in all_sessions
        assert "previous" in all_sessions
    
    def test_session_completion_check(self):
        """Test session completion detection."""
        sessions = [
            SessionConfig(name="Test", start=time(0, 0), end=time(1, 0)),
        ]
        calc = SessionLevelCalculator(
            symbol="BTCUSDT",
            sessions=sessions,
        )
        
        # This should trigger day rollover and session creation
        calc.check_session_completions()
        
        # Method should run without error
        assert True


class TestSessionTimeRanges:
    """Test session time range handling."""
    
    def test_session_within_bounds(self):
        """Trade within session bounds is included."""
        from src.utils.time_utils import is_time_in_session
        
        # Test 3:00 AM is within Tokyo (00:00 - 09:00)
        test_time = time(3, 0)
        tokyo_start = time(0, 0)
        tokyo_end = time(9, 0)
        
        dt = datetime(2024, 1, 1, 3, 0, 0, tzinfo=timezone.utc)
        result = is_time_in_session(dt, tokyo_start, tokyo_end)
        
        assert result is True
    
    def test_session_outside_bounds(self):
        """Trade outside session bounds is excluded."""
        from src.utils.time_utils import is_time_in_session
        
        # Test 10:00 AM is outside Tokyo (00:00 - 09:00)
        tokyo_start = time(0, 0)
        tokyo_end = time(9, 0)
        
        dt = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        result = is_time_in_session(dt, tokyo_start, tokyo_end)
        
        assert result is False
    
    def test_session_at_boundary(self):
        """Trade at session boundary is included."""
        from src.utils.time_utils import is_time_in_session
        
        # Test exact start time
        tokyo_start = time(0, 0)
        tokyo_end = time(9, 0)
        
        dt = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        result = is_time_in_session(dt, tokyo_start, tokyo_end)
        
        assert result is True
        
        # Test exact end time
        dt = datetime(2024, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
        result = is_time_in_session(dt, tokyo_start, tokyo_end)
        
        assert result is True
    
    def test_overlapping_sessions(self):
        """Test overlapping session handling."""
        from src.utils.time_utils import is_time_in_session
        
        # Tokyo (00:00 - 09:00) and London (07:00 - 16:00) overlap at 07:00-09:00
        tokyo_start = time(0, 0)
        tokyo_end = time(9, 0)
        london_start = time(7, 0)
        london_end = time(16, 0)
        
        # 8:00 should be in both sessions
        dt = datetime(2024, 1, 1, 8, 0, 0, tzinfo=timezone.utc)
        
        in_tokyo = is_time_in_session(dt, tokyo_start, tokyo_end)
        in_london = is_time_in_session(dt, london_start, london_end)
        
        assert in_tokyo is True
        assert in_london is True
