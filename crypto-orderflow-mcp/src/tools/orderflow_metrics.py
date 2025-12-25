"""

import sys
from pathlib import Path

_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

get_orderflow_metrics tool implementation.
Returns delta, CVD, and imbalance data.
"""

import sys
from pathlib import Path

_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


from typing import Any

from src.indicators import DeltaCVDCalculator, ImbalanceDetector
from src.utils import get_logger, get_utc_now_ms

logger = get_logger(__name__)


async def get_orderflow_metrics(
    symbol: str,
    timeframe: str,
    start_time: int | None,
    end_time: int | None,
    limit: int,
    delta_cvd_calc: DeltaCVDCalculator | None,
    imbalance_detector: ImbalanceDetector | None,
) -> dict:
    """
    Get orderflow metrics for a symbol.
    
    Returns:
        {
            "timestamp": int,
            "symbol": str,
            "exchange": "binance",
            "marketType": "linear perpetual",
            "timeframe": str,
            "delta": {...},
            "cvd": {...},
            "imbalances": {...}
        }
    """
    result = {
        "timestamp": get_utc_now_ms(),
        "symbol": symbol,
        "exchange": "binance",
        "marketType": "linear perpetual",
        "timeframe": timeframe,
    }
    
    # Get delta series
    if delta_cvd_calc:
        delta_series = delta_cvd_calc.get_delta_series(
            timeframe=timeframe,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )
        
        cvd_series = delta_cvd_calc.get_cvd_series(
            timeframe=timeframe,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )
        
        delta_stats = delta_cvd_calc.get_delta_stats(timeframe, lookback=limit)
        divergence = delta_cvd_calc.get_delta_divergence(timeframe, lookback=20)
        
        result["delta"] = {
            "series": delta_series,
            "stats": delta_stats,
            "currentCVD": delta_cvd_calc.get_current_cvd(),
        }
        
        result["cvd"] = {
            "series": cvd_series,
            "divergence": divergence,
        }
    else:
        result["delta"] = None
        result["cvd"] = None
    
    # Get imbalances
    if imbalance_detector:
        recent_imbalances = imbalance_detector.get_recent_imbalances(
            timeframe=timeframe,
            lookback=limit,
        )
        
        imbalance_summary = imbalance_detector.get_imbalance_summary(
            timeframe=timeframe,
            lookback=limit,
        )
        
        result["imbalances"] = {
            "recent": recent_imbalances,
            "summary": imbalance_summary,
        }
    else:
        result["imbalances"] = None
    
    return result
