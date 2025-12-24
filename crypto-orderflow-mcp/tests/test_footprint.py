"""
Tests for Footprint bar calculation.
"""

import pytest
from decimal import Decimal

from src.data.trade_aggregator import TradeAggregator, FootprintBar, AggregatedTrade
from src.indicators.footprint import FootprintCalculator
from src.utils.time_utils import get_utc_now_ms, align_timestamp_to_timeframe


class TestFootprintBar:
    """Test FootprintBar data structure."""
    
    def create_trade(
        self,
        price: str,
        quantity: str,
        timestamp: int,
        is_buyer_maker: bool = False,
    ) -> AggregatedTrade:
        """Helper to create test trades."""
        return AggregatedTrade(
            agg_trade_id=1,
            price=Decimal(price),
            quantity=Decimal(quantity),
            first_trade_id=1,
            last_trade_id=1,
            timestamp=timestamp,
            is_buyer_maker=is_buyer_maker,
        )
    
    def test_footprint_bar_initialization(self):
        """Test footprint bar initializes correctly."""
        bar = FootprintBar(
            symbol="BTCUSDT",
            timeframe="1m",
            open_time=1000,
            close_time=2000,
            tick_size=Decimal("0.1"),
        )
        
        assert bar.symbol == "BTCUSDT"
        assert bar.timeframe == "1m"
        assert len(bar.levels) == 0
        assert bar.total_buy_volume == Decimal(0)
        assert bar.total_sell_volume == Decimal(0)
    
    def test_add_buy_trade(self):
        """Test adding buy trade updates correctly."""
        bar = FootprintBar(
            symbol="BTCUSDT",
            timeframe="1m",
            open_time=1000,
            close_time=2000,
            tick_size=Decimal("10"),
        )
        
        # Buy trade (is_buyer_maker=False)
        trade = self.create_trade("50000", "1.5", 1500, is_buyer_maker=False)
        bar.add_trade(trade)
        
        assert bar.total_buy_volume == Decimal("1.5")
        assert bar.total_sell_volume == Decimal(0)
        assert bar.delta == Decimal("1.5")
        assert bar.trade_count == 1
    
    def test_add_sell_trade(self):
        """Test adding sell trade updates correctly."""
        bar = FootprintBar(
            symbol="BTCUSDT",
            timeframe="1m",
            open_time=1000,
            close_time=2000,
            tick_size=Decimal("10"),
        )
        
        # Sell trade (is_buyer_maker=True)
        trade = self.create_trade("50000", "2.0", 1500, is_buyer_maker=True)
        bar.add_trade(trade)
        
        assert bar.total_buy_volume == Decimal(0)
        assert bar.total_sell_volume == Decimal("2.0")
        assert bar.delta == Decimal("-2.0")
        assert bar.trade_count == 1
    
    def test_ohlc_tracking(self):
        """Test OHLC values are tracked correctly."""
        bar = FootprintBar(
            symbol="BTCUSDT",
            timeframe="1m",
            open_time=1000,
            close_time=2000,
            tick_size=Decimal("10"),
        )
        
        trades = [
            self.create_trade("50000", "1.0", 1100),  # Open
            self.create_trade("50500", "1.0", 1200),  # High
            self.create_trade("49500", "1.0", 1300),  # Low
            self.create_trade("50200", "1.0", 1400),  # Close
        ]
        
        for trade in trades:
            bar.add_trade(trade)
        
        assert bar.open == Decimal("50000")
        assert bar.high == Decimal("50500")
        assert bar.low == Decimal("49500")
        assert bar.close == Decimal("50200")
    
    def test_price_level_aggregation(self):
        """Test trades aggregate to price levels."""
        bar = FootprintBar(
            symbol="BTCUSDT",
            timeframe="1m",
            open_time=1000,
            close_time=2000,
            tick_size=Decimal("100"),  # 100 tick size
        )
        
        # All trades round to 50000
        trades = [
            self.create_trade("50050", "1.0", 1100, is_buyer_maker=False),  # Buy at ~50000
            self.create_trade("50020", "2.0", 1200, is_buyer_maker=True),   # Sell at ~50000
        ]
        
        for trade in trades:
            bar.add_trade(trade)
        
        assert Decimal("50000") in bar.levels
        level = bar.levels[Decimal("50000")]
        assert level.buy_volume == Decimal("1.0")
        assert level.sell_volume == Decimal("2.0")
    
    def test_delta_calculation(self):
        """Test delta calculation (buy - sell)."""
        bar = FootprintBar(
            symbol="BTCUSDT",
            timeframe="1m",
            open_time=1000,
            close_time=2000,
            tick_size=Decimal("10"),
        )
        
        trades = [
            self.create_trade("50000", "10.0", 1100, is_buyer_maker=False),  # +10 buy
            self.create_trade("50000", "3.0", 1200, is_buyer_maker=True),    # -3 sell
            self.create_trade("50000", "5.0", 1300, is_buyer_maker=False),   # +5 buy
        ]
        
        for trade in trades:
            bar.add_trade(trade)
        
        # Delta = 10 + 5 - 3 = 12
        assert bar.delta == Decimal("12.0")
        assert bar.total_volume == Decimal("18.0")
    
    def test_max_min_delta_price(self):
        """Test max/min delta price detection."""
        bar = FootprintBar(
            symbol="BTCUSDT",
            timeframe="1m",
            open_time=1000,
            close_time=2000,
            tick_size=Decimal("100"),
        )
        
        # Level 50000: +5 delta (all buys)
        bar.add_trade(self.create_trade("50000", "5.0", 1100, is_buyer_maker=False))
        
        # Level 50100: -3 delta (all sells)
        bar.add_trade(self.create_trade("50100", "3.0", 1200, is_buyer_maker=True))
        
        # Level 50200: +10 delta (all buys) - highest delta
        bar.add_trade(self.create_trade("50200", "10.0", 1300, is_buyer_maker=False))
        
        assert bar.max_delta_price == Decimal("50200")
        assert bar.min_delta_price == Decimal("50100")
    
    def test_poc_price(self):
        """Test POC (highest volume level) detection."""
        bar = FootprintBar(
            symbol="BTCUSDT",
            timeframe="1m",
            open_time=1000,
            close_time=2000,
            tick_size=Decimal("100"),
        )
        
        # Level 50000: 5 volume
        bar.add_trade(self.create_trade("50000", "5.0", 1100, is_buyer_maker=False))
        
        # Level 50100: 15 volume (highest)
        bar.add_trade(self.create_trade("50100", "15.0", 1200, is_buyer_maker=False))
        
        # Level 50200: 8 volume
        bar.add_trade(self.create_trade("50200", "8.0", 1300, is_buyer_maker=False))
        
        assert bar.poc_price == Decimal("50100")
    
    def test_to_dict(self):
        """Test footprint bar serialization."""
        bar = FootprintBar(
            symbol="BTCUSDT",
            timeframe="1m",
            open_time=1000,
            close_time=2000,
            tick_size=Decimal("10"),
        )
        
        bar.add_trade(self.create_trade("50000", "1.0", 1100, is_buyer_maker=False))
        
        data = bar.to_dict(include_levels=True)
        
        assert data["symbol"] == "BTCUSDT"
        assert data["timeframe"] == "1m"
        assert data["openTime"] == 1000
        assert "levels" in data
        assert "delta" in data
        assert "totalVolume" in data


