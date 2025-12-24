"""
MCP Server implementation with SSE and Streamable HTTP support.
"""

import asyncio
import json
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Deque

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.responses import JSONResponse, Response
from starlette.requests import Request
from sse_starlette.sse import EventSourceResponse
import uvicorn

from ..config import get_config
from ..utils import get_logger, setup_logging, get_utc_now_ms
from ..data import BinanceRestClient, BinanceWebSocketClient, OrderbookManager, TradeAggregator, AggregatedTrade
from ..data.binance_ws import StreamType, BinanceAllMarketsWebSocket
from ..indicators import (
    VWAPCalculator,
    VolumeProfileCalculator,
    SessionLevelCalculator,
    FootprintCalculator,
    DeltaCVDCalculator,
    ImbalanceDetector,
    DepthDeltaCalculator,
)
from ..storage import SQLiteStore, DataCache
from ..tools import (
    get_market_snapshot,
    get_key_levels,
    get_footprint,
    get_orderflow_metrics,
    get_orderbook_depth_delta,
    stream_liquidations,
)

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
    depth_delta_calculator: DepthDeltaCalculator | None = None
    
    # Liquidation buffer
    liquidation_buffer: dict[str, Deque[dict]] = field(default_factory=dict)
    
    # State
    _running: bool = False
    _mcp_server: Server | None = None
    
    async def initialize(self) -> None:
        """Initialize all components."""
        logger.info("Initializing Crypto MCP Server...")
        
        # Setup logging
        setup_logging(self.config.log_level, self.config.log_format)
        
        # Connect to database
        await self.store.connect()
        
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
            self.session_level_calculators[symbol] = SessionLevelCalculator(
                symbol=symbol,
                sessions=self.config.sessions,
            )
            self.footprint_calculators[symbol] = FootprintCalculator(
                aggregator=self.trade_aggregators[symbol]
            )
            self.delta_cvd_calculators[symbol] = DeltaCVDCalculator(
                aggregator=self.trade_aggregators[symbol]
            )
            self.imbalance_detectors[symbol] = ImbalanceDetector(
                aggregator=self.trade_aggregators[symbol],
                ratio_threshold=self.config.imbalance_ratio_threshold,
                consecutive_count=self.config.imbalance_consecutive_count,
            )
            
            # Liquidation buffer
            self.liquidation_buffer[symbol] = deque(maxlen=1000)
        
        # Initialize orderbook manager
        self.orderbook_manager = OrderbookManager(
            rest_client=self.rest_client,
            ws_client=self.ws_client,
            symbols=self.config.symbols,
            depth_limit=self.config.orderbook_depth_levels,
            resync_interval=self.config.orderbook_sync_interval,
        )
        
        # Initialize depth delta calculator
        self.depth_delta_calculator = DepthDeltaCalculator(
            orderbook_manager=self.orderbook_manager,
            percent_range=self.config.depth_delta_percent,
            sample_interval_sec=self.config.depth_delta_interval_sec,
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
        
        # Start depth delta calculator
        await self.depth_delta_calculator.start()
        
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
        if self.depth_delta_calculator:
            await self.depth_delta_calculator.stop()
        
        await self.rest_client.close()
        await self.store.close()
        
        logger.info("Crypto MCP Server stopped")
    
    async def _on_trade(self, data: dict) -> None:
        """Handle incoming trade from WebSocket."""
        try:
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
            
            if symbol in self.liquidation_buffer:
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
                
                self.liquidation_buffer[symbol].append(liq_event)
                
                # Also save to database
                await self.store.save_liquidation(
                    symbol=symbol,
                    side=liq_event["side"],
                    price=liq_event["price"],
                    quantity=liq_event["quantity"],
                    timestamp=liq_event["timestamp"],
                    order_type=liq_event["orderType"],
                    time_in_force=liq_event["timeInForce"],
                )
        except Exception as e:
            logger.error("Error processing liquidation", error=str(e))
    
    async def _cleanup_loop(self) -> None:
        """Periodic cleanup task."""
        while self._running:
            try:
                # Clean old data from database
                await self.store.cleanup_old_data()
                
                # Clean cache
                await self.cache.cleanup()
                
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
        return await get_orderbook_depth_delta(
            symbol=symbol,
            percent=percent,
            window_sec=window_sec,
            lookback=lookback,
            depth_delta_calc=self.depth_delta_calculator,
            orderbook_manager=self.orderbook_manager,
        )
    
    async def api_stream_liquidations(
        self,
        symbol: str,
        limit: int = 100,
    ) -> dict:
        """Get recent liquidations for a symbol."""
        return await stream_liquidations(
            symbol=symbol,
            limit=limit,
            liq_buffer=self.liquidation_buffer.get(symbol),
            store=self.store,
        )
    
    def get_health(self) -> dict:
        """Get server health status."""
        return {
            "status": "healthy" if self._running else "stopped",
            "timestamp": get_utc_now_ms(),
            "symbols": self.config.symbols,
            "websocket": self.ws_client.get_status(),
            "orderbook": self.orderbook_manager.get_status() if self.orderbook_manager else None,
            "cache": self.cache.get_stats(),
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
                        "id": body.get("id") if "body" in dir() else None,
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
                "description": "Get market snapshot including price, volume, funding, and OI",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "Trading pair symbol (e.g., BTCUSDT)",
                        },
                    },
                    "required": ["symbol"],
                },
            },
            {
                "name": "get_key_levels",
                "description": "Get key levels: VWAP, Volume Profile (POC/VAH/VAL), Session H/L",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "date": {"type": "string", "description": "Date (YYYY-MM-DD), defaults to today"},
                        "sessionTZ": {"type": "string", "description": "Session timezone, defaults to UTC"},
                    },
                    "required": ["symbol"],
                },
            },
            {
                "name": "get_footprint",
                "description": "Get footprint bars with volume by price level",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "timeframe": {"type": "string", "description": "1m, 5m, 15m, 30m, 1h"},
                        "startTime": {"type": "integer", "description": "Start time (ms)"},
                        "endTime": {"type": "integer", "description": "End time (ms)"},
                    },
                    "required": ["symbol", "timeframe"],
                },
            },
            {
                "name": "get_orderflow_metrics",
                "description": "Get orderflow metrics: delta, CVD, imbalances",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "timeframe": {"type": "string"},
                        "startTime": {"type": "integer"},
                        "endTime": {"type": "integer"},
                    },
                    "required": ["symbol", "timeframe"],
                },
            },
            {
                "name": "get_orderbook_depth_delta",
                "description": "Get orderbook depth delta within price range",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "percent": {"type": "number", "description": "Price range % (default 1.0)"},
                        "windowSec": {"type": "integer", "description": "Sample interval (default 5)"},
                        "lookback": {"type": "integer", "description": "Number of samples (default 100)"},
                    },
                    "required": ["symbol"],
                },
            },
            {
                "name": "stream_liquidations",
                "description": "Get recent liquidation events",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "limit": {"type": "integer", "description": "Max events (default 100)"},
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
