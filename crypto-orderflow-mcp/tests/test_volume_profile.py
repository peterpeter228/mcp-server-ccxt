"""
Tests for Volume Profile calculation (POC, VAH, VAL).
"""

import pytest
from decimal import Decimal

from src.indicators.volume_profile import VolumeProfile, VolumeProfileCalculator
from src.data.trade_aggregator import AggregatedTrade
from src.utils.time_utils import get_utc_now_ms


class TestVolumeProfile:
    """Test Volume Profile calculations."""
    
    def create_trade(
        self,
        price: str,
        quantity: str,
        timestamp: int,
    ) -> AggregatedTrade:
        """Helper to create test trades."""
        return AggregatedTrade(
            agg_trade_id=1,
            price=Decimal(price),
            quantity=Decimal(quantity),
            first_trade_id=1,
            last_trade_id=1,
            timestamp=timestamp,
            is_buyer_maker=False,
        )
    
    def test_poc_single_level(self):
        """POC with single price level."""
        profile = VolumeProfile(
            symbol="BTCUSDT",
            start_time=0,
            end_time=0,
            tick_size=Decimal("0.1"),
        )
        
        now = get_utc_now_ms()
        trade = self.create_trade("50000", "10.0", now)
        profile.add_trade(trade)
        
        poc = profile.get_poc()
        assert poc == Decimal("50000.0")
    
    def test_poc_multiple_levels(self):
        """POC is highest volume level."""
        profile = VolumeProfile(
            symbol="BTCUSDT",
            start_time=0,
            end_time=0,
            tick_size=Decimal("10"),  # Larger tick for testing
        )
        
        now = get_utc_now_ms()
        
        # Level 50000: 5.0 volume
        # Level 50100: 15.0 volume (highest)
        # Level 50200: 8.0 volume
        trades = [
            self.create_trade("50000", "5.0", now),
            self.create_trade("50100", "15.0", now + 1000),
            self.create_trade("50200", "8.0", now + 2000),
        ]
        
        for trade in trades:
            profile.add_trade(trade)
        
        poc = profile.get_poc()
        assert poc == Decimal("50100")
    
    def test_value_area_calculation(self):
        """Value Area contains ~70% of volume."""
        profile = VolumeProfile(
            symbol="BTCUSDT",
            start_time=0,
            end_time=0,
            tick_size=Decimal("100"),
            value_area_percent=70,
        )
        
        now = get_utc_now_ms()
        
        # Create a distribution: more volume in the middle
        trades = [
            self.create_trade("49000", "5.0", now),
            self.create_trade("49500", "10.0", now + 1000),
            self.create_trade("50000", "30.0", now + 2000),  # POC
            self.create_trade("50500", "10.0", now + 3000),
            self.create_trade("51000", "5.0", now + 4000),
        ]
        
        for trade in trades:
            profile.add_trade(trade)
        
        profile.calculate()
        
        poc = profile.get_poc()
        vah = profile.get_vah()
        val = profile.get_val()
        
        assert poc == Decimal("50000")
        assert val is not None
        assert vah is not None
        assert val <= poc <= vah
    
    def test_vah_val_bounds(self):
        """VAH >= VAL always."""
        profile = VolumeProfile(
            symbol="BTCUSDT",
            start_time=0,
            end_time=0,
            tick_size=Decimal("10"),
        )
        
        now = get_utc_now_ms()
        
        # Random distribution
        prices = [49800, 49900, 50000, 50100, 50200, 50000, 50000, 49900, 50100]
        
        for i, price in enumerate(prices):
            trade = self.create_trade(str(price), "1.0", now + i * 1000)
            profile.add_trade(trade)
        
        profile.calculate()
        
        vah = profile.get_vah()
        val = profile.get_val()
        
        assert vah is not None
        assert val is not None
        assert vah >= val
    
    def test_profile_to_dict(self):
        """Test profile serialization."""
        profile = VolumeProfile(
            symbol="BTCUSDT",
            start_time=1000,
            end_time=2000,
            tick_size=Decimal("10"),
        )
        
        now = get_utc_now_ms()
        trade = self.create_trade("50000", "10.0", now)
        profile.add_trade(trade)
        
        data = profile.to_dict()
        
        assert data["symbol"] == "BTCUSDT"
        assert data["poc"] is not None
        assert "totalVolume" in data
        assert "tradeCount" in data
    
    def test_empty_profile(self):
        """Empty profile returns None for levels."""
        profile = VolumeProfile(
            symbol="BTCUSDT",
            start_time=0,
            end_time=0,
            tick_size=Decimal("10"),
        )
        
        profile.calculate()
        
        assert profile.get_poc() is None
        assert profile.get_vah() is None
        assert profile.get_val() is None


