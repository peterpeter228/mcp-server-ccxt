"""
Main entry point for Crypto Orderflow MCP Server.
"""

import asyncio
import os
import signal
import sys
from pathlib import Path
from typing import NoReturn

# Ensure project root is in path
_project_root = str(Path(__file__).parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.config import get_config
from src.server.mcp_server import CryptoMCPServer
from src.utils.logging import setup_logging, get_logger


async def main_async() -> None:
    """Async main function."""
    config = get_config()
    
    # Setup logging
    setup_logging(config.log_level, config.log_format)
    logger = get_logger(__name__)
    
    logger.info(
        "Starting Crypto Orderflow MCP Server",
        version="1.0.0",
        symbols=config.symbols,
        host=config.host,
        port=config.port,
    )
    
    # Create server
    server = CryptoMCPServer(config=config)
    
    # Setup signal handlers
    loop = asyncio.get_running_loop()
    
    async def shutdown():
        logger.info("Shutting down...")
        await server.stop()
    
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda: asyncio.create_task(shutdown()),
        )
    
    try:
        # Initialize and start
        await server.initialize()
        await server.start()
        
        # Run HTTP server
        await server.run_http_server()
        
    except Exception as e:
        logger.error("Server error", error=str(e))
        raise
    finally:
        await server.stop()


def main() -> NoReturn:
    """Main entry point."""
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\nShutdown requested...")
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)
    
    sys.exit(0)


if __name__ == "__main__":
    main()
