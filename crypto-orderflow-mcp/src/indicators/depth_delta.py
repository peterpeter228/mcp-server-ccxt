"""
Orderbook Depth Delta calculator.
Monitors changes in orderbook depth over time.
"""

import sys
from pathlib import Path
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
import asyncio
from collections import deque

_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.data.orderbook import OrderbookManager
from src.utils.logging import get_logger
from src.utils.time_utils import get_utc_now_ms

logger = get_logger(__name__)


@dataclass
class DepthSnapshot:
    """A snapshot of orderbook depth at a point in time."""
    
    timestamp: int
    mid_price: Decimal
    bid_depth: Decimal
    ask_depth: Decimal
    net_depth: Decimal
    bid_levels: int
    ask_levels: int
    spread: Decimal
    
    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "midPrice": str(self.mid_price),
            "bidDepth": str(self.bid_depth),
            "askDepth": str(self.ask_depth),
            "netDepth": str(self.net_depth),
            "bidLevels": self.bid_levels,
            "askLevels": self.ask_levels,
            "spread": str(self.spread),
        }


@dataclass
class DepthDelta:
    """Change in depth between two snapshots."""
    
    timestamp: int
    delta_bid: Decimal
    delta_ask: Decimal
    delta_net: Decimal
    time_delta_ms: int
    
    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "deltaBid": str(self.delta_bid),
            "deltaAsk": str(self.delta_ask),
            "deltaNet": str(self.delta_net),
            "timeDeltaMs": self.time_delta_ms,
        }


@dataclass
class DepthDeltaCalculator:
    """Calculator for orderbook depth changes."""
    
    symbol: str
    orderbook_manager: OrderbookManager
    percent_range: Decimal = Decimal("1.0")
    snapshot_interval_sec: int = 5
    max_history: int = 1000
    
    _snapshots: deque = field(default_factory=deque, init=False)
    _deltas: deque = field(default_factory=deque, init=False)
    _running: bool = field(default=False, init=False)
    _task: asyncio.Task | None = field(default=None, init=False)
    
    def __post_init__(self):
        self._snapshots = deque(maxlen=self.max_history)
        self._deltas = deque(maxlen=self.max_history)
    
    async def start(self) -> None:
        """Start periodic depth snapshots."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._snapshot_loop())
        logger.info(
            "Depth delta calculator started",
            symbol=self.symbol,
            interval=self.snapshot_interval_sec,
        )
    
    async def stop(self) -> None:
        """Stop depth snapshots."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
    
    async def _snapshot_loop(self) -> None:
        """Background loop to take periodic snapshots."""
        while self._running:
            try:
                await self.take_snapshot()
                await asyncio.sleep(self.snapshot_interval_sec)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error taking depth snapshot", error=str(e))
                await asyncio.sleep(1)
    
    async def take_snapshot(self) -> DepthSnapshot | None:
        """Take a depth snapshot."""
        orderbook = self.orderbook_manager.get_orderbook(self.symbol)
        if not orderbook:
            return None
        
        best_bid = orderbook.get_best_bid()
        best_ask = orderbook.get_best_ask()
        
        if not best_bid or not best_ask:
            return None
        
        mid_price = (best_bid[0] + best_ask[0]) / 2
        
        range_lower = mid_price * (1 - self.percent_range / 100)
        range_upper = mid_price * (1 + self.percent_range / 100)
        
        bid_depth = Decimal(0)
        bid_levels = 0
        for price, qty in orderbook.bids.items():
            if price >= range_lower:
                bid_depth += qty
                bid_levels += 1
        
        ask_depth = Decimal(0)
        ask_levels = 0
        for price, qty in orderbook.asks.items():
            if price <= range_upper:
                ask_depth += qty
                ask_levels += 1
        
        timestamp = get_utc_now_ms()
        spread = best_ask[0] - best_bid[0]
        
        snapshot = DepthSnapshot(
            timestamp=timestamp,
            mid_price=mid_price,
            bid_depth=bid_depth,
            ask_depth=ask_depth,
            net_depth=bid_depth - ask_depth,
            bid_levels=bid_levels,
            ask_levels=ask_levels,
            spread=spread,
        )
        
        if self._snapshots:
            prev = self._snapshots[-1]
            delta = DepthDelta(
                timestamp=timestamp,
                delta_bid=snapshot.bid_depth - prev.bid_depth,
                delta_ask=snapshot.ask_depth - prev.ask_depth,
                delta_net=snapshot.net_depth - prev.net_depth,
                time_delta_ms=timestamp - prev.timestamp,
            )
            self._deltas.append(delta)
        
        self._snapshots.append(snapshot)
        return snapshot
    
    def get_current_depth(self) -> dict | None:
        """Get the most recent depth snapshot."""
        if not self._snapshots:
            return None
        return self._snapshots[-1].to_dict()
    
    def get_depth_history(
        self,
        limit: int = 100,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[dict]:
        """Get historical depth snapshots."""
        result = []
        
        for snapshot in self._snapshots:
            if start_time and snapshot.timestamp < start_time:
                continue
            if end_time and snapshot.timestamp > end_time:
                continue
            result.append(snapshot.to_dict())
            if len(result) >= limit:
                break
        
        return result
    
    def get_delta_history(
        self,
        limit: int = 100,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[dict]:
        """Get historical depth deltas."""
        result = []
        
        for delta in self._deltas:
            if start_time and delta.timestamp < start_time:
                continue
            if end_time and delta.timestamp > end_time:
                continue
            result.append(delta.to_dict())
            if len(result) >= limit:
                break
        
        return result
    
    def get_summary(self, lookback_sec: int = 300) -> dict:
        """Get depth delta summary statistics."""
        now = get_utc_now_ms()
        cutoff = now - (lookback_sec * 1000)
        
        recent_deltas = [d for d in self._deltas if d.timestamp >= cutoff]
        
        if not recent_deltas:
            current = self._snapshots[-1] if self._snapshots else None
            return {
                "symbol": self.symbol,
                "timestamp": now,
                "lookbackSec": lookback_sec,
                "snapshotCount": 0,
                "currentBidDepth": str(current.bid_depth) if current else "0",
                "currentAskDepth": str(current.ask_depth) if current else "0",
                "currentNetDepth": str(current.net_depth) if current else "0",
                "avgDeltaBid": "0",
                "avgDeltaAsk": "0",
                "avgDeltaNet": "0",
                "totalDeltaBid": "0",
                "totalDeltaAsk": "0",
                "totalDeltaNet": "0",
            }
        
        total_bid = sum(d.delta_bid for d in recent_deltas)
        total_ask = sum(d.delta_ask for d in recent_deltas)
        total_net = sum(d.delta_net for d in recent_deltas)
        
        current = self._snapshots[-1] if self._snapshots else None
        
        return {
            "symbol": self.symbol,
            "timestamp": now,
            "percentRange": str(self.percent_range),
            "lookbackSec": lookback_sec,
            "snapshotCount": len(recent_deltas),
            "currentBidDepth": str(current.bid_depth) if current else "0",
            "currentAskDepth": str(current.ask_depth) if current else "0",
            "currentNetDepth": str(current.net_depth) if current else "0",
            "currentSpread": str(current.spread) if current else "0",
            "avgDeltaBid": str(total_bid / len(recent_deltas)),
            "avgDeltaAsk": str(total_ask / len(recent_deltas)),
            "avgDeltaNet": str(total_net / len(recent_deltas)),
            "totalDeltaBid": str(total_bid),
            "totalDeltaAsk": str(total_ask),
            "totalDeltaNet": str(total_net),
        }
