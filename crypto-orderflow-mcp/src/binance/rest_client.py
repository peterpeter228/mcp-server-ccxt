"""Binance REST API client for USD-M Futures."""

import asyncio
from typing import Any

import aiohttp

from src.config import get_settings
from src.utils import get_logger, timestamp_ms
from .types import (
    AggTrade,
    FundingRate,
    Kline,
    OpenInterest,
    OpenInterestHist,
    OrderbookLevel,
    OrderbookSnapshot,
    Ticker24h,
    MarkPrice,
)


class BinanceRestClient:
    """Async REST client for Binance USD-M Futures API."""
    
    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.binance_rest_url
        self.logger = get_logger("binance.rest")
        self._session: aiohttp.ClientSession | None = None
        self._rate_limit_remaining = self.settings.rest_rate_limit_per_min
        self._rate_limit_reset = timestamp_ms() + 60_000
        
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session
    
    async def close(self) -> None:
        """Close the session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
    
    async def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Make HTTP request with rate limiting."""
        session = await self._get_session()
        url = f"{self.base_url}{endpoint}"
        
        # Simple rate limit check
        now = timestamp_ms()
        if now > self._rate_limit_reset:
            self._rate_limit_remaining = self.settings.rest_rate_limit_per_min
            self._rate_limit_reset = now + 60_000
        
        if self._rate_limit_remaining <= 0:
            wait_time = (self._rate_limit_reset - now) / 1000
            self.logger.warning("rate_limit_hit", wait_seconds=wait_time)
            await asyncio.sleep(wait_time)
            self._rate_limit_remaining = self.settings.rest_rate_limit_per_min
        
        self._rate_limit_remaining -= 1
        
        try:
            async with session.request(method, url, params=params) as response:
                # Update rate limit from headers
                if "X-MBX-USED-WEIGHT-1M" in response.headers:
                    used = int(response.headers["X-MBX-USED-WEIGHT-1M"])
                    self._rate_limit_remaining = self.settings.rest_rate_limit_per_min - used
                
                if response.status == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    self.logger.warning("rate_limited", retry_after=retry_after)
                    await asyncio.sleep(retry_after)
                    return await self._request(method, endpoint, params)
                
                response.raise_for_status()
                return await response.json()
                
        except aiohttp.ClientError as e:
            self.logger.error("request_failed", endpoint=endpoint, error=str(e))
            raise
    
    async def get_exchange_info(self) -> dict[str, Any]:
        """Get exchange trading rules and symbol information."""
        return await self._request("GET", "/fapi/v1/exchangeInfo")
    
    async def get_ticker_24h(self, symbol: str) -> Ticker24h:
        """Get 24hr ticker statistics."""
        data = await self._request("GET", "/fapi/v1/ticker/24hr", {"symbol": symbol})
        return Ticker24h(
            symbol=data["symbol"],
            price_change=float(data["priceChange"]),
            price_change_percent=float(data["priceChangePercent"]),
            weighted_avg_price=float(data["weightedAvgPrice"]),
            last_price=float(data["lastPrice"]),
            last_qty=float(data["lastQty"]),
            open_price=float(data["openPrice"]),
            high_price=float(data["highPrice"]),
            low_price=float(data["lowPrice"]),
            volume=float(data["volume"]),
            quote_volume=float(data["quoteVolume"]),
            open_time=data["openTime"],
            close_time=data["closeTime"],
            first_trade_id=data["firstId"],
            last_trade_id=data["lastId"],
            trade_count=data["count"],
        )
    
    async def get_mark_price(self, symbol: str) -> MarkPrice:
        """Get mark price and funding rate."""
        data = await self._request("GET", "/fapi/v1/premiumIndex", {"symbol": symbol})
        return MarkPrice(
            symbol=data["symbol"],
            mark_price=float(data["markPrice"]),
            index_price=float(data["indexPrice"]),
            estimated_settle_price=float(data.get("estimatedSettlePrice", 0)),
            funding_rate=float(data["lastFundingRate"]),
            next_funding_time=data["nextFundingTime"],
            timestamp=data["time"],
        )
    
    async def get_funding_rate(self, symbol: str, limit: int = 1) -> list[FundingRate]:
        """Get funding rate history."""
        data = await self._request(
            "GET", "/fapi/v1/fundingRate",
            {"symbol": symbol, "limit": limit}
        )
        return [
            FundingRate(
                symbol=item["symbol"],
                funding_rate=float(item["fundingRate"]),
                funding_time=item["fundingTime"],
                mark_price=float(item.get("markPrice", 0)) if item.get("markPrice") else None,
            )
            for item in data
        ]
    
    async def get_open_interest(self, symbol: str) -> OpenInterest:
        """Get current open interest."""
        data = await self._request("GET", "/fapi/v1/openInterest", {"symbol": symbol})
        # Get notional value from another endpoint
        oi_data = await self._request(
            "GET", "/futures/data/openInterestHist",
            {"symbol": symbol, "period": "5m", "limit": 1}
        )
        notional = float(oi_data[0]["sumOpenInterestValue"]) if oi_data else 0
        
        return OpenInterest(
            symbol=data["symbol"],
            open_interest=float(data["openInterest"]),
            open_interest_notional=notional,
            timestamp=data.get("time", timestamp_ms()),
        )
    
    async def get_open_interest_hist(
        self,
        symbol: str,
        period: str = "5m",
        limit: int = 500,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[OpenInterestHist]:
        """Get historical open interest.
        
        Args:
            symbol: Trading pair symbol
            period: '5m', '15m', '30m', '1h', '2h', '4h', '6h', '12h', '1d'
            limit: Number of records (max 500)
            start_time: Start time in milliseconds
            end_time: End time in milliseconds
        """
        params: dict[str, Any] = {
            "symbol": symbol,
            "period": period,
            "limit": limit,
        }
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        
        data = await self._request("GET", "/futures/data/openInterestHist", params)
        return [
            OpenInterestHist(
                symbol=symbol,
                sum_open_interest=float(item["sumOpenInterest"]),
                sum_open_interest_value=float(item["sumOpenInterestValue"]),
                timestamp=item["timestamp"],
            )
            for item in data
        ]
    
    async def get_orderbook_snapshot(self, symbol: str, limit: int = 1000) -> OrderbookSnapshot:
        """Get orderbook depth snapshot.
        
        Args:
            symbol: Trading pair symbol
            limit: Depth limit (5, 10, 20, 50, 100, 500, 1000)
        """
        data = await self._request(
            "GET", "/fapi/v1/depth",
            {"symbol": symbol, "limit": limit}
        )
        return OrderbookSnapshot(
            symbol=symbol,
            last_update_id=data["lastUpdateId"],
            timestamp=data.get("T", timestamp_ms()),
            bids=[OrderbookLevel(float(b[0]), float(b[1])) for b in data["bids"]],
            asks=[OrderbookLevel(float(a[0]), float(a[1])) for a in data["asks"]],
        )
    
    async def get_agg_trades(
        self,
        symbol: str,
        from_id: int | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 1000,
    ) -> list[AggTrade]:
        """Get aggregated trades.
        
        Args:
            symbol: Trading pair symbol
            from_id: Trade ID to fetch from
            start_time: Start time in milliseconds
            end_time: End time in milliseconds
            limit: Number of trades (max 1000)
        """
        params: dict[str, Any] = {"symbol": symbol, "limit": limit}
        if from_id:
            params["fromId"] = from_id
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        
        data = await self._request("GET", "/fapi/v1/aggTrades", params)
        return [
            AggTrade(
                agg_trade_id=item["a"],
                symbol=symbol,
                price=float(item["p"]),
                quantity=float(item["q"]),
                first_trade_id=item["f"],
                last_trade_id=item["l"],
                timestamp=item["T"],
                is_buyer_maker=item["m"],
            )
            for item in data
        ]
    
    async def get_klines(
        self,
        symbol: str,
        interval: str,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 500,
    ) -> list[Kline]:
        """Get kline/candlestick data.
        
        Args:
            symbol: Trading pair symbol
            interval: Kline interval (1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 3d, 1w, 1M)
            start_time: Start time in milliseconds
            end_time: End time in milliseconds
            limit: Number of klines (max 1500)
        """
        params: dict[str, Any] = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        
        data = await self._request("GET", "/fapi/v1/klines", params)
        return [
            Kline(
                symbol=symbol,
                interval=interval,
                open_time=item[0],
                open=float(item[1]),
                high=float(item[2]),
                low=float(item[3]),
                close=float(item[4]),
                volume=float(item[5]),
                close_time=item[6],
                quote_volume=float(item[7]),
                trade_count=item[8],
                taker_buy_volume=float(item[9]),
                taker_buy_quote_volume=float(item[10]),
            )
            for item in data
        ]
    
    async def fetch_trades_range(
        self,
        symbol: str,
        start_time: int,
        end_time: int,
    ) -> list[AggTrade]:
        """Fetch all trades in a time range (handles pagination).
        
        Args:
            symbol: Trading pair symbol
            start_time: Start time in milliseconds
            end_time: End time in milliseconds
        
        Returns:
            List of all trades in the range
        """
        all_trades: list[AggTrade] = []
        current_start = start_time
        
        while current_start < end_time:
            trades = await self.get_agg_trades(
                symbol=symbol,
                start_time=current_start,
                end_time=end_time,
                limit=1000,
            )
            
            if not trades:
                break
            
            all_trades.extend(trades)
            
            # Move start to after last trade
            last_timestamp = trades[-1].timestamp
            if last_timestamp >= current_start:
                current_start = last_timestamp + 1
            else:
                break
            
            # Small delay to avoid rate limits
            await asyncio.sleep(0.1)
        
        return all_trades
