"""

import sys
from pathlib import Path

_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

get_key_levels tool implementation.
Returns VWAP, Volume Profile, and Session levels.
"""

import sys
from pathlib import Path

_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


from datetime import datetime, timezone
from typing import Any

from src.indicators import VWAPCalculator, VolumeProfileCalculator, SessionLevelCalculator
from src.storage import SQLiteStore, DataCache
from src.utils import get_logger, get_utc_now_ms, get_utc_now

logger = get_logger(__name__)


async def get_key_levels(
    symbol: str,
    date: str | None,
    session_tz: str,
    vwap_calc: VWAPCalculator | None,
    vp_calc: VolumeProfileCalculator | None,
    session_calc: SessionLevelCalculator | None,
    store: SQLiteStore,
    cache: DataCache,
) -> dict:
    """
    Get key levels for a symbol.
    
    Returns:
        {
            "timestamp": int,
            "symbol": str,
            "exchange": "binance",
            "marketType": "linear perpetual",
            "date": str,
            "sessionTZ": str,
            "vwap": {...},
            "volumeProfile": {...},
            "sessions": {...}
        }
    """
    # Use today's date if not specified
    if date is None:
        date = get_utc_now().strftime("%Y-%m-%d")
    
    cache_key = f"key_levels:{symbol}:{date}:{session_tz}"
    
    # Try cache (30 second TTL for developing levels)
    cached = await cache.get(cache_key)
    if cached:
        return cached
    
    result = {
        "timestamp": get_utc_now_ms(),
        "symbol": symbol,
        "exchange": "binance",
        "marketType": "linear perpetual",
        "date": date,
        "sessionTZ": session_tz,
    }
    
    # Get VWAP levels
    if vwap_calc:
        vwap_data = vwap_calc.get_levels()
        result["vwap"] = {
            "dVWAP": vwap_data.get("dVWAP"),
            "pdVWAP": vwap_data.get("pdVWAP"),
            "current": vwap_data.get("dVWAPData"),
            "previous": vwap_data.get("pdVWAPData"),
        }
    else:
        result["vwap"] = None
    
    # Get Volume Profile levels
    if vp_calc:
        vp_data = vp_calc.get_levels()
        result["volumeProfile"] = {
            "developing": {
                "POC": vp_data.get("dPOC"),
                "VAH": vp_data.get("dVAH"),
                "VAL": vp_data.get("dVAL"),
                "profile": vp_data.get("dProfile"),
            },
            "previous": {
                "POC": vp_data.get("pdPOC"),
                "VAH": vp_data.get("pdVAH"),
                "VAL": vp_data.get("pdVAL"),
                "profile": vp_data.get("pdProfile"),
            },
        }
    else:
        result["volumeProfile"] = None
    
    # Get Session levels
    if session_calc:
        session_data = session_calc.get_levels_flat()
        result["sessions"] = {
            "Tokyo": {
                "high": session_data.get("TokyoH"),
                "low": session_data.get("TokyoL"),
                "isComplete": session_data.get("TokyoComplete", False),
            },
            "London": {
                "high": session_data.get("LondonH"),
                "low": session_data.get("LondonL"),
                "isComplete": session_data.get("LondonComplete", False),
            },
            "NY": {
                "high": session_data.get("NYH"),
                "low": session_data.get("NYL"),
                "isComplete": session_data.get("NYComplete", False),
            },
            "previousTokyo": {
                "high": session_data.get("pTokyoH"),
                "low": session_data.get("pTokyoL"),
            },
            "previousLondon": {
                "high": session_data.get("pLondonH"),
                "low": session_data.get("pLondonL"),
            },
            "previousNY": {
                "high": session_data.get("pNYH"),
                "low": session_data.get("pNYL"),
            },
        }
    else:
        result["sessions"] = None
    
    # Also try to get from database for historical data
    stored_levels = await store.get_daily_levels(symbol, date)
    if stored_levels:
        result["storedLevels"] = stored_levels
    
    # Cache result
    await cache.set(cache_key, result, ttl=30)
    
    return result
