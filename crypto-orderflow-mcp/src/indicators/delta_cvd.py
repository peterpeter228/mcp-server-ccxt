"""
Delta and Cumulative Volume Delta (CVD) calculator.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from src.data.trade_aggregator import TradeAggregator
from src.utils import get_logger, get_utc_now_ms

logger = get_logger(__name__)


@dataclass
class DeltaCVDCalculator:
    """
    Calculator for Delta and Cumulative Volume Delta.
    
    Delta = Buy Volume - Sell Volume
    CVD = Running sum of Delta
    """
    
    aggregator: TradeAggregator
    
    def get_delta_series(
        self,
        timeframe: str,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """
        Get delta series for a timeframe.
        
        Args:
            timeframe: Bar timeframe
            start_time: Start time filter (ms)
            end_time: End time filter (ms)
            limit: Max number of entries
            
        Returns:
            List of {openTime, delta, buyVolume, sellVolume} dicts
        """
        bars = self.aggregator.get_completed_bars(
            timeframe=timeframe,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )
        
        result = [
            {
                "openTime": bar.open_time,
                "closeTime": bar.close_time,
                "delta": str(bar.delta),
                "buyVolume": str(bar.total_buy_volume),
                "sellVolume": str(bar.total_sell_volume),
                "totalVolume": str(bar.total_volume),
            }
            for bar in bars
        ]
        
        return result
    
    def get_cvd_series(
        self,
        timeframe: str,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int | None = None,
        reset_at_start: bool = True,
    ) -> list[dict]:
        """
        Get CVD series for a timeframe.
        
        Args:
            timeframe: Bar timeframe
            start_time: Start time filter (ms)
            end_time: End time filter (ms)
            limit: Max number of entries
            reset_at_start: If True, CVD starts at 0 at the beginning of the range
            
        Returns:
            List of {openTime, delta, cvd} dicts
        """
        bars = self.aggregator.get_completed_bars(
            timeframe=timeframe,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )
        
        result = []
        cvd = Decimal(0)
        
        for bar in bars:
            cvd += bar.delta
            result.append({
                "openTime": bar.open_time,
                "closeTime": bar.close_time,
                "delta": str(bar.delta),
                "cvd": str(cvd),
            })
        
        return result
    
    def get_current_cvd(self) -> str:
        """Get current CVD value."""
        return str(self.aggregator.cvd)
    
    def get_delta_divergence(
        self,
        timeframe: str,
        lookback: int = 20,
    ) -> dict:
        """
        Analyze delta divergence from price.
        
        Identifies situations where price and CVD are moving in opposite directions,
        which may indicate potential reversals.
        
        Args:
            timeframe: Bar timeframe
            lookback: Number of bars to analyze
            
        Returns:
            Divergence analysis
        """
        bars = self.aggregator.get_completed_bars(timeframe, limit=lookback)
        
        if len(bars) < 5:
            return {
                "symbol": self.aggregator.symbol,
                "timeframe": timeframe,
                "hasDivergence": False,
                "divergenceType": None,
                "message": "Insufficient data",
            }
        
        # Compare first half vs second half
        mid = len(bars) // 2
        first_half = bars[:mid]
        second_half = bars[mid:]
        
        # Price direction
        first_price_avg = sum(bar.close for bar in first_half) / len(first_half)
        second_price_avg = sum(bar.close for bar in second_half) / len(second_half)
        price_rising = second_price_avg > first_price_avg
        
        # CVD direction
        first_cvd = sum(bar.delta for bar in first_half)
        second_cvd = sum(bar.delta for bar in second_half)
        cvd_rising = second_cvd > first_cvd
        
        divergence_type = None
        if price_rising and not cvd_rising:
            divergence_type = "bearish"  # Price up, CVD down
        elif not price_rising and cvd_rising:
            divergence_type = "bullish"  # Price down, CVD up
        
        return {
            "symbol": self.aggregator.symbol,
            "timeframe": timeframe,
            "hasDivergence": divergence_type is not None,
            "divergenceType": divergence_type,
            "priceDirection": "up" if price_rising else "down",
            "cvdDirection": "up" if cvd_rising else "down",
            "firstHalfCVD": str(first_cvd),
            "secondHalfCVD": str(second_cvd),
            "barsAnalyzed": len(bars),
        }
    
    def get_delta_stats(
        self,
        timeframe: str,
        lookback: int = 100,
    ) -> dict:
        """
        Get statistical analysis of delta.
        
        Args:
            timeframe: Bar timeframe
            lookback: Number of bars to analyze
            
        Returns:
            Delta statistics
        """
        bars = self.aggregator.get_completed_bars(timeframe, limit=lookback)
        
        if not bars:
            return {
                "symbol": self.aggregator.symbol,
                "timeframe": timeframe,
                "barCount": 0,
            }
        
        deltas = [bar.delta for bar in bars]
        total_delta = sum(deltas)
        avg_delta = total_delta / len(deltas)
        
        positive_deltas = [d for d in deltas if d > 0]
        negative_deltas = [d for d in deltas if d < 0]
        
        max_delta = max(deltas)
        min_delta = min(deltas)
        
        # Calculate standard deviation
        variance = sum((d - avg_delta) ** 2 for d in deltas) / len(deltas)
        std_delta = variance ** Decimal("0.5")
        
        return {
            "symbol": self.aggregator.symbol,
            "timeframe": timeframe,
            "barCount": len(bars),
            "totalDelta": str(total_delta),
            "avgDelta": str(avg_delta),
            "maxDelta": str(max_delta),
            "minDelta": str(min_delta),
            "stdDelta": str(std_delta),
            "positiveBars": len(positive_deltas),
            "negativeBars": len(negative_deltas),
            "avgPositiveDelta": str(sum(positive_deltas) / len(positive_deltas)) if positive_deltas else "0",
            "avgNegativeDelta": str(sum(negative_deltas) / len(negative_deltas)) if negative_deltas else "0",
        }
