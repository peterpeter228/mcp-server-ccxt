"""
get_key_levels tool implementation.
Returns VWAP, Volume Profile, and Session levels.
"""

import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.utils.logging import get_logger
from src.utils.time_utils import get_utc_now_ms

logger = get_logger(__name__)


async def get_key_levels(
    symbol: str,
    vwap_calculator: Any,
    volume_profile_calculator: Any,
    session_level_calculator: Any,
    date: str | None = None,
    session_tz: str = "UTC",
) -> dict:
    """
    Get key trading levels.
    
    Args:
        symbol: Trading pair symbol
        vwap_calculator: VWAPCalculator instance
        volume_profile_calculator: VolumeProfileCalculator instance
        session_level_calculator: SessionLevelCalculator instance
        date: Date string (YYYY-MM-DD), defaults to today
        session_tz: Timezone for session calculations
    
    Returns:
        Key levels including VWAP, Volume Profile, and Session H/L
    """
    result = {
        "symbol": symbol,
        "exchange": "binance",
        "marketType": "linear_perpetual",
        "timestamp": get_utc_now_ms(),
        "date": date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "sessionTZ": session_tz,
    }
    
    try:
        vwap_levels = vwap_calculator.get_levels()
        result.update({
            "dVWAP": vwap_levels.get("dVWAP"),
            "pdVWAP": vwap_levels.get("pdVWAP"),
            "vwapData": {
                "developing": vwap_levels.get("dVWAPData"),
                "previousDay": vwap_levels.get("pdVWAPData"),
            },
        })
    except Exception as e:
        logger.error("Error getting VWAP levels", symbol=symbol, error=str(e))
        result.update({"dVWAP": None, "pdVWAP": None, "vwapData": None})
    
    try:
        vp_levels = volume_profile_calculator.get_levels()
        result.update({
            "dPOC": vp_levels.get("dPOC"),
            "dVAH": vp_levels.get("dVAH"),
            "dVAL": vp_levels.get("dVAL"),
            "pdPOC": vp_levels.get("pdPOC"),
            "pdVAH": vp_levels.get("pdVAH"),
            "pdVAL": vp_levels.get("pdVAL"),
            "volumeProfileData": {
                "developing": vp_levels.get("dProfile"),
                "previousDay": vp_levels.get("pdProfile"),
            },
        })
    except Exception as e:
        logger.error("Error getting Volume Profile levels", symbol=symbol, error=str(e))
        result.update({
            "dPOC": None, "dVAH": None, "dVAL": None,
            "pdPOC": None, "pdVAH": None, "pdVAL": None,
            "volumeProfileData": None,
        })
    
    try:
        session_levels = session_level_calculator.get_all_levels()
        
        result.update({
            "tokyoH": session_levels.get("tokyoH"),
            "tokyoL": session_levels.get("tokyoL"),
            "londonH": session_levels.get("londonH"),
            "londonL": session_levels.get("londonL"),
            "newyorkH": session_levels.get("newyorkH"),
            "newyorkL": session_levels.get("newyorkL"),
            "sessionData": session_levels.get("sessions"),
        })
    except Exception as e:
        logger.error("Error getting session levels", symbol=symbol, error=str(e))
        result.update({
            "tokyoH": None, "tokyoL": None,
            "londonH": None, "londonL": None,
            "newyorkH": None, "newyorkL": None,
            "sessionData": None,
        })
    
    return result
