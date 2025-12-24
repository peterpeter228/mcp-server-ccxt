"""
get_orderbook_depth_delta tool implementation.
Returns orderbook depth delta within price range.
"""

from typing import Any

from ..indicators import DepthDeltaCalculator
from ..data import OrderbookManager
from ..utils import get_logger, get_utc_now_ms

logger = get_logger(__name__)


async def get_orderbook_depth_delta(
    symbol: str,
    percent: float,
    window_sec: int,
    lookback: int,
    depth_delta_calc: DepthDeltaCalculator | None,
    orderbook_manager: OrderbookManager | None,
) -> dict:
    """
    Get orderbook depth delta for a symbol.
    
    Returns:
        {
            "timestamp": int,
            "symbol": str,
            "exchange": "binance",
            "marketType": "linear perpetual",
            "percentRange": float,
            "current": {...},
            "history": [...],
            "summary": {...}
        }
    """
    result = {
        "timestamp": get_utc_now_ms(),
        "symbol": symbol,
        "exchange": "binance",
        "marketType": "linear perpetual",
        "percentRange": percent,
        "windowSec": window_sec,
    }
    
    # Get current depth
    if depth_delta_calc:
        current = depth_delta_calc.get_current_depth(symbol)
        result["current"] = current
        
        # Get history
        history = depth_delta_calc.get_depth_history(symbol, lookback)
        result["history"] = history
        
        # Get delta history
        delta_history = depth_delta_calc.get_delta_history(symbol, lookback)
        result["deltaHistory"] = delta_history
        
        # Get summary
        summary = depth_delta_calc.get_depth_delta_summary(symbol, lookback)
        result["summary"] = summary
    else:
        result["current"] = None
        result["history"] = []
        result["deltaHistory"] = []
        result["summary"] = None
    
    # Get current orderbook snapshot
    if orderbook_manager:
        orderbook = orderbook_manager.get_orderbook(symbol)
        if orderbook:
            result["orderbook"] = {
                "isSynced": orderbook.is_synced,
                "lastUpdateId": orderbook.last_update_id,
                "lastUpdateTime": orderbook.last_update_time,
                "bestBid": [str(x) for x in orderbook.get_best_bid()] if orderbook.get_best_bid() else None,
                "bestAsk": [str(x) for x in orderbook.get_best_ask()] if orderbook.get_best_ask() else None,
                "midPrice": str(orderbook.get_mid_price()) if orderbook.get_mid_price() else None,
                "spread": str(orderbook.get_spread()) if orderbook.get_spread() else None,
            }
    
    return result
