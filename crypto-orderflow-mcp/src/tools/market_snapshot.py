"""
get_market_snapshot tool implementation.
Returns current market snapshot including price, volume, funding, and OI.
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


async def get_market_snapshot(
    symbol: str,
    rest_client: Any,
    orderbook_manager: Any,
) -> dict:
    """
    Get current market snapshot.
    
    Args:
        symbol: Trading pair symbol (e.g., BTCUSDT)
        rest_client: BinanceRestClient instance
        orderbook_manager: OrderbookManager instance
    
    Returns:
        Market snapshot with price, volume, funding, OI data
    """
    result = {
        "symbol": symbol,
        "exchange": "binance",
        "marketType": "linear_perpetual",
        "timestamp": get_utc_now_ms(),
    }
    
    try:
        ticker = await rest_client.get_ticker_24h(symbol)
        if ticker:
            result.update({
                "lastPrice": ticker.get("lastPrice"),
                "priceChange": ticker.get("priceChange"),
                "priceChangePercent": ticker.get("priceChangePercent"),
                "highPrice24h": ticker.get("highPrice"),
                "lowPrice24h": ticker.get("lowPrice"),
                "volume24h": ticker.get("volume"),
                "quoteVolume24h": ticker.get("quoteVolume"),
                "weightedAvgPrice": ticker.get("weightedAvgPrice"),
            })
    except Exception as e:
        logger.error("Error fetching ticker", symbol=symbol, error=str(e))
    
    try:
        mark_price = await rest_client.get_mark_price(symbol)
        if mark_price:
            result.update({
                "markPrice": mark_price.get("markPrice"),
                "indexPrice": mark_price.get("indexPrice"),
                "fundingRate": mark_price.get("lastFundingRate"),
                "nextFundingTime": mark_price.get("nextFundingTime"),
            })
    except Exception as e:
        logger.error("Error fetching mark price", symbol=symbol, error=str(e))
    
    try:
        oi_data = await rest_client.get_open_interest(symbol)
        if oi_data:
            result.update({
                "openInterest": oi_data.get("openInterest"),
                "openInterestValue": str(
                    float(oi_data.get("openInterest", 0)) * 
                    float(result.get("markPrice", 0))
                ) if result.get("markPrice") else None,
            })
    except Exception as e:
        logger.error("Error fetching open interest", symbol=symbol, error=str(e))
    
    try:
        orderbook = orderbook_manager.get_orderbook(symbol)
        if orderbook:
            best_bid = orderbook.get_best_bid()
            best_ask = orderbook.get_best_ask()
            
            if best_bid and best_ask:
                result.update({
                    "bestBid": str(best_bid[0]),
                    "bestBidQty": str(best_bid[1]),
                    "bestAsk": str(best_ask[0]),
                    "bestAskQty": str(best_ask[1]),
                    "spread": str(best_ask[0] - best_bid[0]),
                    "spreadPercent": str(
                        (best_ask[0] - best_bid[0]) / best_bid[0] * 100
                    ),
                })
    except Exception as e:
        logger.error("Error fetching orderbook", symbol=symbol, error=str(e))
    
    return result
