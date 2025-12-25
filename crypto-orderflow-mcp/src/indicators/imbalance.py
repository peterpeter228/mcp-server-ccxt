"""

import sys
from pathlib import Path

_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

Stacked Imbalance detector.
Identifies areas where buy/sell imbalances stack at consecutive price levels.
"""

import sys
from pathlib import Path

_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from src.data.trade_aggregator import TradeAggregator, FootprintBar
from src.config import get_config
from src.utils import get_logger, get_utc_now_ms

logger = get_logger(__name__)


@dataclass
class ImbalanceLevel:
    """Single imbalance level."""
    price: Decimal
    buy_volume: Decimal
    sell_volume: Decimal
    ratio: float
    side: str  # 'buy' or 'sell'
    
    def to_dict(self) -> dict:
        return {
            "price": str(self.price),
            "buyVolume": str(self.buy_volume),
            "sellVolume": str(self.sell_volume),
            "ratio": self.ratio,
            "side": self.side,
        }


@dataclass
class StackedImbalance:
    """A group of consecutive imbalance levels."""
    levels: list[ImbalanceLevel]
    side: str  # 'buy' or 'sell'
    start_price: Decimal
    end_price: Decimal
    total_imbalance_volume: Decimal
    bar_open_time: int
    bar_close_time: int
    
    def to_dict(self) -> dict:
        return {
            "side": self.side,
            "startPrice": str(self.start_price),
            "endPrice": str(self.end_price),
            "levelCount": len(self.levels),
            "totalImbalanceVolume": str(self.total_imbalance_volume),
            "barOpenTime": self.bar_open_time,
            "barCloseTime": self.bar_close_time,
            "levels": [level.to_dict() for level in self.levels],
        }


