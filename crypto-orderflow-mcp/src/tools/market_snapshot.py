"""

import sys
from pathlib import Path

_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

get_market_snapshot tool implementation.
Returns current market snapshot including price, volume, funding, and OI.
"""

import sys
from pathlib import Path

_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


from typing import Any

from src.data import BinanceRestClient
from src.storage import DataCache
from src.utils import get_logger, get_utc_now_ms

logger = get_logger(__name__)


async def get_market_snapshot(
    symbol: str,
    rest_client: BinanceRestClient,
    cache: DataCache,
) -> dict:
    """
    Get market snapshot for a symbol.
    
    Returns:
        {
            "timestamp": int,
            "symbol": str,
            "exchange": "binance",
            "marketType": "linear perpetual",
            "price": str,
            "markPrice": str,
            "indexPrice": str,
            "high24h": str,
            "low24h": str,
            "volume24h": str,
            "quoteVolume24h": str,
            "fundingRate": str,
            "nextFundingTime": int,
            "openInterest": str,
            "openInterestValue": str
        }
    """
    cache_key = f"market_snapshot:{symbol}"
    
    # Try cache first (5 second TTL)
    cached = await cache.get(cache_key)
    if cached:
        return cached
    
    try:
        # Fetch data from multiple endpoints
        ticker_task = rest_client.get_ticker_24h(symbol)
        mark_price_task = rest_client.get_mark_price(symbol)
        oi_task = rest_client.get_open_interest(symbol)
        
        # Await all tasks
        import asyncio
        ticker, mark_price, oi = await asyncio.gather(
            ticker_task, mark_price_task, oi_task
        )
        
        result = {
            "timestamp": get_utc_now_ms(),
            "symbol": symbol,
            "exchange": "binance",
            "marketType": "linear perpetual",
            
            # Price data
            "price": ticker.get("lastPrice", "0"),
            "markPrice": mark_price.get("markPrice", "0"),
            "indexPrice": mark_price.get("indexPrice", "0"),
            
            # 24h stats
            "high24h": ticker.get("highPrice", "0"),
            "low24h": ticker.get("lowPrice", "0"),
            "volume24h": ticker.get("volume", "0"),
            "quoteVolume24h": ticker.get("quoteVolume", "0"),
            "priceChange24h": ticker.get("priceChange", "0"),
            "priceChangePercent24h": ticker.get("priceChangePercent", "0"),
            
            # Funding
            "fundingRate": mark_price.get("lastFundingRate", "0"),
            "nextFundingTime": mark_price.get("nextFundingTime", 0),
            
            # Open Interest
            "openInterest": oi.get("openInterest", "0"),
            "openInterestValue": str(
                float(oi.get("openInterest", 0)) * float(mark_price.get("markPrice", 0))
            ),
            
            # Additional info
            "weightedAvgPrice": ticker.get("weightedAvgPrice", "0"),
            "trades24h": ticker.get("count", 0),
        }
        
        # Cache result
        await cache.set(cache_key, result, ttl=5)
        
        return result
        
    except Exception as e:
        logger.error("Failed to get market snapshot", symbol=symbol, error=str(e))
        raise