class TestImbalanceDetection:
    """Test imbalance detection in footprint bars."""
    
    def create_trade(
        self,
        price: str,
        quantity: str,
        timestamp: int,
        is_buyer_maker: bool,
    ) -> AggregatedTrade:
        return AggregatedTrade(
            agg_trade_id=1,
            price=Decimal(price),
            quantity=Decimal(quantity),
            first_trade_id=1,
            last_trade_id=1,
            timestamp=timestamp,
            is_buyer_maker=is_buyer_maker,
        )
    
    def test_buy_imbalance_detection(self):
        """Test detection of buy-side imbalance."""
        bar = FootprintBar(
            symbol="BTCUSDT",
            timeframe="1m",
            open_time=1000,
            close_time=2000,
            tick_size=Decimal("10"),
        )
        
        # Create 3 consecutive levels with buy imbalance (ratio >= 3)
        # Level 50000: buy=30, sell=5 (ratio=6)
        bar.add_trade(self.create_trade("50000", "30.0", 1100, is_buyer_maker=False))
        bar.add_trade(self.create_trade("50000", "5.0", 1101, is_buyer_maker=True))
        
        # Level 50010: buy=15, sell=3 (ratio=5)
        bar.add_trade(self.create_trade("50010", "15.0", 1200, is_buyer_maker=False))
        bar.add_trade(self.create_trade("50010", "3.0", 1201, is_buyer_maker=True))
        
        # Level 50020: buy=12, sell=2 (ratio=6)
        bar.add_trade(self.create_trade("50020", "12.0", 1300, is_buyer_maker=False))
        bar.add_trade(self.create_trade("50020", "2.0", 1301, is_buyer_maker=True))
        
        imbalances = bar.get_imbalances(ratio_threshold=3.0, consecutive_count=3)
        
        assert "buyImbalances" in imbalances
        assert len(imbalances["buyImbalances"]) > 0
    
    def test_sell_imbalance_detection(self):
        """Test detection of sell-side imbalance."""
        bar = FootprintBar(
            symbol="BTCUSDT",
            timeframe="1m",
            open_time=1000,
            close_time=2000,
            tick_size=Decimal("10"),
        )
        
        # Create 3 consecutive levels with sell imbalance
        # Level 50000: buy=5, sell=30 (ratio=6)
        bar.add_trade(self.create_trade("50000", "5.0", 1100, is_buyer_maker=False))
        bar.add_trade(self.create_trade("50000", "30.0", 1101, is_buyer_maker=True))
        
        # Level 50010: buy=3, sell=15 (ratio=5)
        bar.add_trade(self.create_trade("50010", "3.0", 1200, is_buyer_maker=False))
        bar.add_trade(self.create_trade("50010", "15.0", 1201, is_buyer_maker=True))
        
        # Level 50020: buy=2, sell=12 (ratio=6)
        bar.add_trade(self.create_trade("50020", "2.0", 1300, is_buyer_maker=False))
        bar.add_trade(self.create_trade("50020", "12.0", 1301, is_buyer_maker=True))
        
        imbalances = bar.get_imbalances(ratio_threshold=3.0, consecutive_count=3)
        
        assert "sellImbalances" in imbalances
        assert len(imbalances["sellImbalances"]) > 0
    
    def test_no_imbalance_below_threshold(self):
        """Test no imbalance when ratio below threshold."""
        bar = FootprintBar(
            symbol="BTCUSDT",
            timeframe="1m",
            open_time=1000,
            close_time=2000,
            tick_size=Decimal("10"),
        )
        
        # Balanced levels (ratio close to 1)
        bar.add_trade(self.create_trade("50000", "10.0", 1100, is_buyer_maker=False))
        bar.add_trade(self.create_trade("50000", "10.0", 1101, is_buyer_maker=True))
        
        bar.add_trade(self.create_trade("50010", "8.0", 1200, is_buyer_maker=False))
        bar.add_trade(self.create_trade("50010", "12.0", 1201, is_buyer_maker=True))
        
        imbalances = bar.get_imbalances(ratio_threshold=3.0, consecutive_count=3)
        
        assert len(imbalances["buyImbalances"]) == 0
        assert len(imbalances["sellImbalances"]) == 0


