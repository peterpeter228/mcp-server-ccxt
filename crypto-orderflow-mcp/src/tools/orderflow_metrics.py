"""
get_orderflow_metrics tool implementation.
Returns delta, CVD, and imbalance data.
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


async def get_orderflow_metrics(
    symbol: str,
    delta_cvd_calculator: Any,
    imbalance_detector: Any,
    trade_aggregator: Any,
    timeframe: str = "5m",
    start_time: int | None = None,
    end_time: int | None = None,
    limit: int = 100,
) -> dict:
    """
    Get orderflow metrics including delta, CVD, and imbalances.
    
    Args:
        symbol: Trading pair symbol
        delta_cvd_calculator: DeltaCVDCalculator instance
        imbalance_detector: ImbalanceDetector instance
        trade_aggregator: TradeAggregator instance
        timeframe: Analysis timeframe
        start_time: Start timestamp in ms
        end_time: End timestamp in ms
        limit: Maximum number of data points
    
    Returns:
        Orderflow metrics data
    """
    result = {
        "symbol": symbol,
        "exchange": "binance",
        "marketType": "linear_perpetual",
        "timestamp": get_utc_now_ms(),
        "timeframe": timeframe,
    }
    
    try:
        cvd_summary = delta_cvd_calculator.get_summary(
            timeframe=timeframe,
            lookback_bars=limit,
        )
        result["cvdSummary"] = cvd_summary
        
        bar_deltas = delta_cvd_calculator.get_bar_deltas(
            timeframe=timeframe,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )
        result["barDeltas"] = bar_deltas
        result["deltaBarCount"] = len(bar_deltas)
        
    except Exception as e:
        logger.error("Error getting CVD data", symbol=symbol, error=str(e))
        result.update({
            "cvdSummary": None,
            "barDeltas": [],
            "deltaBarCount": 0,
        })
    
    try:
        bars = trade_aggregator.get_completed_bars(
            timeframe=timeframe,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )
        
        imbalance_data = imbalance_detector.analyze_bars(bars)
        result["imbalances"] = imbalance_data
        
    except Exception as e:
        logger.error("Error getting imbalance data", symbol=symbol, error=str(e))
        result["imbalances"] = None
    
    try:
        total_buy_volume = sum(bar.total_buy_volume for bar in bars) if bars else 0
        total_sell_volume = sum(bar.total_sell_volume for bar in bars) if bars else 0
        total_delta = sum(bar.delta for bar in bars) if bars else 0
        
        result["volumeSummary"] = {
            "totalBuyVolume": str(total_buy_volume),
            "totalSellVolume": str(total_sell_volume),
            "totalDelta": str(total_delta),
            "buyRatio": str(
                total_buy_volume / (total_buy_volume + total_sell_volume)
                if (total_buy_volume + total_sell_volume) > 0 else 0
            ),
            "barCount": len(bars) if bars else 0,
        }
    except Exception as e:
        logger.error("Error calculating volume summary", error=str(e))
        result["volumeSummary"] = None
    
    return result
