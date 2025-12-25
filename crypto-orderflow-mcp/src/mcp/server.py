"""MCP Server implementation with SSE and Streamable HTTP transport."""

import asyncio
import json
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from mcp.server import Server
from mcp.types import Tool, TextContent

from src.config import get_settings
from src.utils import get_logger, timestamp_ms
from .tools import MCPTools


def create_mcp_server(tools: MCPTools) -> tuple[FastAPI, Server]:
    """Create FastAPI app with MCP Server.
    
    Args:
        tools: MCPTools instance with all indicators
    
    Returns:
        Tuple of (FastAPI app, MCP Server)
    """
    settings = get_settings()
    logger = get_logger("mcp.server")
    
    # Create MCP Server
    mcp = Server("crypto-orderflow-mcp")
    
    # Define tools
    @mcp.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="get_market_snapshot",
                description="Get real-time market snapshot including latest price, mark price, 24h stats, funding rate, and open interest for a trading pair.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "Trading pair symbol (e.g., 'BTCUSDT', 'ETHUSDT')",
                        },
                    },
                    "required": ["symbol"],
                },
            ),
            Tool(
                name="get_key_levels",
                description="Get key price levels including developing VWAP (dVWAP), previous day VWAP (pdVWAP), Volume Profile (POC, VAH, VAL), and session high/low (Tokyo, London, NY).",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "Trading pair symbol",
                        },
                        "date": {
                            "type": "string",
                            "description": "Date in YYYY-MM-DD format (optional, defaults to today)",
                        },
                        "sessionTZ": {
                            "type": "string",
                            "description": "Session timezone (default: UTC)",
                            "default": "UTC",
                        },
                    },
                    "required": ["symbol"],
                },
            ),
            Tool(
                name="get_footprint",
                description="Get footprint bars showing buy/sell volume distribution by price level for each candle in the specified timeframe.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "Trading pair symbol",
                        },
                        "timeframe": {
                            "type": "string",
                            "description": "Candle timeframe (1m, 5m, 15m, 30m, 1h)",
                            "enum": ["1m", "5m", "15m", "30m", "1h"],
                        },
                        "startTime": {
                            "type": "integer",
                            "description": "Start timestamp in milliseconds",
                        },
                        "endTime": {
                            "type": "integer",
                            "description": "End timestamp in milliseconds",
                        },
                    },
                    "required": ["symbol", "timeframe", "startTime", "endTime"],
                },
            ),
            Tool(
                name="get_orderflow_metrics",
                description="Get orderflow metrics including delta bars, cumulative volume delta (CVD), and stacked imbalance detection.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "Trading pair symbol",
                        },
                        "timeframe": {
                            "type": "string",
                            "description": "Candle timeframe",
                            "enum": ["1m", "5m", "15m", "30m", "1h"],
                        },
                        "startTime": {
                            "type": "integer",
                            "description": "Start timestamp in milliseconds",
                        },
                        "endTime": {
                            "type": "integer",
                            "description": "End timestamp in milliseconds",
                        },
                    },
                    "required": ["symbol", "timeframe", "startTime", "endTime"],
                },
            ),
            Tool(
                name="get_orderbook_depth_delta",
                description="Get orderbook depth delta showing bid/ask volume changes within a price range over time.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "Trading pair symbol",
                        },
                        "percent": {
                            "type": "number",
                            "description": "Price range percentage from mid price (default: 1.0 for ±1%)",
                            "default": 1.0,
                        },
                        "windowSec": {
                            "type": "integer",
                            "description": "Snapshot interval in seconds (default: 5)",
                            "default": 5,
                        },
                        "lookback": {
                            "type": "integer",
                            "description": "Lookback period in seconds (default: 3600 for 1 hour)",
                            "default": 3600,
                        },
                    },
                    "required": ["symbol"],
                },
            ),
            Tool(
                name="stream_liquidations",
                description="Get recent liquidation events (forced position closures) for a trading pair.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "Trading pair symbol",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of liquidations to return (default: 100)",
                            "default": 100,
                        },
                    },
                    "required": ["symbol"],
                },
            ),
            Tool(
                name="get_open_interest",
                description="Get open interest data including current value and historical changes.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "Trading pair symbol",
                        },
                        "period": {
                            "type": "string",
                            "description": "Historical period (5m, 15m, 30m, 1h, 2h, 4h, 6h, 12h, 1d)",
                            "default": "5m",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Number of historical records (default: 100)",
                            "default": 100,
                        },
                    },
                    "required": ["symbol"],
                },
            ),
            Tool(
                name="get_funding_rate",
                description="Get current and historical funding rate for perpetual futures.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "symbol": {
                            "type": "string",
                            "description": "Trading pair symbol",
                        },
                    },
                    "required": ["symbol"],
                },
            ),
        ]
    
    @mcp.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        logger.info("tool_called", name=name, arguments=arguments)
        
        try:
            if name == "get_market_snapshot":
                result = await tools.get_market_snapshot(arguments["symbol"])
            
            elif name == "get_key_levels":
                result = await tools.get_key_levels(
                    symbol=arguments["symbol"],
                    date=arguments.get("date"),
                    session_tz=arguments.get("sessionTZ", "UTC"),
                )
            
            elif name == "get_footprint":
                result = await tools.get_footprint(
                    symbol=arguments["symbol"],
                    timeframe=arguments["timeframe"],
                    start_time=arguments["startTime"],
                    end_time=arguments["endTime"],
                )
            
            elif name == "get_orderflow_metrics":
                result = await tools.get_orderflow_metrics(
                    symbol=arguments["symbol"],
                    timeframe=arguments["timeframe"],
                    start_time=arguments["startTime"],
                    end_time=arguments["endTime"],
                )
            
            elif name == "get_orderbook_depth_delta":
                result = await tools.get_orderbook_depth_delta(
                    symbol=arguments["symbol"],
                    percent=arguments.get("percent", 1.0),
                    window_sec=arguments.get("windowSec", 5),
                    lookback=arguments.get("lookback", 3600),
                )
            
            elif name == "stream_liquidations":
                result = await tools.stream_liquidations(
                    symbol=arguments["symbol"],
                    limit=arguments.get("limit", 100),
                )
            
            elif name == "get_open_interest":
                result = await tools.get_open_interest(
                    symbol=arguments["symbol"],
                    period=arguments.get("period", "5m"),
                    limit=arguments.get("limit", 100),
                )
            
            elif name == "get_funding_rate":
                result = await tools.get_funding_rate(arguments["symbol"])
            
            else:
                result = {"error": f"Unknown tool: {name}"}
            
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
        except Exception as e:
            logger.error("tool_error", name=name, error=str(e))
            return [TextContent(type="text", text=json.dumps({"error": str(e)}))]
    
    # Helper function to handle tool calls
    async def handle_tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Handle a tool call and return the result."""
        contents = await call_tool(name, arguments)
        return {"content": [{"type": c.type, "text": c.text} for c in contents]}
    
    # Helper function to list tools
    async def handle_list_tools() -> dict[str, Any]:
        """List available tools."""
        tool_list = await list_tools()
        return {
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "inputSchema": t.inputSchema,
                }
                for t in tool_list
            ]
        }
    
    # Create FastAPI app
    app = FastAPI(
        title="Crypto Orderflow MCP Server",
        description="Market Data & Orderflow Indicators for Binance USD-M Futures",
        version="1.0.0",
    )
    
    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    @app.get("/healthz")
    async def health_check():
        """Health check endpoint."""
        return {
            "status": "healthy",
            "timestamp": timestamp_ms(),
            "service": "crypto-orderflow-mcp",
            "version": "1.0.0",
        }
    
    @app.get("/")
    async def root():
        """Root endpoint with server info."""
        return {
            "name": "Crypto Orderflow MCP Server",
            "version": "1.0.0",
            "description": "Market Data & Orderflow Indicators for Binance USD-M Futures",
            "endpoints": {
                "sse": "/sse",
                "mcp": "/mcp",
                "health": "/healthz",
            },
            "tools": [
                "get_market_snapshot",
                "get_key_levels",
                "get_footprint",
                "get_orderflow_metrics",
                "get_orderbook_depth_delta",
                "stream_liquidations",
                "get_open_interest",
                "get_funding_rate",
            ],
            "symbols": settings.symbol_list,
        }
    
    @app.get("/sse")
    async def sse_endpoint(request: Request):
        """SSE endpoint for MCP transport - sends server info and keeps connection."""
        logger.info("sse_connection_started")
        
        async def event_stream():
            # Send initial connection event
            init_data = {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {
                        "name": "crypto-orderflow-mcp",
                        "version": "1.0.0",
                    },
                    "capabilities": {
                        "tools": {},
                    },
                }
            }
            yield f"data: {json.dumps(init_data)}\n\n"
            
            # Keep connection alive with heartbeat
            while True:
                await asyncio.sleep(30)
                yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': timestamp_ms()})}\n\n"
        
        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
    
    @app.post("/sse")
    async def sse_message_endpoint(request: Request):
        """Handle SSE POST messages (tool calls)."""
        try:
            body = await request.json()
            method = body.get("method")
            params = body.get("params", {})
            request_id = body.get("id")
            
            logger.info("sse_message", method=method)
            
            if method == "tools/list":
                result = await handle_list_tools()
            elif method == "tools/call":
                result = await handle_tool_call(params.get("name"), params.get("arguments", {}))
            elif method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {
                        "name": "crypto-orderflow-mcp",
                        "version": "1.0.0",
                    },
                    "capabilities": {
                        "tools": {},
                    },
                }
            else:
                return JSONResponse(
                    status_code=400,
                    content={
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32601, "message": f"Method not found: {method}"},
                    },
                )
            
            return JSONResponse(content={"jsonrpc": "2.0", "id": request_id, "result": result})
        
        except Exception as e:
            logger.error("sse_message_error", error=str(e))
            return JSONResponse(
                status_code=500,
                content={"jsonrpc": "2.0", "id": None, "error": {"code": -32603, "message": str(e)}},
            )
    
    @app.post("/mcp")
    async def mcp_endpoint(request: Request):
        """Streamable HTTP endpoint for MCP."""
        try:
            body = await request.json()
            method = body.get("method")
            params = body.get("params", {})
            request_id = body.get("id")
            
            logger.info("mcp_request", method=method, params=params)
            
            if method == "tools/list":
                result = await handle_list_tools()
            
            elif method == "tools/call":
                result = await handle_tool_call(params.get("name"), params.get("arguments", {}))
            
            elif method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {
                        "name": "crypto-orderflow-mcp",
                        "version": "1.0.0",
                    },
                    "capabilities": {
                        "tools": {},
                    },
                }
            
            else:
                return JSONResponse(
                    status_code=400,
                    content={
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32601,
                            "message": f"Method not found: {method}",
                        },
                    },
                )
            
            return JSONResponse(
                content={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": result,
                }
            )
        
        except Exception as e:
            logger.error("mcp_error", error=str(e))
            return JSONResponse(
                status_code=500,
                content={
                    "jsonrpc": "2.0",
                    "id": body.get("id") if 'body' in locals() else None,
                    "error": {
                        "code": -32603,
                        "message": str(e),
                    },
                },
            )
    
    return app, mcp