class TestTradeAggregator:
    """Test TradeAggregator for multiple timeframes."""
    
    def create_trade(
        self,
        trade_id: int,
        price: str,
        quantity: str,
        timestamp: int,
        is_buyer_maker: bool = False,
    ) -> AggregatedTrade:
        return AggregatedTrade(
            agg_trade_id=trade_id,
            price=Decimal(price),
            quantity=Decimal(quantity),
            first_trade_id=trade_id,
            last_trade_id=trade_id,
            timestamp=timestamp,
            is_buyer_maker=is_buyer_maker,
        )
    
    def test_aggregator_initialization(self):
        """Test aggregator initializes correctly."""
        agg = TradeAggregator(
            symbol="BTCUSDT",
            timeframes=["1m", "5m"],
            tick_size=Decimal("0.1"),
        )
        
        assert agg.symbol == "BTCUSDT"
        assert "1m" in agg.timeframes
        assert "5m" in agg.timeframes
    
    def test_add_trade_creates_bars(self):
        """Test adding trade creates bars for all timeframes."""
        agg = TradeAggregator(
            symbol="BTCUSDT",
            timeframes=["1m", "5m"],
            tick_size=Decimal("10"),
        )
        
        now = align_timestamp_to_timeframe(get_utc_now_ms(), "1m")
        trade = self.create_trade(1, "50000", "1.0", now + 1000)
        agg.add_trade(trade)
        
        # Should have current bars for both timeframes
        assert agg.get_current_bar("1m") is not None
        assert agg.get_current_bar("5m") is not None
    
    def test_cvd_calculation(self):
        """Test CVD (Cumulative Volume Delta) calculation."""
        agg = TradeAggregator(
            symbol="BTCUSDT",
            timeframes=["1m"],
            tick_size=Decimal("10"),
        )
        
        now = get_utc_now_ms()
        
        # Buy trade: +5
        agg.add_trade(self.create_trade(1, "50000", "5.0", now, is_buyer_maker=False))
        assert agg.cvd == Decimal("5.0")
        
        # Sell trade: -3
        agg.add_trade(self.create_trade(2, "50000", "3.0", now + 1000, is_buyer_maker=True))
        assert agg.cvd == Decimal("2.0")
        
        # Buy trade: +10
        agg.add_trade(self.create_trade(3, "50000", "10.0", now + 2000, is_buyer_maker=False))
        assert agg.cvd == Decimal("12.0")
    
    def test_bar_completion(self):
        """Test bars complete and move to history."""
        agg = TradeAggregator(
            symbol="BTCUSDT",
            timeframes=["1m"],
            tick_size=Decimal("10"),
        )
        
        # Create trade at start of minute
        minute_start = align_timestamp_to_timeframe(get_utc_now_ms(), "1m")
        agg.add_trade(self.create_trade(1, "50000", "1.0", minute_start + 1000))
        
        # Create trade at start of next minute (completes previous bar)
        next_minute = minute_start + 60000
        agg.add_trade(self.create_trade(2, "50000", "1.0", next_minute + 1000))
        
        completed = agg.get_completed_bars("1m")
        assert len(completed) >= 1
    
    def test_get_status(self):
        """Test aggregator status."""
        agg = TradeAggregator(
            symbol="BTCUSDT",
            timeframes=["1m", "5m"],
            tick_size=Decimal("10"),
        )
        
        status = agg.get_status()
        
        assert "symbol" in status
        assert "lastTradeId" in status
        assert "cvd" in status
        assert "timeframes" in status
        assert "1m" in status["timeframes"]