@dataclass
class ImbalanceDetector:
    """
    Detector for stacked imbalances in footprint bars.
    
    An imbalance exists when buy/sell ratio >= threshold.
    Stacked imbalances are consecutive price levels with imbalances.
    """
    
    aggregator: TradeAggregator
    ratio_threshold: float = field(default_factory=lambda: get_config().imbalance_ratio_threshold)
    consecutive_count: int = field(default_factory=lambda: get_config().imbalance_consecutive_count)
    
    def detect_imbalances_in_bar(self, bar: FootprintBar) -> list[StackedImbalance]:
        """
        Detect stacked imbalances in a single footprint bar.
        
        Args:
            bar: Footprint bar to analyze
            
        Returns:
            List of detected stacked imbalances
        """
        if not bar.levels:
            return []
        
        sorted_prices = sorted(bar.levels.keys())
        
        buy_stack: list[ImbalanceLevel] = []
        sell_stack: list[ImbalanceLevel] = []
        all_imbalances: list[StackedImbalance] = []
        
        for price in sorted_prices:
            level = bar.levels[price]
            
            # Calculate ratios (avoid division by zero)
            buy_ratio = float('inf')
            sell_ratio = float('inf')
            
            if level.sell_volume > 0:
                buy_ratio = float(level.buy_volume / level.sell_volume)
            if level.buy_volume > 0:
                sell_ratio = float(level.sell_volume / level.buy_volume)
            
            # Check for buy imbalance (buyers dominate)
            is_buy_imbalance = buy_ratio >= self.ratio_threshold and level.buy_volume > 0
            # Check for sell imbalance (sellers dominate)
            is_sell_imbalance = sell_ratio >= self.ratio_threshold and level.sell_volume > 0
            
            # Handle buy stack
            if is_buy_imbalance:
                buy_stack.append(ImbalanceLevel(
                    price=price,
                    buy_volume=level.buy_volume,
                    sell_volume=level.sell_volume,
                    ratio=buy_ratio,
                    side="buy",
                ))
            else:
                # Flush buy stack if meets threshold
                if len(buy_stack) >= self.consecutive_count:
                    all_imbalances.append(self._create_stacked_imbalance(
                        buy_stack, "buy", bar
                    ))
                buy_stack = []
            
            # Handle sell stack
            if is_sell_imbalance:
                sell_stack.append(ImbalanceLevel(
                    price=price,
                    buy_volume=level.buy_volume,
                    sell_volume=level.sell_volume,
                    ratio=sell_ratio,
                    side="sell",
                ))
            else:
                # Flush sell stack if meets threshold
                if len(sell_stack) >= self.consecutive_count:
                    all_imbalances.append(self._create_stacked_imbalance(
                        sell_stack, "sell", bar
                    ))
                sell_stack = []
        
        # Check remaining stacks
        if len(buy_stack) >= self.consecutive_count:
            all_imbalances.append(self._create_stacked_imbalance(
                buy_stack, "buy", bar
            ))
        if len(sell_stack) >= self.consecutive_count:
            all_imbalances.append(self._create_stacked_imbalance(
                sell_stack, "sell", bar
            ))
        
        return all_imbalances
    
    def _create_stacked_imbalance(
        self,
        levels: list[ImbalanceLevel],
        side: str,
        bar: FootprintBar,
    ) -> StackedImbalance:
        """Create a StackedImbalance from a list of levels."""
        if side == "buy":
            total_vol = sum(l.buy_volume - l.sell_volume for l in levels)
        else:
            total_vol = sum(l.sell_volume - l.buy_volume for l in levels)
        
        return StackedImbalance(
            levels=levels.copy(),
            side=side,
            start_price=levels[0].price,
            end_price=levels[-1].price,
            total_imbalance_volume=total_vol,
            bar_open_time=bar.open_time,
            bar_close_time=bar.close_time,
        )
    
    def get_recent_imbalances(
        self,
        timeframe: str,
        lookback: int = 20,
    ) -> list[dict]:
        """
        Get stacked imbalances from recent bars.
        
        Args:
            timeframe: Bar timeframe
            lookback: Number of bars to analyze
            
        Returns:
            List of imbalance dicts
        """
        bars = self.aggregator.get_completed_bars(timeframe, limit=lookback)
        
        all_imbalances = []
        for bar in bars:
            imbalances = self.detect_imbalances_in_bar(bar)
            for imb in imbalances:
                all_imbalances.append(imb.to_dict())
        
        # Include current bar
        current_bar = self.aggregator.get_current_bar(timeframe)
        if current_bar:
            imbalances = self.detect_imbalances_in_bar(current_bar)
            for imb in imbalances:
                imb_dict = imb.to_dict()
                imb_dict["isCurrentBar"] = True
                all_imbalances.append(imb_dict)
        
        return all_imbalances
    
    def get_imbalance_summary(
        self,
        timeframe: str,
        lookback: int = 50,
    ) -> dict:
        """
        Get summary of imbalances for analysis.
        
        Args:
            timeframe: Bar timeframe
            lookback: Number of bars to analyze
            
        Returns:
            Summary statistics
        """
        bars = self.aggregator.get_completed_bars(timeframe, limit=lookback)
        
        buy_imbalances = []
        sell_imbalances = []
        
        for bar in bars:
            imbalances = self.detect_imbalances_in_bar(bar)
            for imb in imbalances:
                if imb.side == "buy":
                    buy_imbalances.append(imb)
                else:
                    sell_imbalances.append(imb)
        
        # Find significant levels (most recent imbalances at similar prices)
        buy_levels = {}
        sell_levels = {}
        
        for imb in buy_imbalances:
            for level in imb.levels:
                price_key = str(level.price)
                if price_key not in buy_levels:
                    buy_levels[price_key] = {
                        "price": str(level.price),
                        "count": 0,
                        "totalVolume": Decimal(0),
                    }
                buy_levels[price_key]["count"] += 1
                buy_levels[price_key]["totalVolume"] += level.buy_volume
        
        for imb in sell_imbalances:
            for level in imb.levels:
                price_key = str(level.price)
                if price_key not in sell_levels:
                    sell_levels[price_key] = {
                        "price": str(level.price),
                        "count": 0,
                        "totalVolume": Decimal(0),
                    }
                sell_levels[price_key]["count"] += 1
                sell_levels[price_key]["totalVolume"] += level.sell_volume
        
        # Sort by count (most significant levels first)
        sorted_buy = sorted(buy_levels.values(), key=lambda x: x["count"], reverse=True)[:10]
        sorted_sell = sorted(sell_levels.values(), key=lambda x: x["count"], reverse=True)[:10]
        
        # Convert volumes to strings
        for level in sorted_buy:
            level["totalVolume"] = str(level["totalVolume"])
        for level in sorted_sell:
            level["totalVolume"] = str(level["totalVolume"])
        
        return {
            "symbol": self.aggregator.symbol,
            "timeframe": timeframe,
            "barsAnalyzed": len(bars),
            "ratioThreshold": self.ratio_threshold,
            "consecutiveCount": self.consecutive_count,
            "totalBuyImbalances": len(buy_imbalances),
            "totalSellImbalances": len(sell_imbalances),
            "significantBuyLevels": sorted_buy,
            "significantSellLevels": sorted_sell,
        }
