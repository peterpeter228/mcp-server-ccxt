"""
get_footprint tool implementation.
Returns footprint bars with volume by price level.
"""

from typing import Any

from src.indicators import FootprintCalculator
from src.storage import SQLiteStore
from src.utils import get_logger, get_utc_now_ms

logger = get_logger(__name__)


async def get_footprint(
    symbol: str,
    timeframe: str,
    start_time: int | None,
    end_time: int | None,
    limit: int,
    fp_calc: FootprintCalculator | None,
    store: SQLiteStore,
) -> dict:
    """
    Get footprint bars for a symbol.
    
    Returns:
        {
            "timestamp": int,
            "symbol": str,
            "exchange": "binance",
            "marketType": "linear perpetual",
            "timeframe": str,
            "bars": [...]
        }
    """
    result = {
        "timestamp": get_utc_now_ms(),
        "symbol": symbol,
        "exchange": "binance",
        "marketType": "linear perpetual",
        "timeframe": timeframe,
        "startTime": start_time,
        "endTime": end_time,
        "bars": [],
    }
    
    # Get from calculator (in-memory data)
    if fp_calc:
        bars = fp_calc.get_footprint(
            timeframe=timeframe,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            include_levels=True,
        )
        result["bars"] = bars
        result["source"] = "live"
    
    # If no data from calculator, try database
    if not result["bars"]:
        stored_bars = await store.get_footprint_bars(
            symbol=symbol,
            timeframe=timeframe,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )
        result["bars"] = stored_bars
        result["source"] = "database"
    
    result["barCount"] = len(result["bars"])
    
    # Add summary statistics
    if result["bars"]:
        total_volume = sum(float(b.get("totalVolume", 0)) for b in result["bars"])
        total_delta = sum(float(b.get("delta", 0)) for b in result["bars"])
        
        result["summary"] = {
            "totalVolume": str(total_volume),
            "totalDelta": str(total_delta),
            "avgVolume": str(total_volume / len(result["bars"])),
            "avgDelta": str(total_delta / len(result["bars"])),
        }
    
    return result
