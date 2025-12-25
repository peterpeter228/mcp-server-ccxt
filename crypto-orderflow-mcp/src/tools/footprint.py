"""
get_footprint tool implementation.
Returns footprint bars with volume by price level.
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


async def get_footprint(
    symbol: str,
    footprint_calculator: Any,
    timeframe: str = "5m",
    start_time: int | None = None,
    end_time: int | None = None,
    limit: int = 100,
    include_current: bool = True,
) -> dict:
    """
    Get footprint bars.
    
    Args:
        symbol: Trading pair symbol
        footprint_calculator: FootprintCalculator instance
        timeframe: Bar timeframe (1m, 5m, 15m, 30m, 1h)
        start_time: Start timestamp in ms
        end_time: End timestamp in ms
        limit: Maximum number of bars to return
        include_current: Include the developing (incomplete) bar
    
    Returns:
        Footprint bar data with volume by price level
    """
    result = {
        "symbol": symbol,
        "exchange": "binance",
        "marketType": "linear_perpetual",
        "timestamp": get_utc_now_ms(),
        "timeframe": timeframe,
        "requestedLimit": limit,
    }
    
    try:
        bars = footprint_calculator.get_footprint_bars(
            timeframe=timeframe,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )
        
        result["bars"] = bars
        result["barCount"] = len(bars)
        
        if include_current:
            current_bar = footprint_calculator.get_current_bar(timeframe)
            result["currentBar"] = current_bar
        
        summary = footprint_calculator.get_summary(timeframe, limit=min(limit, 20))
        result["summary"] = summary
        
    except Exception as e:
        logger.error(
            "Error getting footprint",
            symbol=symbol,
            timeframe=timeframe,
            error=str(e),
        )
        result.update({
            "bars": [],
            "barCount": 0,
            "currentBar": None,
            "summary": None,
            "error": str(e),
        })
    
    return result
