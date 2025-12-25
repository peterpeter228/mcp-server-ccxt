"""
Footprint calculation module.
Provides footprint bar generation and analysis.
"""

import sys
from pathlib import Path
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.data.trade_aggregator import TradeAggregator, FootprintBar, AggregatedTrade
from src.utils.logging import get_logger
from src.utils.time_utils import get_utc_now_ms

logger = get_logger(__name__)


@dataclass
class FootprintCalculator:
    """Calculator for footprint bars."""
    
    symbol: str
    trade_aggregator: TradeAggregator
    
    def get_footprint_bars(
        self,
        timeframe: str,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Get footprint bars for a timeframe."""
        bars = self.trade_aggregator.get_completed_bars(
            timeframe=timeframe,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )
        
        return [self._bar_to_dict(bar) for bar in bars]
    
    def get_current_bar(self, timeframe: str) -> dict | None:
        """Get the current developing bar."""
        bar = self.trade_aggregator.get_current_bar(timeframe)
        if bar:
            return self._bar_to_dict(bar)
        return None
    
    def _bar_to_dict(self, bar: FootprintBar) -> dict:
        """Convert footprint bar to dictionary."""
        levels = []
        for price, level in sorted(bar.levels.items(), reverse=True):
            levels.append({
                "price": str(price),
                "buyVolume": str(level.buy_volume),
                "sellVolume": str(level.sell_volume),
                "delta": str(level.delta),
                "totalVolume": str(level.total_volume),
                "buyCount": level.buy_count,
                "sellCount": level.sell_count,
            })
        
        return {
            "symbol": self.symbol,
            "timeframe": bar.timeframe,
            "openTime": bar.open_time,
            "closeTime": bar.close_time,
            "open": str(bar.open),
            "high": str(bar.high),
            "low": str(bar.low),
            "close": str(bar.close),
            "buyVolume": str(bar.total_buy_volume),
            "sellVolume": str(bar.total_sell_volume),
            "totalVolume": str(bar.total_volume),
            "delta": str(bar.delta),
            "maxDeltaPrice": str(bar.max_delta_price) if bar.max_delta_price else None,
            "minDeltaPrice": str(bar.min_delta_price) if bar.min_delta_price else None,
            "tradeCount": bar.trade_count,
            "levels": levels,
            "isComplete": True,  # Completed bars from trade aggregator
        }
    
    def get_summary(self, timeframe: str, limit: int = 10) -> dict:
        """Get summary statistics for recent bars."""
        bars = self.trade_aggregator.get_completed_bars(timeframe=timeframe, limit=limit)
        
        if not bars:
            return {
                "symbol": self.symbol,
                "timeframe": timeframe,
                "barCount": 0,
                "avgDelta": "0",
                "avgVolume": "0",
                "totalVolume": "0",
                "maxDelta": "0",
                "minDelta": "0",
            }
        
        total_delta = sum(bar.delta for bar in bars)
        total_volume = sum(bar.total_volume for bar in bars)
        max_delta = max(bar.delta for bar in bars)
        min_delta = min(bar.delta for bar in bars)
        
        return {
            "symbol": self.symbol,
            "timeframe": timeframe,
            "timestamp": get_utc_now_ms(),
            "barCount": len(bars),
            "avgDelta": str(total_delta / len(bars)),
            "avgVolume": str(total_volume / len(bars)),
            "totalVolume": str(total_volume),
            "totalDelta": str(total_delta),
            "maxDelta": str(max_delta),
            "minDelta": str(min_delta),
            "startTime": bars[-1].open_time if bars else None,
            "endTime": bars[0].close_time if bars else None,
        }
