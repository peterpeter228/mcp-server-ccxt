"""
Tests for VWAP calculation.
"""

import pytest
from decimal import Decimal
from datetime import datetime, timezone

from src.indicators.vwap import VWAPCalculator, VWAPData
from src.data.trade_aggregator import AggregatedTrade
from src.utils.time_utils import get_utc_now_ms, get_day_start_ms


class TestVWAPCalculator:
    """Test VWAP calculator."""
    
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
    
    def test_single_trade_vwap(self):
        """VWAP with single trade equals trade price."""
        calc = VWAPCalculator(symbol="BTCUSDT")
        
        now = get_utc_now_ms()
        trade = self.create_trade("50000", "1.0", now)
        calc.add_trade(trade)
        
        vwap_data = calc.get_current_vwap()
        assert vwap_data is not None
        assert vwap_data.vwap == Decimal("50000")
    
    def test_multiple_trades_vwap(self):
        """VWAP calculation with multiple trades."""
        calc = VWAPCalculator(symbol="BTCUSDT")
        
        now = get_utc_now_ms()
        
        # Trade 1: 50000 * 1.0 = 50000
        # Trade 2: 51000 * 2.0 = 102000
        # VWAP = (50000 + 102000) / (1.0 + 2.0) = 152000 / 3.0 = 50666.67
        
        trade1 = self.create_trade("50000", "1.0", now)
        trade2 = self.create_trade("51000", "2.0", now + 1000)
        
        calc.add_trade(trade1)
        calc.add_trade(trade2)
        
        vwap_data = calc.get_current_vwap()
        assert vwap_data is not None
        
        expected_vwap = (Decimal("50000") * Decimal("1.0") + Decimal("51000") * Decimal("2.0")) / Decimal("3.0")
        assert abs(vwap_data.vwap - expected_vwap) < Decimal("0.01")
    
    def test_vwap_high_low_tracking(self):
        """VWAP tracks high and low prices."""
        calc = VWAPCalculator(symbol="BTCUSDT")
        
        now = get_utc_now_ms()
        
        trades = [
            self.create_trade("50000", "1.0", now),
            self.create_trade("52000", "1.0", now + 1000),  # High
            self.create_trade("48000", "1.0", now + 2000),  # Low
            self.create_trade("50500", "1.0", now + 3000),
        ]
        
        for trade in trades:
            calc.add_trade(trade)
        
        vwap_data = calc.get_current_vwap()
        assert vwap_data is not None
        assert vwap_data.high == Decimal("52000")
        assert vwap_data.low == Decimal("48000")
    
    def test_vwap_trade_count(self):
        """VWAP tracks trade count."""
        calc = VWAPCalculator(symbol="BTCUSDT")
        
        now = get_utc_now_ms()
        
        for i in range(5):
            trade = self.create_trade("50000", "1.0", now + i * 1000)
            calc.add_trade(trade)
        
        vwap_data = calc.get_current_vwap()
        assert vwap_data is not None
        assert vwap_data.trade_count == 5
    
    def test_get_levels_format(self):
        """Test get_levels output format."""
        calc = VWAPCalculator(symbol="BTCUSDT")
        
        now = get_utc_now_ms()
        trade = self.create_trade("50000", "1.0", now)
        calc.add_trade(trade)
        
        levels = calc.get_levels()
        
        assert "symbol" in levels
        assert "timestamp" in levels
        assert "dVWAP" in levels
        assert "pdVWAP" in levels
        assert levels["symbol"] == "BTCUSDT"
        assert levels["dVWAP"] == "50000"
    
    def test_previous_day_vwap_initialization(self):
        """Test setting previous day VWAP."""
        calc = VWAPCalculator(symbol="BTCUSDT")
        
        prev_data = VWAPData(
            vwap=Decimal("49500"),
            cumulative_tp_volume=Decimal("495000000"),
            cumulative_volume=Decimal("10000"),
            high=Decimal("51000"),
            low=Decimal("48000"),
            trade_count=1000,
            start_time=get_day_start_ms() - 86400000,
            last_update_time=get_day_start_ms() - 1000,
        )
        
        calc.set_previous_day_data(prev_data)
        
        assert calc.get_previous_vwap() is not None
        assert calc.get_previous_vwap().vwap == Decimal("49500")
    
    def test_empty_calculator(self):
        """Empty calculator returns None."""
        calc = VWAPCalculator(symbol="BTCUSDT")
        
        assert calc.get_current_vwap() is None
        assert calc.get_previous_vwap() is None
        
        levels = calc.get_levels()
        assert levels["dVWAP"] is None
        assert levels["pdVWAP"] is None


class TestVWAPPrecision:
    """Test VWAP precision with various scenarios."""
    
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
    
    def test_large_volume_precision(self):
        """VWAP maintains precision with large volumes."""
        calc = VWAPCalculator(symbol="BTCUSDT")
        
        now = get_utc_now_ms()
        
        # Large volume trades
        trades = [
            self.create_trade("50000.12345678", "1000.12345678", now),
            self.create_trade("50001.87654321", "2000.87654321", now + 1000),
        ]
        
        for trade in trades:
            calc.add_trade(trade)
        
        vwap_data = calc.get_current_vwap()
        assert vwap_data is not None
        
        # Manual calculation
        tp1 = Decimal("50000.12345678") * Decimal("1000.12345678")
        tp2 = Decimal("50001.87654321") * Decimal("2000.87654321")
        total_vol = Decimal("1000.12345678") + Decimal("2000.87654321")
        expected = (tp1 + tp2) / total_vol
        
        # Allow small precision difference
        assert abs(vwap_data.vwap - expected) < Decimal("0.00001")
    
    def test_small_trades_precision(self):
        """VWAP handles small trade sizes."""
        calc = VWAPCalculator(symbol="ETHUSDT")
        
        now = get_utc_now_ms()
        
        trades = [
            self.create_trade("3000.50", "0.001", now),
            self.create_trade("3001.25", "0.002", now + 1000),
        ]
        
        for trade in trades:
            calc.add_trade(trade)
        
        vwap_data = calc.get_current_vwap()
        assert vwap_data is not None
        
        # Verify calculation
        tp1 = Decimal("3000.50") * Decimal("0.001")
        tp2 = Decimal("3001.25") * Decimal("0.002")
        expected = (tp1 + tp2) / Decimal("0.003")
        
        assert abs(vwap_data.vwap - expected) < Decimal("0.01")
