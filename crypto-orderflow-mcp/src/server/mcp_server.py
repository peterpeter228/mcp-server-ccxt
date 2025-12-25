"""
MCP Server implementation with SSE and Streamable HTTP support.
"""

import asyncio
import json
import os
import sys
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Deque

# Ensure imports work
_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse, Response
from starlette.requests import Request
from sse_starlette.sse import EventSourceResponse
import uvicorn

from src.config import get_config
from src.utils.logging import get_logger, setup_logging
from src.utils.time_utils import get_utc_now_ms
from src.data.binance_rest import BinanceRestClient
from src.data.binance_ws import BinanceWebSocketClient, StreamType, BinanceAllMarketsWebSocket
from src.data.orderbook import OrderbookManager
from src.data.trade_aggregator import TradeAggregator, AggregatedTrade
from src.indicators.vwap import VWAPCalculator
from src.indicators.volume_profile import VolumeProfileCalculator
from src.indicators.session_levels import SessionLevelCalculator
from src.indicators.footprint import FootprintCalculator
from src.indicators.delta_cvd import DeltaCVDCalculator
from src.indicators.imbalance import ImbalanceDetector
from src.indicators.depth_delta import DepthDeltaCalculator
from src.storage.sqlite_store import SQLiteStore
from src.storage.cache import DataCache
from src.tools.market_snapshot import get_market_snapshot
from src.tools.key_levels import get_key_levels
from src.tools.footprint import get_footprint
from src.tools.orderflow_metrics import get_orderflow_metrics
from src.tools.depth_delta import get_orderbook_depth_delta
from src.tools.liquidations import stream_liquidations, LiquidationCache

