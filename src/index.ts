#!/usr/bin/env node
/**
 * CCXT MCP Server
 * High-performance cryptocurrency exchange interface with optimized caching and rate limiting
 * Supports STDIO and SSE transport modes
 * 
 * CCXT MCP 服务器
 * 具有优化缓存和速率限制的高性能加密货币交易所接口
 * 支持 STDIO 和 SSE 传输模式
 */

// IMPORTANT: Redirect all console output to stderr to avoid messing with MCP protocol
const originalConsoleLog = console.log;
const originalConsoleInfo = console.info;
const originalConsoleWarn = console.warn;
const originalConsoleDebug = console.debug;

console.log = (...args) => console.error('[LOG]', ...args);
console.info = (...args) => console.error('[INFO]', ...args);
console.warn = (...args) => console.error('[WARN]', ...args);
console.debug = (...args) => console.error('[DEBUG]', ...args);

// Now we can safely import modules
import { McpServer, ResourceTemplate } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { SSEServerTransport } from "@modelcontextprotocol/sdk/server/sse.js";
import { z } from "zod";
import * as ccxt from 'ccxt';
import * as http from 'http';
import * as url from 'url';
import dotenv from 'dotenv';

import { log, LogLevel, setLogLevel } from './utils/logging.js';
import { getCacheStats, clearCache } from './utils/cache.js';
import { rateLimiter } from './utils/rate-limiter.js';
import { SUPPORTED_EXCHANGES, getExchange } from './exchange/manager.js';
import { registerAllTools } from './tools/index.js';

// Load environment variables
dotenv.config();

// Server configuration
const TRANSPORT_MODE = process.env.MCP_TRANSPORT || 'stdio';
const HTTP_PORT = parseInt(process.env.MCP_HTTP_PORT || '3000', 10);
const HTTP_HOST = process.env.MCP_HTTP_HOST || '127.0.0.1';

// Create MCP server
const server = new McpServer({
  name: "CCXT MCP Server",
  version: "1.3.0",
  capabilities: {
    resources: {},
    tools: {}
  }
});

// Resource: Exchanges list
server.resource("exchanges", "ccxt://exchanges", async (uri) => {
  return {
    contents: [{
      uri: uri.href,
      text: JSON.stringify(SUPPORTED_EXCHANGES, null, 2)
    }]
  };
});

// Resource template: Markets
server.resource("markets", new ResourceTemplate("ccxt://{exchange}/markets", { list: undefined }), 
  async (uri, params) => {
    try {
      const exchange = params.exchange as string;
      const ex = getExchange(exchange);
      await ex.loadMarkets();
      
      const markets = Object.values(ex.markets).map(market => ({
        symbol: (market as any).symbol,
        base: (market as any).base,
        quote: (market as any).quote,
        active: (market as any).active,
      }));
      
      return {
        contents: [{
          uri: uri.href,
          text: JSON.stringify(markets, null, 2)
        }]
      };
    } catch (error) {
      return {
        contents: [{
          uri: uri.href,
          text: `Error fetching markets: ${error instanceof Error ? error.message : String(error)}`
        }]
      };
    }
  }
);

// Resource template: Ticker
server.resource("ticker", new ResourceTemplate("ccxt://{exchange}/ticker/{symbol}", { list: undefined }), 
  async (uri, params) => {
    try {
      const exchange = params.exchange as string;
      const symbol = params.symbol as string;
      const ex = getExchange(exchange);
      const ticker = await ex.fetchTicker(symbol);
      
      return {
        contents: [{
          uri: uri.href,
          text: JSON.stringify(ticker, null, 2)
        }]
      };
    } catch (error) {
      return {
        contents: [{
          uri: uri.href,
          text: `Error fetching ticker: ${error instanceof Error ? error.message : String(error)}`
        }]
      };
    }
  }
);

// Resource template: Order book
server.resource("order-book", new ResourceTemplate("ccxt://{exchange}/orderbook/{symbol}", { list: undefined }), 
  async (uri, params) => {
    try {
      const exchange = params.exchange as string;
      const symbol = params.symbol as string;
      const ex = getExchange(exchange);
      const orderbook = await ex.fetchOrderBook(symbol);
      
      return {
        contents: [{
          uri: uri.href,
          text: JSON.stringify(orderbook, null, 2)
        }]
      };
    } catch (error) {
      return {
        contents: [{
          uri: uri.href,
          text: `Error fetching order book: ${error instanceof Error ? error.message : String(error)}`
        }]
      };
    }
  }
);

// Cache statistics tool
server.tool("cache-stats", "Get CCXT cache statistics", {}, async () => {
  return {
    content: [{
      type: "text" as const,
      text: JSON.stringify(getCacheStats(), null, 2)
    }]
  };
});

// Cache clearing tool
server.tool("clear-cache", "Clear CCXT cache", {}, async () => {
  clearCache();
  return {
    content: [{
      type: "text" as const,
      text: "Cache cleared successfully."
    }]
  };
});

// Log level management
server.tool("set-log-level", "Set logging level", {
  level: z.enum(["debug", "info", "warning", "error"]).describe("Logging level to set")
}, async ({ level }) => {
  setLogLevel(level);
  return {
    content: [{
      type: "text" as const,
      text: `Log level set to ${level}.`
    }]
  };
});

// Store active SSE transports
const sseTransports: Map<string, SSEServerTransport> = new Map();

