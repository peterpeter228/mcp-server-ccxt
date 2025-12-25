"""
Orderbook Depth Delta calculator.
Monitors changes in orderbook depth over time.
"""

import asyncio
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Deque

from src.data.orderbook import OrderbookManager
from src.config import get_config
from src.utils import get_logger, get_utc_now_ms

logger = get_logger(__name__)


@dataclass
class DepthSnapshot:
    """Snapshot of orderbook depth at a point in time."""
    timestamp: int
    symbol: str
    percent_range: float
    bid_volume: Decimal
    ask_volume: Decimal
    net: Decimal  # bid - ask
    mid_price: Decimal | None
    
    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "percentRange": self.percent_range,
            "bidVolume": str(self.bid_volume),
            "askVolume": str(self.ask_volume),
            "net": str(self.net),
            "midPrice": str(self.mid_price) if self.mid_price else None,
        }


@dataclass
class DepthDelta:
    """Change in depth between two snapshots."""
    timestamp: int
    symbol: str
    percent_range: float
    bid_delta: Decimal
    ask_delta: Decimal
    net_delta: Decimal
    time_delta_ms: int
    
    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "symbol": self.symbol,
            "percentRange": self.percent_range,
            "bidDelta": str(self.bid_delta),
            "askDelta": str(self.ask_delta),
            "netDelta": str(self.net_delta),
            "timeDeltaMs": self.time_delta_ms,
        }


