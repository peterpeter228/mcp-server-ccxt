"""MCP Tools definitions for Crypto Orderflow."""

from typing import Any

from src.data.cache import MemoryCache
from src.data.storage import DataStorage
from src.data.orderbook import OrderbookManager
from src.binance.rest_client import BinanceRestClient
from src.indicators import (
    VWAPCalculator,
    VolumeProfileCalculator,
    SessionLevelsCalculator,
    FootprintCalculator,
    DeltaCVDCalculator,
    ImbalanceDetector,
    DepthDeltaCalculator,
)
from src.utils import get_logger, timestamp_ms
from src.utils.helpers import get_day_start_ms


class MCPTools:
    """MCP Tools for Crypto Orderflow indicators."""
    
    def __init__(
        self,
        cache: MemoryCache,
        storage: DataStorage,
        orderbook: OrderbookManager,
        rest_client: BinanceRestClient,
        vwap: VWAPCalculator,
        volume_profile: VolumeProfileCalculator,
        session_levels: SessionLevelsCalculator,
        footprint: FootprintCalculator,
        delta_cvd: DeltaCVDCalculator,
        imbalance: ImbalanceDetector,
        depth_delta: DepthDeltaCalculator,
    ):
        self.cache = cache
        self.storage = storage
        self.orderbook = orderbook
        self.rest_client = rest_client
        self.vwap = vwap
        self.volume_profile = volume_profile
        self.session_levels = session_levels
        self.footprint = footprint
        self.delta_cvd = delta_cvd
        self.imbalance = imbalance
        self.depth_delta = depth_delta
        self.logger = get_logger("mcp.tools")
    
    async def get_market_snapshot(self, symbol: str) -> dict[str, Any]:
        """Get market snapshot including price, funding, OI.
        
        Args:
            symbol: Trading pair symbol (e.g., 'BTCUSDT')
        
        Returns:
            Market snapshot with latest price, mark price, 24h stats, funding, OI
        """
        symbol = symbol.upper()
        self.logger.info("get_market_snapshot", symbol=symbol)
        
        # Get from cache
        snapshot = self.cache.get_snapshot(symbol)
        
        # Enhance with additional data if available
        depth_summary = self.depth_delta.get_depth_summary(symbol)
        if depth_summary:
            snapshot["depthBidVolume"] = depth_summary["bidVolume"]
            snapshot["depthAskVolume"] = depth_summary["askVolume"]
            snapshot["depthNetVolume"] = depth_summary["netVolume"]
            snapshot["depthBidAskRatio"] = depth_summary["bidAskRatio"]
        
        return snapshot
    
    async def get_key_levels(
        self,
        symbol: str,
        date: str | None = None,
        session_tz: str = "UTC",
    ) -> dict[str, Any]:
        """Get key levels including VWAP, Volume Profile, Session H/L.
        
        Args:
            symbol: Trading pair symbol
            date: Date string (YYYY-MM-DD) or None for today
            session_tz: Session timezone (currently only UTC supported)
        
        Returns:
            Key levels with dVWAP, pdVWAP, POC, VAH, VAL, session H/L
        """
        symbol = symbol.upper()
        self.logger.info("get_key_levels", symbol=symbol, date=date)
        
        # Parse date
        date_ms = None
        if date:
            from datetime import datetime
            dt = datetime.strptime(date, "%Y-%m-%d")
            date_ms = int(dt.timestamp() * 1000)
        
        # Get VWAP levels
        vwap_levels = await self.vwap.get_key_levels(symbol, date_ms)
        
        # Get Volume Profile levels
        vp_levels = await self.volume_profile.get_key_levels(symbol, date_ms)
        
        # Get Session levels
        session_levels = await self.session_levels.get_key_levels(symbol, date_ms)
        
        return {
            "symbol": symbol,
            "exchange": "binance",
            "marketType": "linear_perpetual",
            "timestamp": timestamp_ms(),
            "date": date or "today",
            "sessionTimezone": session_tz,
            "vwap": {
                "dVWAP": vwap_levels.get("dVWAP"),
                "pdVWAP": vwap_levels.get("pdVWAP"),
            },
            "volumeProfile": {
                "developing": vp_levels.get("developing", {}),
                "previousDay": vp_levels.get("previousDay", {}),
            },
            "sessions": session_levels,
            "priceUnit": "USDT",
        }
    
    async def get_footprint(
        self,
        symbol: str,
        timeframe: str,
        start_time: int,
        end_time: int,
    ) -> dict[str, Any]:
        """Get footprint bars for a time range.
        
        Args:
            symbol: Trading pair symbol
            timeframe: Candle timeframe (1m, 5m, 15m, 30m, 1h)
            start_time: Start timestamp in milliseconds
            end_time: End timestamp in milliseconds
        
        Returns:
            Footprint bars with buy/sell volume per price level
        """
        symbol = symbol.upper()
        self.logger.info("get_footprint", symbol=symbol, timeframe=timeframe)
        
        bars = await self.footprint.get_footprint_range(
            symbol=symbol,
            timeframe=timeframe,
            start_time=start_time,
            end_time=end_time,
        )
        
        return {
            "symbol": symbol,
            "exchange": "binance",
            "marketType": "linear_perpetual",
            "timeframe": timeframe,
            "startTime": start_time,
            "endTime": end_time,
            "timestamp": timestamp_ms(),
            "barCount": len(bars),
            "bars": bars,
            "volumeUnit": symbol.replace("USDT", ""),
            "priceUnit": "USDT",
        }
    
    async def get_orderflow_metrics(
        self,
        symbol: str,
        timeframe: str,
        start_time: int,
        end_time: int,
    ) -> dict[str, Any]:
        """Get orderflow metrics including delta, CVD, imbalances.
        
        Args:
            symbol: Trading pair symbol
            timeframe: Candle timeframe
            start_time: Start timestamp in milliseconds
            end_time: End timestamp in milliseconds
        
        Returns:
            Orderflow metrics with delta sequence, CVD, imbalances
        """
        symbol = symbol.upper()
        self.logger.info("get_orderflow_metrics", symbol=symbol, timeframe=timeframe)
        
        # Get delta/CVD data
        delta_data = await self.delta_cvd.get_delta_range(
            symbol=symbol,
            timeframe=timeframe,
            start_time=start_time,
            end_time=end_time,
        )
        
        # Get footprint bars for imbalance analysis
        footprint_bars = await self.footprint.get_footprint_range(
            symbol=symbol,
            timeframe=timeframe,
            start_time=start_time,
            end_time=end_time,
        )
        
        # Analyze imbalances in latest bar
        imbalance_analysis = None
        if footprint_bars:
            # Create footprint bar object from dict
            from src.indicators.footprint import FootprintBar, FootprintLevel
            
            latest = footprint_bars[-1]
            bar = FootprintBar(
                symbol=latest["symbol"],
                timeframe=latest["timeframe"],
                timestamp=latest["timestamp"],
            )
            for level_data in latest.get("levels", []):
                bar.levels[level_data["price"]] = FootprintLevel(
                    price=level_data["price"],
                    buy_volume=level_data["buyVolume"],
                    sell_volume=level_data["sellVolume"],
                    trade_count=level_data["tradeCount"],
                )
            
            imbalance_analysis = self.imbalance.analyze_footprint(bar)
        
        return {
            "symbol": symbol,
            "exchange": "binance",
            "marketType": "linear_perpetual",
            "timeframe": timeframe,
            "startTime": start_time,
            "endTime": end_time,
            "timestamp": timestamp_ms(),
            "delta": delta_data.get("summary", {}),
            "deltaSequence": delta_data.get("deltaSequence", []),
            "cvdSequence": delta_data.get("cvdSequence", []),
            "currentCVD": delta_data.get("currentCVD", 0),
            "imbalances": imbalance_analysis,
            "volumeUnit": symbol.replace("USDT", ""),
        }
    
    async def get_orderbook_depth_delta(
        self,
        symbol: str,
        percent: float = 1.0,
        window_sec: int = 5,
        lookback: int = 3600,
    ) -> dict[str, Any]:
        """Get orderbook depth delta over time.
        
        Args:
            symbol: Trading pair symbol
            percent: Price range percentage from mid (default 1%)
            window_sec: Snapshot interval in seconds
            lookback: Lookback period in seconds
        
        Returns:
            Depth delta time series with bid/ask volumes
        """
        symbol = symbol.upper()
        self.logger.info("get_orderbook_depth_delta", symbol=symbol, percent=percent)
        
        depth_data = await self.depth_delta.get_depth_delta_series(
            symbol=symbol,
            percent_range=percent,
            lookback_seconds=lookback,
        )
        
        # Add current summary
        current_summary = self.depth_delta.get_depth_summary(symbol)
        if current_summary:
            depth_data["current"] = current_summary
        
        return {
            "symbol": symbol,
            "exchange": "binance",
            "marketType": "linear_perpetual",
            "percentRange": percent,
            "windowSec": window_sec,
            "lookbackSec": lookback,
            **depth_data,
            "volumeUnit": symbol.replace("USDT", ""),
        }
    
    async def stream_liquidations(
        self,
        symbol: str,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Get recent liquidation events.
        
        Args:
            symbol: Trading pair symbol
            limit: Maximum number of liquidations to return
        
        Returns:
            Recent liquidation events
        """
        symbol = symbol.upper()
        self.logger.info("stream_liquidations", symbol=symbol, limit=limit)
        
        liquidations = self.cache.get_liquidations(symbol, limit)
        
        # Convert to dict format
        liq_list = [
            {
                "timestamp": liq.timestamp,
                "symbol": liq.symbol,
                "side": liq.side,
                "price": liq.price,
                "avgPrice": liq.avg_price,
                "originalQty": liq.original_qty,
                "filledQty": liq.filled_qty,
                "notional": liq.notional,
                "isLongLiquidation": liq.is_long_liquidation,
                "orderStatus": liq.order_status,
            }
            for liq in liquidations
        ]
        
        # Calculate statistics
        long_liqs = [l for l in liq_list if l["isLongLiquidation"]]
        short_liqs = [l for l in liq_list if not l["isLongLiquidation"]]
        
        return {
            "symbol": symbol,
            "exchange": "binance",
            "marketType": "linear_perpetual",
            "timestamp": timestamp_ms(),
            "count": len(liq_list),
            "statistics": {
                "longLiquidations": len(long_liqs),
                "shortLiquidations": len(short_liqs),
                "totalLongNotional": sum(l["notional"] for l in long_liqs),
                "totalShortNotional": sum(l["notional"] for l in short_liqs),
            },
            "liquidations": liq_list,
            "notionalUnit": "USDT",
            "volumeUnit": symbol.replace("USDT", ""),
        }
    
    async def get_open_interest(
        self,
        symbol: str,
        period: str = "5m",
        limit: int = 100,
    ) -> dict[str, Any]:
        """Get open interest data including history.
        
        Args:
            symbol: Trading pair symbol
            period: Historical period (5m, 15m, 30m, 1h, 2h, 4h, 6h, 12h, 1d)
            limit: Number of historical records
        
        Returns:
            Current OI and historical data
        """
        symbol = symbol.upper()
        self.logger.info("get_open_interest", symbol=symbol, period=period)
        
        # Get current OI from cache
        cache = self.cache.get_cache(symbol)
        current_oi = cache.open_interest
        current_oi_notional = cache.open_interest_notional
        
        # Get historical OI
        try:
            oi_history = await self.rest_client.get_open_interest_hist(
                symbol=symbol,
                period=period,
                limit=limit,
            )
            
            history_list = [
                {
                    "timestamp": h.timestamp,
                    "openInterest": h.sum_open_interest,
                    "openInterestNotional": h.sum_open_interest_value,
                }
                for h in oi_history
            ]
            
            # Calculate OI delta
            if len(history_list) >= 2:
                oi_delta = history_list[-1]["openInterest"] - history_list[-2]["openInterest"]
                oi_delta_notional = history_list[-1]["openInterestNotional"] - history_list[-2]["openInterestNotional"]
            else:
                oi_delta = 0
                oi_delta_notional = 0
            
        except Exception as e:
            self.logger.error("get_oi_history_failed", error=str(e))
            history_list = []
            oi_delta = 0
            oi_delta_notional = 0
        
        return {
            "symbol": symbol,
            "exchange": "binance",
            "marketType": "linear_perpetual",
            "timestamp": timestamp_ms(),
            "current": {
                "openInterest": current_oi,
                "openInterestNotional": current_oi_notional,
            },
            "delta": {
                "period": period,
                "openInterestDelta": oi_delta,
                "openInterestDeltaNotional": oi_delta_notional,
            },
            "history": history_list,
            "oiUnit": symbol.replace("USDT", ""),
            "notionalUnit": "USDT",
        }
    
    async def get_funding_rate(self, symbol: str) -> dict[str, Any]:
        """Get current and historical funding rate.
        
        Args:
            symbol: Trading pair symbol
        
        Returns:
            Current funding rate and next funding time
        """
        symbol = symbol.upper()
        self.logger.info("get_funding_rate", symbol=symbol)
        
        # Get from cache
        cache = self.cache.get_cache(symbol)
        
        # Get historical funding rates
        try:
            funding_history = await self.rest_client.get_funding_rate(symbol, limit=10)
            history_list = [
                {
                    "fundingTime": f.funding_time,
                    "fundingRate": f.funding_rate,
                }
                for f in funding_history
            ]
        except Exception as e:
            self.logger.error("get_funding_history_failed", error=str(e))
            history_list = []
        
        return {
            "symbol": symbol,
            "exchange": "binance",
            "marketType": "linear_perpetual",
            "timestamp": timestamp_ms(),
            "current": {
                "fundingRate": cache.funding_rate,
                "fundingRatePercent": cache.funding_rate * 100,
                "nextFundingTime": cache.next_funding_time,
            },
            "history": history_list,
        }
