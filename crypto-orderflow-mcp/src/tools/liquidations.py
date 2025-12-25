"""
stream_liquidations tool implementation.
Returns recent liquidation events.
"""

import sys
from pathlib import Path
from collections import deque
from typing import Any, Deque

_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.utils.logging import get_logger
from src.utils.time_utils import get_utc_now_ms

logger = get_logger(__name__)


class LiquidationCache:
    """Cache for recent liquidation events."""
    
    def __init__(self, max_size: int = 1000):
        self._cache: Deque[dict] = deque(maxlen=max_size)
    
    def add(self, liquidation: dict) -> None:
        """Add a liquidation event to cache."""
        self._cache.append(liquidation)
    
    def get_recent(
        self,
        symbol: str | None = None,
        limit: int = 100,
        side: str | None = None,
    ) -> list[dict]:
        """Get recent liquidations, optionally filtered."""
        result = []
        
        for liq in reversed(self._cache):
            if symbol and liq.get("symbol") != symbol:
                continue
            if side and liq.get("side") != side:
                continue
            result.append(liq)
            if len(result) >= limit:
                break
        
        return result
    
    def size(self) -> int:
        """Get current cache size."""
        return len(self._cache)
    
    def clear(self) -> None:
        """Clear the cache."""
        self._cache.clear()


async def stream_liquidations(
    symbol: str | None,
    liquidation_cache: LiquidationCache,
    sqlite_store: Any,
    limit: int = 100,
    side: str | None = None,
    include_stats: bool = True,
) -> dict:
    """
    Get recent liquidation events.
    
    Args:
        symbol: Trading pair symbol (None for all symbols)
        liquidation_cache: LiquidationCache instance
        sqlite_store: SQLiteStore instance for historical data
        limit: Maximum number of liquidations to return
        side: Filter by side (BUY/SELL)
        include_stats: Include summary statistics
    
    Returns:
        Recent liquidation events with optional statistics
    """
    result = {
        "exchange": "binance",
        "marketType": "linear_perpetual",
        "timestamp": get_utc_now_ms(),
        "symbol": symbol,
        "requestedLimit": limit,
    }
    
    try:
        liquidations = liquidation_cache.get_recent(
            symbol=symbol,
            limit=limit,
            side=side,
        )
        result["liquidations"] = liquidations
        result["count"] = len(liquidations)
        result["cacheSize"] = liquidation_cache.size()
        
    except Exception as e:
        logger.error("Error getting liquidations from cache", error=str(e))
        result["liquidations"] = []
        result["count"] = 0
    
    if include_stats and liquidations:
        try:
            buy_count = sum(1 for l in liquidations if l.get("side") == "BUY")
            sell_count = sum(1 for l in liquidations if l.get("side") == "SELL")
            
            total_buy_qty = sum(
                float(l.get("quantity", 0))
                for l in liquidations if l.get("side") == "BUY"
            )
            total_sell_qty = sum(
                float(l.get("quantity", 0))
                for l in liquidations if l.get("side") == "SELL"
            )
            
            total_buy_value = sum(
                float(l.get("quantity", 0)) * float(l.get("price", 0))
                for l in liquidations if l.get("side") == "BUY"
            )
            total_sell_value = sum(
                float(l.get("quantity", 0)) * float(l.get("price", 0))
                for l in liquidations if l.get("side") == "SELL"
            )
            
            result["statistics"] = {
                "buyCount": buy_count,
                "sellCount": sell_count,
                "totalBuyQuantity": str(total_buy_qty),
                "totalSellQuantity": str(total_sell_qty),
                "totalBuyValue": str(total_buy_value),
                "totalSellValue": str(total_sell_value),
                "netValue": str(total_sell_value - total_buy_value),
                "dominantSide": "SELL" if total_sell_value > total_buy_value else "BUY",
            }
            
            if liquidations:
                result["latestTimestamp"] = liquidations[0].get("timestamp")
                result["oldestTimestamp"] = liquidations[-1].get("timestamp")
                
        except Exception as e:
            logger.error("Error calculating liquidation stats", error=str(e))
            result["statistics"] = None
    
    return result
