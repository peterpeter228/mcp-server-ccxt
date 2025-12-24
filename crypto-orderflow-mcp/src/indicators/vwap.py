"""
VWAP (Volume Weighted Average Price) calculator.
Calculates developing VWAP (dVWAP) and previous day VWAP (pdVWAP).
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from ..data.trade_aggregator import AggregatedTrade
from ..utils import (
    get_logger,
    get_utc_now_ms,
    get_day_start_ms,
    get_previous_day_start_ms,
    ms_to_datetime,
)

logger = get_logger(__name__)


@dataclass
class VWAPData:
    """VWAP calculation data."""
    vwap: Decimal
    cumulative_tp_volume: Decimal  # Sum of (typical_price * volume)
    cumulative_volume: Decimal
    high: Decimal
    low: Decimal
    trade_count: int
    start_time: int
    last_update_time: int
    
    def to_dict(self) -> dict:
        return {
            "vwap": str(self.vwap),
            "cumulativeTpVolume": str(self.cumulative_tp_volume),
            "cumulativeVolume": str(self.cumulative_volume),
            "high": str(self.high),
            "low": str(self.low),
            "tradeCount": self.trade_count,
            "startTime": self.start_time,
            "lastUpdateTime": self.last_update_time,
        }


@dataclass
class VWAPCalculator:
    """
    Calculator for Volume Weighted Average Price.
    
    VWAP = Cumulative(Typical Price × Volume) / Cumulative(Volume)
    Typical Price = (High + Low + Close) / 3
    
    For trade-level VWAP, we use the trade price as typical price.
    """
    
    symbol: str
    
    _current_day_data: VWAPData | None = field(default=None, init=False)
    _previous_day_data: VWAPData | None = field(default=None, init=False)
    _current_day_start: int = field(default=0, init=False)
    
    def _get_current_day_start(self) -> int:
        """Get start of current UTC day in ms."""
        return get_day_start_ms()
    
    def _check_day_rollover(self) -> None:
        """Check if we've rolled over to a new day."""
        new_day_start = self._get_current_day_start()
        
        if self._current_day_start != new_day_start:
            # Day has changed
            if self._current_day_data is not None:
                # Move current to previous
                self._previous_day_data = self._current_day_data
                logger.info(
                    "VWAP day rollover",
                    symbol=self.symbol,
                    previous_vwap=str(self._previous_day_data.vwap),
                )
            
            # Reset current day
            self._current_day_data = None
            self._current_day_start = new_day_start
    
    def add_trade(self, trade: AggregatedTrade) -> None:
        """
        Add a trade to VWAP calculation.
        
        Args:
            trade: Aggregated trade
        """
        self._check_day_rollover()
        
        # Check if trade belongs to current day
        trade_day_start = get_day_start_ms(ms_to_datetime(trade.timestamp))
        if trade_day_start != self._current_day_start:
            # Trade is from a different day (likely backfill or late arrival)
            logger.debug(
                "Trade from different day",
                symbol=self.symbol,
                trade_time=trade.timestamp,
                current_day_start=self._current_day_start,
            )
            return
        
        # Update current day data
        if self._current_day_data is None:
            self._current_day_data = VWAPData(
                vwap=trade.price,
                cumulative_tp_volume=trade.price * trade.quantity,
                cumulative_volume=trade.quantity,
                high=trade.price,
                low=trade.price,
                trade_count=1,
                start_time=self._current_day_start,
                last_update_time=trade.timestamp,
            )
        else:
            data = self._current_day_data
            data.cumulative_tp_volume += trade.price * trade.quantity
            data.cumulative_volume += trade.quantity
            data.vwap = data.cumulative_tp_volume / data.cumulative_volume
            data.high = max(data.high, trade.price)
            data.low = min(data.low, trade.price)
            data.trade_count += 1
            data.last_update_time = trade.timestamp
    
    def add_trades(self, trades: list[AggregatedTrade]) -> None:
        """Add multiple trades."""
        for trade in trades:
            self.add_trade(trade)
    
    def get_current_vwap(self) -> VWAPData | None:
        """Get current day's developing VWAP."""
        self._check_day_rollover()
        return self._current_day_data
    
    def get_previous_vwap(self) -> VWAPData | None:
        """Get previous day's VWAP."""
        return self._previous_day_data
    
    def set_previous_day_data(self, data: VWAPData) -> None:
        """
        Set previous day VWAP data (for initialization from storage).
        
        Args:
            data: Previous day VWAP data
        """
        self._previous_day_data = data
    
    def initialize_from_trades(
        self,
        current_day_trades: list[AggregatedTrade],
        previous_day_trades: list[AggregatedTrade] | None = None,
    ) -> None:
        """
        Initialize VWAP from historical trades.
        
        Args:
            current_day_trades: Trades for current day
            previous_day_trades: Trades for previous day (optional)
        """
        # Calculate previous day VWAP if provided
        if previous_day_trades:
            prev_start = get_previous_day_start_ms()
            cum_tp_vol = Decimal(0)
            cum_vol = Decimal(0)
            high = Decimal(0)
            low = Decimal("999999999")
            count = 0
            last_time = prev_start
            
            for trade in previous_day_trades:
                cum_tp_vol += trade.price * trade.quantity
                cum_vol += trade.quantity
                high = max(high, trade.price)
                low = min(low, trade.price)
                count += 1
                last_time = trade.timestamp
            
            if cum_vol > 0:
                self._previous_day_data = VWAPData(
                    vwap=cum_tp_vol / cum_vol,
                    cumulative_tp_volume=cum_tp_vol,
                    cumulative_volume=cum_vol,
                    high=high,
                    low=low,
                    trade_count=count,
                    start_time=prev_start,
                    last_update_time=last_time,
                )
                logger.info(
                    "Initialized previous day VWAP",
                    symbol=self.symbol,
                    vwap=str(self._previous_day_data.vwap),
                    trades=count,
                )
        
        # Add current day trades
        self._current_day_start = self._get_current_day_start()
        for trade in current_day_trades:
            self.add_trade(trade)
        
        logger.info(
            "Initialized current day VWAP",
            symbol=self.symbol,
            vwap=str(self._current_day_data.vwap) if self._current_day_data else "N/A",
            trades=self._current_day_data.trade_count if self._current_day_data else 0,
        )
    
    def get_levels(self) -> dict:
        """
        Get all VWAP levels.
        
        Returns:
            Dict with dVWAP and pdVWAP data
        """
        result = {
            "symbol": self.symbol,
            "timestamp": get_utc_now_ms(),
        }
        
        if self._current_day_data:
            result["dVWAP"] = str(self._current_day_data.vwap)
            result["dVWAPData"] = self._current_day_data.to_dict()
        else:
            result["dVWAP"] = None
            result["dVWAPData"] = None
        
        if self._previous_day_data:
            result["pdVWAP"] = str(self._previous_day_data.vwap)
            result["pdVWAPData"] = self._previous_day_data.to_dict()
        else:
            result["pdVWAP"] = None
            result["pdVWAPData"] = None
        
        return result