class TestVolumeProfileCalculator:
    """Test VolumeProfileCalculator for daily profiles."""
    
    def create_trade(
        self,
        price: str,
        quantity: str,
        timestamp: int,
    ) -> AggregatedTrade:
        return AggregatedTrade(
            agg_trade_id=1,
            price=Decimal(price),
            quantity=Decimal(quantity),
            first_trade_id=1,
            last_trade_id=1,
            timestamp=timestamp,
            is_buyer_maker=False,
        )
    
    def test_calculator_initialization(self):
        """Test calculator initializes correctly."""
        calc = VolumeProfileCalculator(
            symbol="BTCUSDT",
            tick_size=Decimal("0.1"),
            value_area_percent=70,
        )
        
        assert calc.symbol == "BTCUSDT"
        assert calc.tick_size == Decimal("0.1")
        assert calc.value_area_percent == 70
    
    def test_get_levels_format(self):
        """Test get_levels returns correct format."""
        calc = VolumeProfileCalculator(
            symbol="BTCUSDT",
            tick_size=Decimal("10"),
        )
        
        now = get_utc_now_ms()
        trade = self.create_trade("50000", "10.0", now)
        calc.add_trade(trade)
        
        levels = calc.get_levels()
        
        assert "symbol" in levels
        assert "timestamp" in levels
        assert "dPOC" in levels
        assert "dVAH" in levels
        assert "dVAL" in levels
        assert "pdPOC" in levels
        assert levels["symbol"] == "BTCUSDT"


class TestValueAreaAlgorithm:
    """Detailed tests for Value Area algorithm."""
    
    def test_value_area_symmetric(self):
        """Value Area expands symmetrically from POC."""
        profile = VolumeProfile(
            symbol="BTCUSDT",
            start_time=0,
            end_time=0,
            tick_size=Decimal("100"),
            value_area_percent=70,
        )
        
        now = get_utc_now_ms()
        
        # Symmetric distribution around 50000
        # Total volume = 100
        # 70% = 70 volume needed in VA
        distribution = [
            (49600, 5),   # Level 1
            (49700, 10),  # Level 2
            (49800, 15),  # Level 3
            (49900, 20),  # Level 4
            (50000, 30),  # Level 5 (POC)
            (50100, 20),  # Level 6
            (50200, 15),  # Level 7
            (50300, 10),  # Level 8
            (50400, 5),   # Level 9
        ]
        
        for i, (price, vol) in enumerate(distribution):
            trade = AggregatedTrade(
                agg_trade_id=i,
                price=Decimal(str(price)),
                quantity=Decimal(str(vol)),
                first_trade_id=i,
                last_trade_id=i,
                timestamp=now + i * 1000,
                is_buyer_maker=False,
            )
            profile.add_trade(trade)
        
        profile.calculate()
        
        poc = profile.get_poc()
        vah = profile.get_vah()
        val = profile.get_val()
        
        assert poc == Decimal("50000")
        assert vah is not None
        assert val is not None
        
        # Verify VA contains at least 70% of volume
        va_volume = Decimal(0)
        for price, level in profile.levels.items():
            if val <= price <= vah:
                va_volume += level
        
        total_volume = profile.total_volume
        va_percent = (va_volume / total_volume) * 100
        
        # Should be at least 70%
        assert va_percent >= 70
    
    def test_value_area_skewed_distribution(self):
        """Value Area handles skewed distributions."""
        profile = VolumeProfile(
            symbol="BTCUSDT",
            start_time=0,
            end_time=0,
            tick_size=Decimal("100"),
            value_area_percent=70,
        )
        
        now = get_utc_now_ms()
        
        # Skewed distribution (more volume at higher prices)
        distribution = [
            (49500, 5),
            (49600, 5),
            (49700, 10),
            (49800, 10),
            (49900, 15),
            (50000, 20),
            (50100, 25),  # POC
            (50200, 30),
            (50300, 20),
        ]
        
        for i, (price, vol) in enumerate(distribution):
            trade = AggregatedTrade(
                agg_trade_id=i,
                price=Decimal(str(price)),
                quantity=Decimal(str(vol)),
                first_trade_id=i,
                last_trade_id=i,
                timestamp=now + i * 1000,
                is_buyer_maker=False,
            )
            profile.add_trade(trade)
        
        profile.calculate()
        
        poc = profile.get_poc()
        vah = profile.get_vah()
        val = profile.get_val()
        
        # POC should be at highest volume level
        assert poc == Decimal("50200")
        assert vah is not None
        assert val is not None
        assert val <= poc <= vah
