"""Main entry point for Crypto Orderflow MCP Server."""

import asyncio
import signal
import sys
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uvicorn
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from src.config import get_settings
from src.utils import setup_logging, get_logger, timestamp_ms
from src.utils.helpers import get_day_start_ms
from src.binance import BinanceRestClient, BinanceWebSocketClient, Trade, Liquidation, MarkPrice, OrderbookUpdate
from src.data import DataStorage, MemoryCache, OrderbookManager
from src.indicators import (
    VWAPCalculator,
    VolumeProfileCalculator,
    SessionLevelsCalculator,
    FootprintCalculator,
    DeltaCVDCalculator,
    ImbalanceDetector,
    DepthDeltaCalculator,
)
from src.mcp import create_mcp_server, MCPTools


class CryptoOrderflowServer:
    """Main server orchestrating all components."""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger("server")
        
        # Clients
        self.rest_client = BinanceRestClient()
        self.ws_client = BinanceWebSocketClient()
        
        # Data layer
        self.storage = DataStorage()
        self.cache = MemoryCache()
        self.orderbook = OrderbookManager(self.rest_client)
        
        # Indicators
        self.vwap = VWAPCalculator(self.storage)
        self.volume_profile = VolumeProfileCalculator(self.storage)
        self.session_levels = SessionLevelsCalculator(self.storage)
        self.footprint = FootprintCalculator(self.storage)
        self.delta_cvd = DeltaCVDCalculator(self.storage)
        self.imbalance = ImbalanceDetector()
        self.depth_delta = DepthDeltaCalculator(self.storage, self.orderbook)
        
        # MCP Tools
        self.tools = MCPTools(
            cache=self.cache,
            storage=self.storage,
            orderbook=self.orderbook,
            rest_client=self.rest_client,
            vwap=self.vwap,
            volume_profile=self.volume_profile,
            session_levels=self.session_levels,
            footprint=self.footprint,
            delta_cvd=self.delta_cvd,
            imbalance=self.imbalance,
            depth_delta=self.depth_delta,
        )
        
        # Tasks
        self._background_tasks: list[asyncio.Task] = []
        self._running = False
    
    async def _handle_trade(self, trade: Trade) -> None:
        """Process incoming trade from WebSocket."""
        # Update cache
        await self.cache.update_trade(trade)
        
        # Update indicators
        await self.vwap.update(
            symbol=trade.symbol,
            price=trade.price,
            volume=trade.quantity,
            timestamp=trade.timestamp,
        )
        
        await self.volume_profile.update(
            symbol=trade.symbol,
            price=trade.price,
            volume=trade.quantity,
            buy_volume=trade.buy_volume,
            sell_volume=trade.sell_volume,
            timestamp=trade.timestamp,
        )
        
        await self.session_levels.update(
            symbol=trade.symbol,
            price=trade.price,
            volume=trade.quantity,
            timestamp=trade.timestamp,
        )
        
        await self.footprint.update(
            symbol=trade.symbol,
            price=trade.price,
            volume=trade.quantity,
            is_buyer_maker=trade.is_buyer_maker,
            timestamp=trade.timestamp,
        )
        
        await self.delta_cvd.update(
            symbol=trade.symbol,
            volume=trade.quantity,
            is_buyer_maker=trade.is_buyer_maker,
            timestamp=trade.timestamp,
        )
    
    async def _handle_orderbook_update(self, update: OrderbookUpdate) -> None:
        """Process orderbook update from WebSocket."""
        await self.orderbook.process_update(update)
    
    async def _handle_mark_price(self, data: MarkPrice) -> None:
        """Process mark price update from WebSocket."""
        await self.cache.update_mark_price(data)
    
    async def _handle_liquidation(self, liq: Liquidation) -> None:
        """Process liquidation event from WebSocket."""
        await self.cache.add_liquidation(liq)
        self.logger.info("liquidation", 
                        symbol=liq.symbol, 
                        side=liq.side, 
                        qty=liq.original_qty,
                        price=liq.price)
    
    async def _depth_delta_task(self) -> None:
        """Periodically take depth delta snapshots."""
        while self._running:
            try:
                for symbol in self.settings.symbol_list:
                    if await self.depth_delta.should_take_snapshot(symbol):
                        await self.depth_delta.take_snapshot(symbol)
                
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("depth_delta_task_error", error=str(e))
                await asyncio.sleep(5)
    
    async def _ticker_update_task(self) -> None:
        """Periodically update ticker data from REST API."""
        while self._running:
            try:
                for symbol in self.settings.symbol_list:
                    ticker = await self.rest_client.get_ticker_24h(symbol)
                    await self.cache.update_ticker(
                        symbol=symbol,
                        high_24h=ticker.high_price,
                        low_24h=ticker.low_price,
                        volume_24h=ticker.volume,
                        quote_volume_24h=ticker.quote_volume,
                    )
                    
                    # Also update OI
                    try:
                        oi = await self.rest_client.get_open_interest(symbol)
                        await self.cache.update_open_interest(
                            symbol=symbol,
                            oi=oi.open_interest,
                            oi_notional=oi.open_interest_notional,
                        )
                    except Exception as e:
                        self.logger.error("oi_update_error", symbol=symbol, error=str(e))
                
                await asyncio.sleep(10)  # Update every 10 seconds
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("ticker_update_error", error=str(e))
                await asyncio.sleep(30)
    
    async def _cleanup_task(self) -> None:
        """Periodically cleanup old data."""
        while self._running:
            try:
                await asyncio.sleep(3600)  # Run hourly
                deleted = await self.storage.cleanup_old_data()
                self.logger.info("cleanup_complete", deleted_records=deleted)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("cleanup_task_error", error=str(e))
    
    async def _day_rollover_task(self) -> None:
        """Handle day rollover for indicators."""
        while self._running:
            try:
                # Wait until next day start
                now = timestamp_ms()
                next_day = get_day_start_ms(now) + 86_400_000
                wait_ms = next_day - now
                
                await asyncio.sleep(wait_ms / 1000)
                
                # Reset daily indicators
                for symbol in self.settings.symbol_list:
                    self.vwap.reset_day(symbol)
                    self.volume_profile.reset_day(symbol)
                    self.session_levels.reset_day(symbol)
                    self.cache.reset_cvd(symbol)
                
                self.logger.info("day_rollover_complete")
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("day_rollover_error", error=str(e))
                await asyncio.sleep(60)
    
    async def start(self) -> None:
        """Start all server components."""
        self.logger.info("starting_server", 
                        symbols=self.settings.symbol_list,
                        port=self.settings.mcp_port)
        
        self._running = True
        
        # Initialize storage
        await self.storage.initialize()
        
        # Initialize orderbooks (non-blocking, will retry in background)
        for symbol in self.settings.symbol_list:
            try:
                await self.orderbook.initialize_orderbook(symbol)
            except Exception as e:
                self.logger.warning("orderbook_init_skipped", symbol=symbol, error=str(e))
        
        # Register WebSocket callbacks
        self.ws_client.on_trade(self._handle_trade)
        self.ws_client.on_orderbook(self._handle_orderbook_update)
        self.ws_client.on_mark_price(self._handle_mark_price)
        self.ws_client.on_liquidation(self._handle_liquidation)
        
        # Start WebSocket connections (non-blocking)
        try:
            await self.ws_client.start(self.settings.symbol_list)
        except Exception as e:
            self.logger.warning("websocket_start_skipped", error=str(e))
        
        # Start background tasks
        self._background_tasks = [
            asyncio.create_task(self._depth_delta_task()),
            asyncio.create_task(self._ticker_update_task()),
            asyncio.create_task(self._cleanup_task()),
            asyncio.create_task(self._day_rollover_task()),
        ]
        
        # Initial ticker fetch (non-blocking)
        for symbol in self.settings.symbol_list:
            try:
                ticker = await self.rest_client.get_ticker_24h(symbol)
                await self.cache.update_ticker(
                    symbol=symbol,
                    high_24h=ticker.high_price,
                    low_24h=ticker.low_price,
                    volume_24h=ticker.volume,
                    quote_volume_24h=ticker.quote_volume,
                )
            except Exception as e:
                self.logger.warning("initial_ticker_fetch_skipped", symbol=symbol, error=str(e))
        
        self.logger.info("server_started")
    
    async def stop(self) -> None:
        """Stop all server components."""
        self.logger.info("stopping_server")
        self._running = False
        
        # Cancel background tasks
        for task in self._background_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        self._background_tasks.clear()
        
        # Stop WebSocket
        await self.ws_client.stop()
        
        # Close REST client
        await self.rest_client.close()
        
        # Close storage
        await self.storage.close()
        
        self.logger.info("server_stopped")


# Global server instance
server: CryptoOrderflowServer | None = None


@asynccontextmanager
async def lifespan(app):
    """FastAPI lifespan context manager."""
    global server
    
    if server:
        await server.start()
    
    yield
    
    if server:
        await server.stop()


def main():
    """Main entry point."""
    global server
    
    # Setup logging
    setup_logging()
    logger = get_logger("main")
    
    settings = get_settings()
    
    # Create server
    server = CryptoOrderflowServer()
    
    # Create MCP app
    app, mcp = create_mcp_server(server.tools)
    
    # Add lifespan
    app.router.lifespan_context = lifespan
    
    # Handle signals
    def signal_handler(sig, frame):
        logger.info("shutdown_signal_received", signal=sig)
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info("starting_uvicorn", 
               host=settings.mcp_host, 
               port=settings.mcp_port)
    
    # Run uvicorn
    uvicorn.run(
        app,
        host=settings.mcp_host,
        port=settings.mcp_port,
        log_level=settings.log_level.lower(),
        access_log=settings.debug,
    )


if __name__ == "__main__":
    main()