@dataclass
class DepthDeltaCalculator:
    """
    Calculator for orderbook depth deltas.
    
    Periodically samples orderbook depth within a price range
    and calculates changes over time.
    """
    
    orderbook_manager: OrderbookManager
    percent_range: float = field(default_factory=lambda: get_config().depth_delta_percent)
    sample_interval_sec: int = field(default_factory=lambda: get_config().depth_delta_interval_sec)
    max_history: int = 1000
    
    _snapshots: dict[str, Deque[DepthSnapshot]] = field(default_factory=dict)
    _deltas: dict[str, Deque[DepthDelta]] = field(default_factory=dict)
    _running: bool = False
    _task: asyncio.Task | None = None
    
    async def start(self) -> None:
        """Start periodic depth sampling."""
        if self._running:
            return
        
        self._running = True
        
        # Initialize history for each symbol
        for symbol in self.orderbook_manager.symbols:
            self._snapshots[symbol] = deque(maxlen=self.max_history)
            self._deltas[symbol] = deque(maxlen=self.max_history)
        
        # Start sampling task
        self._task = asyncio.create_task(self._sample_loop())
        logger.info(
            "DepthDeltaCalculator started",
            symbols=self.orderbook_manager.symbols,
            interval=self.sample_interval_sec,
        )
    
    async def stop(self) -> None:
        """Stop periodic sampling."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("DepthDeltaCalculator stopped")
    
    async def _sample_loop(self) -> None:
        """Main sampling loop."""
        while self._running:
            try:
                await self._take_samples()
            except Exception as e:
                logger.error("Depth sampling error", error=str(e))
            
            await asyncio.sleep(self.sample_interval_sec)
    
    async def _take_samples(self) -> None:
        """Take depth snapshots for all symbols."""
        for symbol in self.orderbook_manager.symbols:
            snapshot = self._take_snapshot(symbol)
            if snapshot:
                self._snapshots[symbol].append(snapshot)
                
                # Calculate delta from previous snapshot
                if len(self._snapshots[symbol]) >= 2:
                    prev = self._snapshots[symbol][-2]
                    delta = self._calculate_delta(prev, snapshot)
                    self._deltas[symbol].append(delta)
    
    def _take_snapshot(self, symbol: str) -> DepthSnapshot | None:
        """Take a depth snapshot for a symbol."""
        orderbook = self.orderbook_manager.get_orderbook(symbol)
        if not orderbook or not orderbook.is_synced:
            return None
        
        depth = orderbook.get_depth_at_percent(self.percent_range)
        mid_price = orderbook.get_mid_price()
        
        return DepthSnapshot(
            timestamp=get_utc_now_ms(),
            symbol=symbol,
            percent_range=self.percent_range,
            bid_volume=depth["bid_volume"],
            ask_volume=depth["ask_volume"],
            net=depth["net"],
            mid_price=mid_price,
        )
    
    def _calculate_delta(
        self,
        prev: DepthSnapshot,
        current: DepthSnapshot,
    ) -> DepthDelta:
        """Calculate delta between two snapshots."""
        return DepthDelta(
            timestamp=current.timestamp,
            symbol=current.symbol,
            percent_range=current.percent_range,
            bid_delta=current.bid_volume - prev.bid_volume,
            ask_delta=current.ask_volume - prev.ask_volume,
            net_delta=current.net - prev.net,
            time_delta_ms=current.timestamp - prev.timestamp,
        )
    
    def get_current_depth(self, symbol: str) -> dict | None:
        """
        Get current depth snapshot for a symbol.
        
        Args:
            symbol: Trading pair symbol
            
        Returns:
            Current depth snapshot or None
        """
        snapshot = self._take_snapshot(symbol)
        if snapshot:
            return snapshot.to_dict()
        return None
    
    def get_depth_history(
        self,
        symbol: str,
        lookback: int = 100,
    ) -> list[dict]:
        """
        Get depth snapshot history.
        
        Args:
            symbol: Trading pair symbol
            lookback: Number of snapshots to return
            
        Returns:
            List of depth snapshots
        """
        snapshots = self._snapshots.get(symbol, deque())
        return [s.to_dict() for s in list(snapshots)[-lookback:]]
    
    def get_delta_history(
        self,
        symbol: str,
        lookback: int = 100,
    ) -> list[dict]:
        """
        Get depth delta history.
        
        Args:
            symbol: Trading pair symbol
            lookback: Number of deltas to return
            
        Returns:
            List of depth deltas
        """
        deltas = self._deltas.get(symbol, deque())
        return [d.to_dict() for d in list(deltas)[-lookback:]]
    
    def get_depth_delta_summary(
        self,
        symbol: str,
        lookback: int = 60,
    ) -> dict:
        """
        Get summary of depth delta changes.
        
        Args:
            symbol: Trading pair symbol
            lookback: Number of samples to analyze
            
        Returns:
            Summary statistics
        """
        deltas = list(self._deltas.get(symbol, deque()))[-lookback:]
        
        if not deltas:
            return {
                "symbol": symbol,
                "sampleCount": 0,
                "percentRange": self.percent_range,
            }
        
        total_bid_delta = sum(d.bid_delta for d in deltas)
        total_ask_delta = sum(d.ask_delta for d in deltas)
        total_net_delta = sum(d.net_delta for d in deltas)
        
        # Count positive vs negative net deltas
        positive_net = sum(1 for d in deltas if d.net_delta > 0)
        negative_net = sum(1 for d in deltas if d.net_delta < 0)
        
        # Get latest snapshot for current values
        snapshots = list(self._snapshots.get(symbol, deque()))
        latest = snapshots[-1] if snapshots else None
        
        return {
            "symbol": symbol,
            "percentRange": self.percent_range,
            "sampleCount": len(deltas),
            "timeRangeMs": deltas[-1].timestamp - deltas[0].timestamp if len(deltas) > 1 else 0,
            "totalBidDelta": str(total_bid_delta),
            "totalAskDelta": str(total_ask_delta),
            "totalNetDelta": str(total_net_delta),
            "avgNetDelta": str(total_net_delta / len(deltas)),
            "positiveNetCount": positive_net,
            "negativeNetCount": negative_net,
            "currentBidVolume": str(latest.bid_volume) if latest else None,
            "currentAskVolume": str(latest.ask_volume) if latest else None,
            "currentNet": str(latest.net) if latest else None,
            "trend": "bullish" if total_net_delta > 0 else ("bearish" if total_net_delta < 0 else "neutral"),
        }
    
    def set_percent_range(self, percent: float) -> None:
        """
        Update the percent range for depth calculations.
        
        Args:
            percent: New percent range (e.g., 1.0 for ±1%)
        """
        self.percent_range = percent
        logger.info("Depth percent range updated", percent=percent)