logger = get_logger(__name__)


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder for Decimal types."""
    def default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return str(obj)
        return super().default(obj)


@dataclass
class CryptoMCPServer:
    """
    Main MCP Server for crypto orderflow data.
    
    Provides:
    - REST API endpoints
    - SSE streaming
    - MCP tool interface
    """
    
    config: Any = field(default_factory=get_config)
    
    # Components
    rest_client: BinanceRestClient = field(default_factory=BinanceRestClient)
    ws_client: BinanceWebSocketClient = field(default_factory=BinanceWebSocketClient)
    all_markets_ws: BinanceAllMarketsWebSocket | None = None
    orderbook_manager: OrderbookManager | None = None
    store: SQLiteStore = field(default_factory=SQLiteStore)
    cache: DataCache = field(default_factory=DataCache)
    
    # Per-symbol components
    trade_aggregators: dict[str, TradeAggregator] = field(default_factory=dict)
    vwap_calculators: dict[str, VWAPCalculator] = field(default_factory=dict)
    volume_profile_calculators: dict[str, VolumeProfileCalculator] = field(default_factory=dict)
    session_level_calculators: dict[str, SessionLevelCalculator] = field(default_factory=dict)
    footprint_calculators: dict[str, FootprintCalculator] = field(default_factory=dict)
    delta_cvd_calculators: dict[str, DeltaCVDCalculator] = field(default_factory=dict)
    imbalance_detectors: dict[str, ImbalanceDetector] = field(default_factory=dict)
    depth_delta_calculators: dict[str, DepthDeltaCalculator] = field(default_factory=dict)
    
    # Liquidation caches
    liquidation_caches: dict[str, LiquidationCache] = field(default_factory=dict)
    
    # State
    _running: bool = False
    
    async def initialize(self) -> None:
        """Initialize all components."""
        logger.info("Initializing Crypto MCP Server...")
        
        # Setup logging
        setup_logging(self.config.log_level, self.config.log_format)
        
        # Initialize database
        await self.store.initialize()
        
        # Initialize per-symbol components
        for symbol in self.config.symbols:
            tick_size = Decimal(str(self.config.get_tick_size(symbol)))
            
            # Trade aggregator
            self.trade_aggregators[symbol] = TradeAggregator(
                symbol=symbol,
                tick_size=tick_size,
            )
            
            # Indicators
            self.vwap_calculators[symbol] = VWAPCalculator(symbol=symbol)
            self.volume_profile_calculators[symbol] = VolumeProfileCalculator(
                symbol=symbol,
                tick_size=tick_size,
                value_area_percent=self.config.value_area_percent,
            )
            # Convert session list to dict by name
            sessions_dict = {s.name.lower(): s for s in self.config.sessions}
            self.session_level_calculators[symbol] = SessionLevelCalculator(
                symbol=symbol,
                sessions=sessions_dict,
            )
            self.footprint_calculators[symbol] = FootprintCalculator(
                symbol=symbol,
                trade_aggregator=self.trade_aggregators[symbol],
            )
            self.delta_cvd_calculators[symbol] = DeltaCVDCalculator(
                symbol=symbol,
                trade_aggregator=self.trade_aggregators[symbol],
            )
            self.imbalance_detectors[symbol] = ImbalanceDetector(
                symbol=symbol,
                min_ratio=Decimal(str(self.config.imbalance_ratio_threshold)),
                min_stack_levels=self.config.imbalance_consecutive_count,
            )
            
            # Liquidation cache
            self.liquidation_caches[symbol] = LiquidationCache(max_size=1000)
        
        # Initialize orderbook manager
        self.orderbook_manager = OrderbookManager(
            rest_client=self.rest_client,
            ws_client=self.ws_client,
            symbols=self.config.symbols,
            depth_limit=self.config.orderbook_depth_levels,
            resync_interval=self.config.orderbook_sync_interval,
        )
        
        # Initialize depth delta calculators (one per symbol for now)
        self.depth_delta_calculators: dict[str, DepthDeltaCalculator] = {}
        for symbol in self.config.symbols:
            self.depth_delta_calculators[symbol] = DepthDeltaCalculator(
                symbol=symbol,
                orderbook_manager=self.orderbook_manager,
                percent_range=Decimal(str(self.config.depth_delta_percent)),
                snapshot_interval_sec=self.config.depth_delta_interval_sec,
            )
        
        # Initialize all-markets WebSocket for liquidations
        self.all_markets_ws = BinanceAllMarketsWebSocket(
            base_url=self.config.binance_ws_url
        )
        self.all_markets_ws.on_force_order(self._on_liquidation)
        
        logger.info(
            "Components initialized",
            symbols=self.config.symbols,
        )
    
    async def start(self) -> None:
        """Start all services."""
        if self._running:
            return
        
        self._running = True
        
        # Subscribe to trade streams
        for symbol in self.config.symbols:
            self.ws_client.subscribe(
                symbol=symbol,
                stream_type=StreamType.AGG_TRADE,
                callback=self._on_trade,
            )
        
        # Start WebSocket connections
        await self.ws_client.connect()
        await self.all_markets_ws.connect()
        
        # Start orderbook manager
        await self.orderbook_manager.start()
        
        # Start depth delta calculators
        for calc in self.depth_delta_calculators.values():
            await calc.start()
        
        # Start cleanup task
        asyncio.create_task(self._cleanup_loop())
        
        logger.info("Crypto MCP Server started")
    
    async def stop(self) -> None:
        """Stop all services."""
        self._running = False
        
        await self.ws_client.disconnect()
        if self.all_markets_ws:
            await self.all_markets_ws.disconnect()
        if self.orderbook_manager:
            await self.orderbook_manager.stop()
        for calc in self.depth_delta_calculators.values():
            await calc.stop()
        
        await self.rest_client.close()
        await self.store.close()
        
        logger.info("Crypto MCP Server stopped")
    
    async def _on_trade(self, data: dict) -> None:
        """Handle incoming trade from WebSocket."""
        try:
            # Validate data is a dict with expected trade fields
            if not isinstance(data, dict) or "a" not in data:
                return
            
            trade = AggregatedTrade.from_ws_data(data)
            symbol = data.get("s", "")
            
            if symbol in self.trade_aggregators:
                # Add to aggregator
                self.trade_aggregators[symbol].add_trade(trade)
                
                # Update indicators
                if symbol in self.vwap_calculators:
                    self.vwap_calculators[symbol].add_trade(trade)
                if symbol in self.volume_profile_calculators:
                    self.volume_profile_calculators[symbol].add_trade(trade)
                if symbol in self.session_level_calculators:
                    self.session_level_calculators[symbol].add_trade(trade)
        except Exception as e:
            logger.error("Error processing trade", error=str(e))
    
    async def _on_liquidation(self, data: dict) -> None:
        """Handle liquidation event from WebSocket."""
        try:
            order = data.get("o", {})
            symbol = order.get("s", "")
            
            if symbol in self.liquidation_caches:
                liq_event = {
                    "symbol": symbol,
                    "side": order.get("S", ""),
                    "orderType": order.get("o", ""),
                    "timeInForce": order.get("f", ""),
                    "quantity": order.get("q", ""),
                    "price": order.get("p", ""),
                    "avgPrice": order.get("ap", ""),
                    "status": order.get("X", ""),
                    "timestamp": order.get("T", get_utc_now_ms()),
                }
                
                self.liquidation_caches[symbol].add(liq_event)
                
                # Also save to database
                await self.store.save_liquidation(liq_event)
        except Exception as e:
            logger.error("Error processing liquidation", error=str(e))
    
    async def _cleanup_loop(self) -> None:
        """Periodic cleanup task."""
        while self._running:
            try:
                # Clean old data from database
                await self.store.cleanup_old_data()
                
                # Clean cache
                await self.cache.cleanup_expired()
                
            except Exception as e:
                logger.error("Cleanup error", error=str(e))
            
            # Run every hour
            await asyncio.sleep(3600)
    
    # ==================== API Methods ====================
    
    async def api_get_market_snapshot(self, symbol: str) -> dict:
        """Get market snapshot for a symbol."""
        return await get_market_snapshot(
            symbol=symbol,
            rest_client=self.rest_client,
            cache=self.cache,
        )
    
    async def api_get_key_levels(
        self,
        symbol: str,
        date: str | None = None,
        session_tz: str = "UTC",
    ) -> dict:
        """Get key levels for a symbol."""
        return await get_key_levels(
            symbol=symbol,
            date=date,
            session_tz=session_tz,
            vwap_calc=self.vwap_calculators.get(symbol),
            vp_calc=self.volume_profile_calculators.get(symbol),
            session_calc=self.session_level_calculators.get(symbol),
            store=self.store,
            cache=self.cache,
        )
    
    async def api_get_footprint(
        self,
        symbol: str,
        timeframe: str = "1m",
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 100,
    ) -> dict:
        """Get footprint bars for a symbol."""
        return await get_footprint(
            symbol=symbol,
            timeframe=timeframe,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            fp_calc=self.footprint_calculators.get(symbol),
            store=self.store,
        )
    
    async def api_get_orderflow_metrics(
        self,
        symbol: str,
        timeframe: str = "1m",
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 100,
    ) -> dict:
        """Get orderflow metrics for a symbol."""
        return await get_orderflow_metrics(
            symbol=symbol,
            timeframe=timeframe,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            delta_cvd_calc=self.delta_cvd_calculators.get(symbol),
            imbalance_detector=self.imbalance_detectors.get(symbol),
        )
    
    async def api_get_orderbook_depth_delta(
        self,
        symbol: str,
        percent: float = 1.0,
        window_sec: int = 5,
        lookback: int = 100,
    ) -> dict:
        """Get orderbook depth delta for a symbol."""
        depth_calc = self.depth_delta_calculators.get(symbol)
        if not depth_calc:
            return {"error": f"No depth delta calculator for {symbol}"}
        return await get_orderbook_depth_delta(
            symbol=symbol,
            depth_delta_calculator=depth_calc,
            percent=percent,
            window_sec=window_sec,
            lookback=lookback,
        )
    
    async def api_stream_liquidations(
        self,
        symbol: str,
        limit: int = 100,
    ) -> dict:
        """Get recent liquidations for a symbol."""
        liq_cache = self.liquidation_caches.get(symbol)
        if not liq_cache:
            return {"error": f"No liquidation cache for {symbol}"}
        return await stream_liquidations(
            symbol=symbol,
            liquidation_cache=liq_cache,
            sqlite_store=self.store,
            limit=limit,
        )
    
    def get_health(self) -> dict:
        """Get server health status."""
        return {
            "status": "healthy" if self._running else "stopped",
            "timestamp": get_utc_now_ms(),
            "symbols": self.config.symbols,
            "websocket": self.ws_client.get_status(),
            "orderbook": self.orderbook_manager.get_status() if self.orderbook_manager else None,
            "cacheSize": self.cache.size(),
        }
    
    # ==================== HTTP Server ====================
    
    def create_http_app(self) -> Starlette:
        """Create Starlette HTTP application."""
        
        async def healthz(request: Request) -> JSONResponse:
            return JSONResponse(self.get_health())
        
        async def mcp_handler(request: Request) -> Response:
            """Handle MCP requests (Streamable HTTP)."""
            try:
                body = await request.json()
                method = body.get("method", "")
                params = body.get("params", {})
                request_id = body.get("id")
                
                result = await self._handle_mcp_method(method, params)
                
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": result,
                }
                
                return JSONResponse(
                    response,
                    headers={"Content-Type": "application/json"},
                )
            except Exception as e:
                logger.error("MCP request error", error=str(e))
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32603, "message": str(e)},
                    },
                    status_code=500,
                )
        
        async def sse_handler(request: Request) -> EventSourceResponse:
            """Handle SSE connections."""
            async def event_generator():
                # Send initial connection event
                yield {
                    "event": "connected",
                    "data": json.dumps({
                        "timestamp": get_utc_now_ms(),
                        "symbols": self.config.symbols,
                    }),
                }
                
                # Stream updates
                while True:
                    # Get market snapshots
                    for symbol in self.config.symbols:
                        try:
                            snapshot = await self.api_get_market_snapshot(symbol)
                            yield {
                                "event": "market_snapshot",
                                "data": json.dumps(snapshot, cls=DecimalEncoder),
                            }
                        except Exception as e:
                            logger.error("SSE snapshot error", error=str(e))
                    
                    await asyncio.sleep(1)
            
            return EventSourceResponse(event_generator())
        
        async def api_market_snapshot(request: Request) -> JSONResponse:
            symbol = request.path_params.get("symbol", "BTCUSDT")
            result = await self.api_get_market_snapshot(symbol)
            return JSONResponse(result)
        
        async def api_key_levels(request: Request) -> JSONResponse:
            symbol = request.path_params.get("symbol", "BTCUSDT")
            date = request.query_params.get("date")
            session_tz = request.query_params.get("sessionTZ", "UTC")
            result = await self.api_get_key_levels(symbol, date, session_tz)
            return JSONResponse(result)
        
        async def api_footprint(request: Request) -> JSONResponse:
            symbol = request.path_params.get("symbol", "BTCUSDT")
            timeframe = request.query_params.get("timeframe", "1m")
            start_time = request.query_params.get("startTime")
            end_time = request.query_params.get("endTime")
            limit = int(request.query_params.get("limit", "100"))
            
            result = await self.api_get_footprint(
                symbol=symbol,
                timeframe=timeframe,
                start_time=int(start_time) if start_time else None,
                end_time=int(end_time) if end_time else None,
                limit=limit,
            )
            return JSONResponse(result)
        
        async def api_orderflow_metrics(request: Request) -> JSONResponse:
            symbol = request.path_params.get("symbol", "BTCUSDT")
            timeframe = request.query_params.get("timeframe", "1m")
            start_time = request.query_params.get("startTime")
            end_time = request.query_params.get("endTime")
            limit = int(request.query_params.get("limit", "100"))
            
            result = await self.api_get_orderflow_metrics(
                symbol=symbol,
                timeframe=timeframe,
                start_time=int(start_time) if start_time else None,
                end_time=int(end_time) if end_time else None,
                limit=limit,
            )
            return JSONResponse(result)
        
        async def api_depth_delta(request: Request) -> JSONResponse:
            symbol = request.path_params.get("symbol", "BTCUSDT")
            percent = float(request.query_params.get("percent", "1.0"))
            window_sec = int(request.query_params.get("windowSec", "5"))
            lookback = int(request.query_params.get("lookback", "100"))
            
            result = await self.api_get_orderbook_depth_delta(
                symbol=symbol,
                percent=percent,
                window_sec=window_sec,
                lookback=lookback,
            )
            return JSONResponse(result)
        
        async def api_liquidations(request: Request) -> JSONResponse:
            symbol = request.path_params.get("symbol", "BTCUSDT")
            limit = int(request.query_params.get("limit", "100"))
            
            result = await self.api_stream_liquidations(symbol, limit)
            return JSONResponse(result)
        
        routes = [
            Route("/healthz", healthz, methods=["GET"]),
            Route("/mcp", mcp_handler, methods=["POST"]),
            Route("/sse", sse_handler, methods=["GET"]),
            Route("/api/market/{symbol}", api_market_snapshot, methods=["GET"]),
            Route("/api/key-levels/{symbol}", api_key_levels, methods=["GET"]),
            Route("/api/footprint/{symbol}", api_footprint, methods=["GET"]),
            Route("/api/orderflow/{symbol}", api_orderflow_metrics, methods=["GET"]),
            Route("/api/depth-delta/{symbol}", api_depth_delta, methods=["GET"]),
            Route("/api/liquidations/{symbol}", api_liquidations, methods=["GET"]),
        ]
        
        app = Starlette(routes=routes)
        return app
    
    async def _handle_mcp_method(self, method: str, params: dict) -> Any:
        """Handle MCP method calls."""
        if method == "tools/list":
            return {"tools": self._get_tools_list()}
        
        elif method == "tools/call":
            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {})
            return await self._call_tool(tool_name, tool_args)
        
        else:
            raise ValueError(f"Unknown method: {method}")
    
    def _get_tools_list(self) -> list[dict]:
        """Get list of available MCP tools."""
        return [
            {
                "name": "get_market_snapshot",
                "description": "获取市场快照，包含价格、成交量、资金费率和持仓量",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "交易对，如 BTCUSDT、ETHUSDT",
                        },
                    },
                    "required": ["symbol"],
                },
            },
            {
                "name": "get_key_levels",
                "description": "获取关键价位：VWAP、Volume Profile (POC/VAH/VAL)、Session H/L",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "交易对"},
                        "date": {"type": "string", "description": "日期 (YYYY-MM-DD)，默认今天"},
                        "sessionTZ": {"type": "string", "description": "会话时区，默认 UTC"},
                    },
                    "required": ["symbol"],
                },
            },
            {
                "name": "get_footprint",
                "description": "获取 Footprint 柱状图，显示每个价位的买卖成交量",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "交易对"},
                        "timeframe": {"type": "string", "description": "时间周期: 1m, 5m, 15m, 30m, 1h"},
                        "startTime": {"type": "integer", "description": "开始时间 (毫秒时间戳)"},
                        "endTime": {"type": "integer", "description": "结束时间 (毫秒时间戳)"},
                    },
                    "required": ["symbol", "timeframe"],
                },
            },
            {
                "name": "get_orderflow_metrics",
                "description": "获取订单流指标：Delta、CVD、Stacked Imbalance",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "交易对"},
                        "timeframe": {"type": "string", "description": "时间周期"},
                        "startTime": {"type": "integer", "description": "开始时间"},
                        "endTime": {"type": "integer", "description": "结束时间"},
                    },
                    "required": ["symbol", "timeframe"],
                },
            },
            {
                "name": "get_orderbook_depth_delta",
                "description": "获取订单簿深度变化，监控买卖挂单变化",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "交易对"},
                        "percent": {"type": "number", "description": "价格范围百分比 (默认 1.0)"},
                        "windowSec": {"type": "integer", "description": "采样间隔秒 (默认 5)"},
                        "lookback": {"type": "integer", "description": "历史条数 (默认 100)"},
                    },
                    "required": ["symbol"],
                },
            },
            {
                "name": "stream_liquidations",
                "description": "获取最近的清算事件",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string", "description": "交易对"},
                        "limit": {"type": "integer", "description": "返回条数 (默认 100)"},
                    },
                    "required": ["symbol"],
                },
            },
        ]
    
    async def _call_tool(self, name: str, args: dict) -> dict:
        """Call an MCP tool."""
        symbol = args.get("symbol", "BTCUSDT")
        
        if name == "get_market_snapshot":
            return await self.api_get_market_snapshot(symbol)
        
        elif name == "get_key_levels":
            return await self.api_get_key_levels(
                symbol=symbol,
                date=args.get("date"),
                session_tz=args.get("sessionTZ", "UTC"),
            )
        
        elif name == "get_footprint":
            return await self.api_get_footprint(
                symbol=symbol,
                timeframe=args.get("timeframe", "1m"),
                start_time=args.get("startTime"),
                end_time=args.get("endTime"),
                limit=args.get("limit", 100),
            )
        
        elif name == "get_orderflow_metrics":
            return await self.api_get_orderflow_metrics(
                symbol=symbol,
                timeframe=args.get("timeframe", "1m"),
                start_time=args.get("startTime"),
                end_time=args.get("endTime"),
                limit=args.get("limit", 100),
            )
        
        elif name == "get_orderbook_depth_delta":
            return await self.api_get_orderbook_depth_delta(
                symbol=symbol,
                percent=args.get("percent", 1.0),
                window_sec=args.get("windowSec", 5),
                lookback=args.get("lookback", 100),
            )
        
        elif name == "stream_liquidations":
            return await self.api_stream_liquidations(
                symbol=symbol,
                limit=args.get("limit", 100),
            )
        
        else:
            raise ValueError(f"Unknown tool: {name}")
    
    async def run_http_server(self) -> None:
        """Run the HTTP server."""
        app = self.create_http_app()
        
        config = uvicorn.Config(
            app,
            host=self.config.host,
            port=self.config.port,
            log_level=self.config.log_level.lower(),
        )
        server = uvicorn.Server(config)
        
        logger.info(
            "Starting HTTP server",
            host=self.config.host,
            port=self.config.port,
        )
        
        await server.serve()
