"""
Volume Profile calculator.
Calculates POC (Point of Control), VAH (Value Area High), VAL (Value Area Low).
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from src.data.trade_aggregator import AggregatedTrade
from src.utils import (
    get_logger,
    get_utc_now_ms,
    get_day_start_ms,
    get_previous_day_start_ms,
    ms_to_datetime,
)

logger = get_logger(__name__)


@dataclass
class VolumeProfile:
    """Volume profile with POC and Value Area."""
    
    symbol: str
    start_time: int
    end_time: int
    tick_size: Decimal
    value_area_percent: int = 70  # Usually 70%
    
    # Price levels: price -> total volume
    levels: dict[Decimal, Decimal] = field(default_factory=dict)
    
    # Calculated values
    poc: Decimal | None = None
    vah: Decimal | None = None
    val: Decimal | None = None
    
    total_volume: Decimal = Decimal(0)
    trade_count: int = 0
    high: Decimal = Decimal(0)
    low: Decimal = Decimal("999999999")
    
    def _price_to_tick(self, price: Decimal) -> Decimal:
        """Round price to tick size."""
        return (price / self.tick_size).quantize(Decimal("1")) * self.tick_size
    
    def add_trade(self, trade: AggregatedTrade) -> None:
        """
        Add a trade to volume profile.
        
        Args:
            trade: Trade to add
        """
        tick_price = self._price_to_tick(trade.price)
        
        if tick_price not in self.levels:
            self.levels[tick_price] = Decimal(0)
        
        self.levels[tick_price] += trade.quantity
        self.total_volume += trade.quantity
        self.trade_count += 1
        self.high = max(self.high, trade.price)
        self.low = min(self.low, trade.price)
        self.end_time = max(self.end_time, trade.timestamp)
        
        # Invalidate calculated values (will be recalculated on access)
        self.poc = None
        self.vah = None
        self.val = None
    
    def calculate(self) -> None:
        """Calculate POC and Value Area."""
        if not self.levels:
            return
        
        # Find POC (price with highest volume)
        self.poc = max(self.levels.keys(), key=lambda p: self.levels[p])
        
        # Calculate Value Area
        self._calculate_value_area()
    
    def _calculate_value_area(self) -> None:
        """
        Calculate Value Area High and Low.
        
        Value Area contains X% (default 70%) of total volume,
        expanding from POC in both directions.
        """
        if not self.levels or self.poc is None:
            return
        
        target_volume = self.total_volume * Decimal(str(self.value_area_percent / 100))
        
        # Sort price levels
        sorted_prices = sorted(self.levels.keys())
        poc_index = sorted_prices.index(self.poc)
        
        # Start from POC
        value_area_volume = self.levels[self.poc]
        low_index = poc_index
        high_index = poc_index
        
        # Expand outward from POC
        while value_area_volume < target_volume:
            # Calculate volume at next price above and below
            can_go_up = high_index < len(sorted_prices) - 1
            can_go_down = low_index > 0
            
            if not can_go_up and not can_go_down:
                break
            
            # Get volumes for potential expansion
            up_vol = Decimal(0)
            down_vol = Decimal(0)
            
            # Look up to 2 levels in each direction (as per TPO profile methodology)
            if can_go_up:
                for i in range(1, 3):
                    if high_index + i < len(sorted_prices):
                        up_vol += self.levels[sorted_prices[high_index + i]]
            
            if can_go_down:
                for i in range(1, 3):
                    if low_index - i >= 0:
                        down_vol += self.levels[sorted_prices[low_index - i]]
            
            # Expand in direction with more volume
            if up_vol >= down_vol and can_go_up:
                # Expand up
                for i in range(1, 3):
                    if high_index + i < len(sorted_prices):
                        high_index += 1
                        value_area_volume += self.levels[sorted_prices[high_index]]
                        if value_area_volume >= target_volume:
                            break
            elif can_go_down:
                # Expand down
                for i in range(1, 3):
                    if low_index - i >= 0:
                        low_index -= 1
                        value_area_volume += self.levels[sorted_prices[low_index]]
                        if value_area_volume >= target_volume:
                            break
            else:
                break
        
        self.val = sorted_prices[low_index]
        self.vah = sorted_prices[high_index]
    
    def get_poc(self) -> Decimal | None:
        """Get Point of Control (highest volume price)."""
        if self.poc is None:
            self.calculate()
        return self.poc
    
    def get_vah(self) -> Decimal | None:
        """Get Value Area High."""
        if self.vah is None:
            self.calculate()
        return self.vah
    
    def get_val(self) -> Decimal | None:
        """Get Value Area Low."""
        if self.val is None:
            self.calculate()
        return self.val
    
    def to_dict(self, include_levels: bool = False) -> dict:
        """Convert to dictionary."""
        self.calculate()
        
        result = {
            "symbol": self.symbol,
            "startTime": self.start_time,
            "endTime": self.end_time,
            "poc": str(self.poc) if self.poc else None,
            "vah": str(self.vah) if self.vah else None,
            "val": str(self.val) if self.val else None,
            "totalVolume": str(self.total_volume),
            "tradeCount": self.trade_count,
            "high": str(self.high) if self.high < Decimal("999999999") else None,
            "low": str(self.low) if self.low < Decimal("999999999") else None,
            "valueAreaPercent": self.value_area_percent,
        }
        
        if include_levels:
            result["levels"] = {
                str(price): str(vol)
                for price, vol in sorted(self.levels.items(), reverse=True)
            }
        
        return result


@dataclass
class VolumeProfileCalculator:
    """
    Calculator for developing and previous day Volume Profiles.
    """
    
    symbol: str
    tick_size: Decimal = Decimal("0.1")
    value_area_percent: int = 70
    
    _current_day_profile: VolumeProfile | None = field(default=None, init=False)
    _previous_day_profile: VolumeProfile | None = field(default=None, init=False)
    _current_day_start: int = field(default=0, init=False)
    
    def _get_current_day_start(self) -> int:
        """Get start of current UTC day in ms."""
        return get_day_start_ms()
    
    def _check_day_rollover(self) -> None:
        """Check if we've rolled over to a new day."""
        new_day_start = self._get_current_day_start()
        
        if self._current_day_start != new_day_start:
            # Day has changed
            if self._current_day_profile is not None:
                # Move current to previous
                self._previous_day_profile = self._current_day_profile
                logger.info(
                    "Volume profile day rollover",
                    symbol=self.symbol,
                    previous_poc=str(self._previous_day_profile.get_poc()),
                )
            
            # Reset current day
            self._current_day_profile = None
            self._current_day_start = new_day_start
    
    def add_trade(self, trade: AggregatedTrade) -> None:
        """Add a trade to volume profile."""
        self._check_day_rollover()
        
        # Check if trade belongs to current day
        trade_day_start = get_day_start_ms(ms_to_datetime(trade.timestamp))
        if trade_day_start != self._current_day_start:
            return
        
        # Create profile if needed
        if self._current_day_profile is None:
            self._current_day_profile = VolumeProfile(
                symbol=self.symbol,
                start_time=self._current_day_start,
                end_time=trade.timestamp,
                tick_size=self.tick_size,
                value_area_percent=self.value_area_percent,
            )
        
        self._current_day_profile.add_trade(trade)
    
    def add_trades(self, trades: list[AggregatedTrade]) -> None:
        """Add multiple trades."""
        for trade in trades:
            self.add_trade(trade)
    
    def get_current_profile(self) -> VolumeProfile | None:
        """Get current day's developing profile."""
        self._check_day_rollover()
        return self._current_day_profile
    
    def get_previous_profile(self) -> VolumeProfile | None:
        """Get previous day's profile."""
        return self._previous_day_profile
    
    def set_previous_day_profile(self, profile: VolumeProfile) -> None:
        """Set previous day profile (for initialization)."""
        self._previous_day_profile = profile
    
    def initialize_from_trades(
        self,
        current_day_trades: list[AggregatedTrade],
        previous_day_trades: list[AggregatedTrade] | None = None,
    ) -> None:
        """
        Initialize profiles from historical trades.
        """
        # Calculate previous day profile if provided
        if previous_day_trades:
            prev_start = get_previous_day_start_ms()
            prev_profile = VolumeProfile(
                symbol=self.symbol,
                start_time=prev_start,
                end_time=prev_start,
                tick_size=self.tick_size,
                value_area_percent=self.value_area_percent,
            )
            
            for trade in previous_day_trades:
                prev_profile.add_trade(trade)
            
            prev_profile.calculate()
            self._previous_day_profile = prev_profile
            
            logger.info(
                "Initialized previous day volume profile",
                symbol=self.symbol,
                poc=str(prev_profile.get_poc()),
                vah=str(prev_profile.get_vah()),
                val=str(prev_profile.get_val()),
            )
        
        # Initialize current day
        self._current_day_start = self._get_current_day_start()
        for trade in current_day_trades:
            self.add_trade(trade)
        
        if self._current_day_profile:
            self._current_day_profile.calculate()
            logger.info(
                "Initialized current day volume profile",
                symbol=self.symbol,
                poc=str(self._current_day_profile.get_poc()),
                trades=self._current_day_profile.trade_count,
            )
    
    def get_levels(self) -> dict:
        """
        Get all volume profile levels.
        
        Returns:
            Dict with current and previous day POC/VAH/VAL
        """
        result = {
            "symbol": self.symbol,
            "timestamp": get_utc_now_ms(),
        }
        
        current = self._current_day_profile
        if current:
            current.calculate()
            result["dPOC"] = str(current.get_poc()) if current.get_poc() else None
            result["dVAH"] = str(current.get_vah()) if current.get_vah() else None
            result["dVAL"] = str(current.get_val()) if current.get_val() else None
            result["dProfile"] = current.to_dict()
        else:
            result["dPOC"] = None
            result["dVAH"] = None
            result["dVAL"] = None
            result["dProfile"] = None
        
        previous = self._previous_day_profile
        if previous:
            previous.calculate()
            result["pdPOC"] = str(previous.get_poc()) if previous.get_poc() else None
            result["pdVAH"] = str(previous.get_vah()) if previous.get_vah() else None
            result["pdVAL"] = str(previous.get_val()) if previous.get_val() else None
            result["pdProfile"] = previous.to_dict()
        else:
            result["pdPOC"] = None
            result["pdVAH"] = None
            result["pdVAL"] = None
            result["pdProfile"] = None
        
        return result
