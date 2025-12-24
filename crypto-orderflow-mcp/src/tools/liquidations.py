"""
stream_liquidations tool implementation.
Returns recent liquidation events.
"""

from collections import deque
from typing import Any, Deque

from ..storage import SQLiteStore
from ..utils import get_logger, get_utc_now_ms

logger = get_logger(__name__)


async def stream_liquidations(
    symbol: str,
    limit: int,
    liq_buffer: Deque[dict] | None,
    store: SQLiteStore,
) -> dict:
    """
    Get recent liquidations for a symbol.
    
    Returns:
        {
            "timestamp": int,
            "symbol": str,
            "exchange": "binance",
            "marketType": "linear perpetual",
            "liquidations": [...],
            "summary": {...}
        }
    """
    result = {
        "timestamp": get_utc_now_ms(),
        "symbol": symbol,
        "exchange": "binance",
        "marketType": "linear perpetual",
        "liquidations": [],
    }
    
    # Get from in-memory buffer first
    if liq_buffer:
        recent = list(liq_buffer)[-limit:]
        result["liquidations"] = recent
        result["source"] = "live"
    
    # If not enough data, supplement from database
    if len(result["liquidations"]) < limit:
        stored = await store.get_liquidations(
            symbol=symbol,
            limit=limit - len(result["liquidations"]),
        )
        result["liquidations"].extend(stored)
        if stored:
            result["source"] = "mixed" if result["liquidations"] else "database"
    
    result["count"] = len(result["liquidations"])
    
    # Calculate summary
    if result["liquidations"]:
        buy_liqs = [l for l in result["liquidations"] if l.get("side") == "BUY"]
        sell_liqs = [l for l in result["liquidations"] if l.get("side") == "SELL"]
        
        total_buy_qty = sum(float(l.get("quantity", 0)) for l in buy_liqs)
        total_sell_qty = sum(float(l.get("quantity", 0)) for l in sell_liqs)
        
        result["summary"] = {
            "buyCount": len(buy_liqs),
            "sellCount": len(sell_liqs),
            "totalBuyQuantity": str(total_buy_qty),
            "totalSellQuantity": str(total_sell_qty),
            "netQuantity": str(total_buy_qty - total_sell_qty),
            "dominantSide": "buy" if total_buy_qty > total_sell_qty else "sell",
        }
        
        if result["liquidations"]:
            result["timeRange"] = {
                "oldest": min(l.get("timestamp", 0) for l in result["liquidations"]),
                "newest": max(l.get("timestamp", 0) for l in result["liquidations"]),
            }
    else:
        result["summary"] = {
            "buyCount": 0,
            "sellCount": 0,
            "totalBuyQuantity": "0",
            "totalSellQuantity": "0",
            "netQuantity": "0",
            "dominantSide": "none",
        }
    
    return result
