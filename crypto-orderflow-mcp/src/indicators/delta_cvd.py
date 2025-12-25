"""
Delta and Cumulative Volume Delta (CVD) calculator.
"""

import sys
from pathlib import Path
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from collections import deque

_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.data.trade_aggregator import TradeAggregator, FootprintBar, AggregatedTrade
from src.utils.logging import get_logger
from src.utils.time_utils import get_utc_now_ms

logger = get_logger(__name__)


@dataclass
class DeltaPoint:
    """A single delta data point."""
    timestamp: int
    delta: Decimal
    cvd: Decimal
    buy_volume: Decimal
    sell_volume: Decimal
    
    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "delta": str(self.delta),
            "cvd": str(self.cvd),
            "buyVolume": str(self.buy_volume),
            "sellVolume": str(self.sell_volume),
        }


@dataclass
class DeltaCVDCalculator:
    """Calculator for Delta and Cumulative Volume Delta."""
    
    symbol: str
    trade_aggregator: TradeAggregator
    max_history: int = 10000
    
    _cvd: Decimal = field(default=Decimal(0), init=False)
    _delta_history: deque = field(default_factory=deque, init=False)
    _session_start_cvd: Decimal = field(default=Decimal(0), init=False)
    
    def __post_init__(self):
        self._delta_history = deque(maxlen=self.max_history)
    
    def add_trade(self, trade: AggregatedTrade) -> None:
        """Add a trade and update delta/CVD."""
        delta = trade.quantity if trade.is_buyer_maker else -trade.quantity
        self._cvd += delta
        
        point = DeltaPoint(
            timestamp=trade.timestamp,
            delta=delta,
            cvd=self._cvd,
            buy_volume=trade.quantity if trade.is_buyer_maker else Decimal(0),
            sell_volume=Decimal(0) if trade.is_buyer_maker else trade.quantity,
        )
        self._delta_history.append(point)
    
    def add_trades(self, trades: list[AggregatedTrade]) -> None:
        """Add multiple trades."""
        for trade in trades:
            self.add_trade(trade)
    
    def get_current_cvd(self) -> Decimal:
        """Get current CVD value."""
        return self._cvd
    
    def get_session_cvd(self) -> Decimal:
        """Get CVD since session start."""
        return self._cvd - self._session_start_cvd
    
    def reset_session_cvd(self) -> None:
        """Reset session CVD at session start."""
        self._session_start_cvd = self._cvd
    
    def get_delta_series(
        self,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Get delta series for time range."""
        result = []
        
        for point in self._delta_history:
            if start_time and point.timestamp < start_time:
                continue
            if end_time and point.timestamp > end_time:
                continue
            result.append(point.to_dict())
            if len(result) >= limit:
                break
        
        return result
    
    def get_bar_deltas(
        self,
        timeframe: str,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Get delta data aggregated by bar."""
        bars = self.trade_aggregator.get_completed_bars(
            timeframe=timeframe,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )
        
        result = []
        running_cvd = Decimal(0)
        
        sorted_bars = sorted(bars, key=lambda b: b.open_time)
        
        for bar in sorted_bars:
            running_cvd += bar.delta
            result.append({
                "openTime": bar.open_time,
                "closeTime": bar.close_time,
                "delta": str(bar.delta),
                "cvd": str(running_cvd),
                "buyVolume": str(bar.total_buy_volume),
                "sellVolume": str(bar.total_sell_volume),
                "totalVolume": str(bar.total_volume),
            })
        
        return result
    
    def get_summary(self, timeframe: str = "1m", lookback_bars: int = 60) -> dict:
        """Get CVD summary statistics."""
        bars = self.trade_aggregator.get_completed_bars(
            timeframe=timeframe,
            limit=lookback_bars,
        )
        
        if not bars:
            return {
                "symbol": self.symbol,
                "timestamp": get_utc_now_ms(),
                "currentCVD": str(self._cvd),
                "sessionCVD": str(self.get_session_cvd()),
                "periodDelta": "0",
                "avgDelta": "0",
                "deltaStdDev": "0",
            }
        
        deltas = [bar.delta for bar in bars]
        total_delta = sum(deltas)
        avg_delta = total_delta / len(deltas) if deltas else Decimal(0)
        
        variance = sum((d - avg_delta) ** 2 for d in deltas) / len(deltas) if deltas else Decimal(0)
        std_dev = variance ** Decimal("0.5")
        
        return {
            "symbol": self.symbol,
            "timestamp": get_utc_now_ms(),
            "timeframe": timeframe,
            "lookbackBars": len(bars),
            "currentCVD": str(self._cvd),
            "sessionCVD": str(self.get_session_cvd()),
            "periodDelta": str(total_delta),
            "avgDelta": str(avg_delta),
            "deltaStdDev": str(std_dev),
            "maxDelta": str(max(deltas)) if deltas else "0",
            "minDelta": str(min(deltas)) if deltas else "0",
        }
