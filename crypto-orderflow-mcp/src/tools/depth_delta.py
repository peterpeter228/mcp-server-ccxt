"""
get_orderbook_depth_delta tool implementation.
Returns orderbook depth delta within price range.
"""

import sys
from pathlib import Path
from typing import Any

_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.utils.logging import get_logger
from src.utils.time_utils import get_utc_now_ms

logger = get_logger(__name__)


async def get_orderbook_depth_delta(
    symbol: str,
    depth_delta_calculator: Any,
    percent: float = 1.0,
    window_sec: int = 5,
    lookback: int = 60,
) -> dict:
    """
    Get orderbook depth delta data.
    
    Args:
        symbol: Trading pair symbol
        depth_delta_calculator: DepthDeltaCalculator instance
        percent: Price range percent from mid (e.g., 1.0 = ±1%)
        window_sec: Snapshot interval in seconds
        lookback: Number of snapshots to return
    
    Returns:
        Depth delta data showing changes in orderbook over time
    """
    result = {
        "symbol": symbol,
        "exchange": "binance",
        "marketType": "linear_perpetual",
        "timestamp": get_utc_now_ms(),
        "percentRange": percent,
        "windowSec": window_sec,
    }
    
    try:
        current_depth = depth_delta_calculator.get_current_depth()
        result["currentDepth"] = current_depth
        
    except Exception as e:
        logger.error("Error getting current depth", symbol=symbol, error=str(e))
        result["currentDepth"] = None
    
    try:
        history = depth_delta_calculator.get_depth_history(limit=lookback)
        result["depthHistory"] = history
        result["historyCount"] = len(history)
        
    except Exception as e:
        logger.error("Error getting depth history", symbol=symbol, error=str(e))
        result["depthHistory"] = []
        result["historyCount"] = 0
    
    try:
        deltas = depth_delta_calculator.get_delta_history(limit=lookback)
        result["deltaHistory"] = deltas
        result["deltaCount"] = len(deltas)
        
    except Exception as e:
        logger.error("Error getting delta history", symbol=symbol, error=str(e))
        result["deltaHistory"] = []
        result["deltaCount"] = 0
    
    try:
        summary = depth_delta_calculator.get_summary(lookback_sec=lookback * window_sec)
        result["summary"] = summary
        
    except Exception as e:
        logger.error("Error getting depth summary", symbol=symbol, error=str(e))
        result["summary"] = None
    
    return result