/**
 * Create HTTP server for SSE transport
 */
function createHttpServer(): http.Server {
  const httpServer = http.createServer(async (req, res) => {
    const parsedUrl = url.parse(req.url || '', true);
    const pathname = parsedUrl.pathname;
    
    // CORS headers
    res.setHeader('Access-Control-Allow-Origin', process.env.CORS_ORIGIN || '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Accept');
    
    if (req.method === 'OPTIONS') {
      res.writeHead(204);
      res.end();
      return;
    }
    
    // Health check endpoint
    if (pathname === '/health') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ 
        status: 'ok', 
        transport: TRANSPORT_MODE,
        activeSessions: sseTransports.size 
      }));
      return;
    }
    
    // API info endpoint
    if (pathname === '/' && req.method === 'GET') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        name: 'CCXT MCP Server',
        version: '1.3.0',
        transport: TRANSPORT_MODE,
        endpoints: {
          sse: '/sse',
          message: '/message',
          health: '/health'
        },
        activeSessions: sseTransports.size
      }, null, 2));
      return;
    }
    
    // SSE endpoint - establishes SSE connection
    if (pathname === '/sse' && req.method === 'GET') {
      const sessionId = `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
      log(LogLevel.INFO, `New SSE connection: ${sessionId}`);
      
      try {
        // Create SSE transport - it will handle writing headers
        const transport = new SSEServerTransport('/message', res);
        sseTransports.set(sessionId, transport);
        
        // Clean up on connection close
        res.on('close', () => {
          log(LogLevel.INFO, `SSE connection closed: ${sessionId}`);
          sseTransports.delete(sessionId);
        });
        
        res.on('error', (err) => {
          log(LogLevel.ERROR, `SSE connection error: ${sessionId} - ${err.message}`);
          sseTransports.delete(sessionId);
        });
        
        // Connect MCP server to this transport
        await server.connect(transport);
        log(LogLevel.INFO, `MCP connected to SSE transport: ${sessionId}`);
        
      } catch (error) {
        log(LogLevel.ERROR, `Failed to establish SSE: ${error}`);
        sseTransports.delete(sessionId);
        if (!res.headersSent) {
          res.writeHead(500, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: 'Failed to establish SSE connection' }));
        }
      }
      return;
    }
    
    // Message endpoint - receives POST messages from client
    if (pathname === '/message' && req.method === 'POST') {
      // Find an active transport to handle this message
      if (sseTransports.size === 0) {
        res.writeHead(503, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'No active SSE session. Connect to /sse first.' }));
        return;
      }
      
      // Get the transport (use first available for single-client scenarios)
      const transport = sseTransports.values().next().value;
      
      if (!transport) {
        res.writeHead(503, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'Transport not available' }));
        return;
      }
      
      try {
        await transport.handlePostMessage(req, res);
      } catch (error) {
        log(LogLevel.ERROR, `Error handling message: ${error}`);
        if (!res.headersSent) {
          res.writeHead(500, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: 'Internal server error' }));
        }
      }
      return;
    }
    
    // 404 for unknown paths
    res.writeHead(404, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Not found', path: pathname }));
  });
  
  return httpServer;
}

// Start the server
async function main() {
  try {
    log(LogLevel.INFO, `Starting CCXT MCP Server (transport: ${TRANSPORT_MODE})...`);
    
    // Register all tools
    registerAllTools(server);
    
    if (TRANSPORT_MODE === 'stdio') {
      const transport = new StdioServerTransport();
      await server.connect(transport);
      log(LogLevel.INFO, "CCXT MCP Server is running (STDIO mode)");
    } else if (TRANSPORT_MODE === 'sse') {
      const httpServer = createHttpServer();
      
      httpServer.listen(HTTP_PORT, HTTP_HOST, () => {
        log(LogLevel.INFO, `CCXT MCP Server is running (SSE mode)`);
        log(LogLevel.INFO, `Listening on http://${HTTP_HOST}:${HTTP_PORT}`);
        log(LogLevel.INFO, `SSE endpoint: http://${HTTP_HOST}:${HTTP_PORT}/sse`);
        log(LogLevel.INFO, `Message endpoint: http://${HTTP_HOST}:${HTTP_PORT}/message`);
      });
      
      // Graceful shutdown
      const shutdown = () => {
        log(LogLevel.INFO, 'Shutting down server...');
        httpServer.close(() => {
          log(LogLevel.INFO, 'Server shut down');
          process.exit(0);
        });
      };
      
      process.on('SIGINT', shutdown);
      process.on('SIGTERM', shutdown);
    } else {
      throw new Error(`Unknown transport mode: ${TRANSPORT_MODE}. Use 'stdio' or 'sse'`);
    }
  } catch (error) {
    log(LogLevel.ERROR, `Failed to start server: ${error instanceof Error ? error.message : String(error)}`);
    process.exit(1);
  }
}

// Handle process signals
process.on('uncaughtException', (error) => {
  log(LogLevel.ERROR, `Uncaught exception: ${error.message}`);
  log(LogLevel.ERROR, error.stack || 'No stack trace');
});

process.on('unhandledRejection', (reason) => {
  log(LogLevel.ERROR, `Unhandled rejection: ${reason}`);
});

// Export for programmatic use
export { server, createHttpServer };

// Start the MCP server
main();
