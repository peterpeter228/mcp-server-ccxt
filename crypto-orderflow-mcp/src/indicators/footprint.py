"""

import sys
from pathlib import Path

_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

Footprint calculation module.
Provides footprint bar generation and analysis.
"""

import sys
from pathlib import Path

_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from src.data.trade_aggregator import FootprintBar, TradeAggregator, AggregatedTrade
from src.utils import get_logger, get_utc_now_ms, align_timestamp_to_timeframe, get_timeframe_ms

logger = get_logger(__name__)


@dataclass
class FootprintCalculator:
    """
    Calculator for footprint bars.
    
    Wraps TradeAggregator to provide footprint-specific analysis.
    """
    
    aggregator: TradeAggregator
    
    def get_footprint(
        self,
        timeframe: str,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int | None = None,
        include_levels: bool = True,
    ) -> list[dict]:
        """
        Get footprint bars for a timeframe.
        
        Args:
            timeframe: Bar timeframe (1m, 5m, 15m, 30m, 1h)
            start_time: Start time in ms (optional)
            end_time: End time in ms (optional)
            limit: Max number of bars (optional)
            include_levels: Include price level details
            
        Returns:
            List of footprint bar dicts
        """
        bars = self.aggregator.get_completed_bars(
            timeframe=timeframe,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )
        
        result = [bar.to_dict(include_levels=include_levels) for bar in bars]
        
        # Include current (incomplete) bar if no end_time filter
        if end_time is None:
            current = self.aggregator.get_current_bar(timeframe)
            if current:
                current_dict = current.to_dict(include_levels=include_levels)
                current_dict["isComplete"] = False
                result.append(current_dict)
        
        return result
    
    def get_latest_footprint(
        self,
        timeframe: str,
        include_levels: bool = True,
    ) -> dict | None:
        """
        Get the latest footprint bar (may be incomplete).
        
        Args:
            timeframe: Bar timeframe
            include_levels: Include price level details
            
        Returns:
            Latest footprint bar dict or None
        """
        current = self.aggregator.get_current_bar(timeframe)
        if current:
            result = current.to_dict(include_levels=include_levels)
            result["isComplete"] = False
            return result
        
        # No current bar, get last completed
        bars = self.aggregator.get_completed_bars(timeframe, limit=1)
        if bars:
            result = bars[-1].to_dict(include_levels=include_levels)
            result["isComplete"] = True
            return result
        
        return None
    
    def get_footprint_summary(
        self,
        timeframe: str,
        lookback: int = 20,
    ) -> dict:
        """
        Get summary statistics for recent footprint bars.
        
        Args:
            timeframe: Bar timeframe
            lookback: Number of bars to analyze
            
        Returns:
            Summary statistics
        """
        bars = self.aggregator.get_completed_bars(timeframe, limit=lookback)
        
        if not bars:
            return {
                "symbol": self.aggregator.symbol,
                "timeframe": timeframe,
                "barCount": 0,
                "avgVolume": "0",
                "avgDelta": "0",
                "totalDelta": "0",
                "bullishBars": 0,
                "bearishBars": 0,
            }
        
        total_volume = sum(bar.total_volume for bar in bars)
        total_delta = sum(bar.delta for bar in bars)
        bullish = sum(1 for bar in bars if bar.delta > 0)
        bearish = sum(1 for bar in bars if bar.delta < 0)
        
        return {
            "symbol": self.aggregator.symbol,
            "timeframe": timeframe,
            "barCount": len(bars),
            "avgVolume": str(total_volume / len(bars)),
            "avgDelta": str(total_delta / len(bars)),
            "totalDelta": str(total_delta),
            "bullishBars": bullish,
            "bearishBars": bearish,
            "startTime": bars[0].open_time,
            "endTime": bars[-1].close_time,
        }
    
    def analyze_volume_cluster(
        self,
        timeframe: str,
        lookback: int = 10,
    ) -> dict:
        """
        Analyze volume clusters across recent bars.
        
        Identifies high volume price levels that may act as support/resistance.
        
        Args:
            timeframe: Bar timeframe
            lookback: Number of bars to analyze
            
        Returns:
            Volume cluster analysis
        """
        bars = self.aggregator.get_completed_bars(timeframe, limit=lookback)
        
        if not bars:
            return {
                "symbol": self.aggregator.symbol,
                "timeframe": timeframe,
                "clusters": [],
            }
        
        # Aggregate volume by price level across all bars
        level_volumes: dict[Decimal, Decimal] = {}
        
        for bar in bars:
            for price, level in bar.levels.items():
                if price not in level_volumes:
                    level_volumes[price] = Decimal(0)
                level_volumes[price] += level.total_volume
        
        # Sort by volume and get top levels
        sorted_levels = sorted(
            level_volumes.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:20]
        
        total_vol = sum(v for _, v in level_volumes.items())
        
        clusters = [
            {
                "price": str(price),
                "volume": str(vol),
                "percentOfTotal": str((vol / total_vol * 100).quantize(Decimal("0.01"))),
            }
            for price, vol in sorted_levels
        ]
        
        return {
            "symbol": self.aggregator.symbol,
            "timeframe": timeframe,
            "barCount": len(bars),
            "totalVolume": str(total_vol),
            "clusters": clusters,
        }
