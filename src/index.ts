#!/usr/bin/env node
/**
 * CCXT MCP Server
 * High-performance cryptocurrency exchange interface with optimized caching and rate limiting
 * Supports STDIO, HTTP Streamable, and SSE transport modes
 * 
 * CCXT MCP 服务器
 * 具有优化缓存和速率限制的高性能加密货币交易所接口
 * 支持 STDIO、HTTP Streamable 和 SSE 传输模式
 */

// IMPORTANT: Redirect all console output to stderr to avoid messing with MCP protocol
// This must be done before any imports that may log to console
// 重要：将所有控制台输出重定向到stderr，避免干扰MCP协议
// 这必须在任何可能记录到控制台的导入之前完成
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
// 加载环境变量
dotenv.config();

// Server configuration
// 服务器配置
const TRANSPORT_MODE = process.env.MCP_TRANSPORT || 'stdio'; // 'stdio', 'sse', 'http-stream'
const HTTP_PORT = parseInt(process.env.MCP_HTTP_PORT || '3000', 10);
const HTTP_HOST = process.env.MCP_HTTP_HOST || '127.0.0.1';

// Create MCP server
// 创建MCP服务器
const server = new McpServer({
  name: "CCXT MCP Server",
  version: "1.2.0",
  capabilities: {
    resources: {},
    tools: {}
  }
});

// Resource: Exchanges list
// 资源：交易所列表
server.resource("exchanges", "ccxt://exchanges", async (uri) => {
  return {
    contents: [{
      uri: uri.href,
      text: JSON.stringify(SUPPORTED_EXCHANGES, null, 2)
    }]
  };
});

// Resource template: Markets
// 资源模板：市场
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
// 资源模板：行情
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
// 资源模板：订单簿
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
// 缓存统计工具
server.tool("cache-stats", "Get CCXT cache statistics", {}, async () => {
  return {
    content: [{
      type: "text",
      text: JSON.stringify(getCacheStats(), null, 2)
    }]
  };
});

// Cache clearing tool
// 缓存清理工具
server.tool("clear-cache", "Clear CCXT cache", {}, async () => {
  clearCache();
  return {
    content: [{
      type: "text",
      text: "Cache cleared successfully."
    }]
  };
});

// Log level management
// 日志级别管理
server.tool("set-log-level", "Set logging level", {
  level: z.enum(["debug", "info", "warning", "error"]).describe("Logging level to set")
}, async ({ level }) => {
  setLogLevel(level);
  return {
    content: [{
      type: "text",
      text: `Log level set to ${level}.`
    }]
  };
});

// Active SSE transports for HTTP mode
// HTTP模式下的活跃SSE传输
const activeTransports = new Map<string, SSEServerTransport>();

/**
 * Create HTTP server for SSE/HTTP-Stream transport
 * 为SSE/HTTP-Stream传输创建HTTP服务器
 */
function createHttpServer(): http.Server {
  const httpServer = http.createServer(async (req, res) => {
    const parsedUrl = url.parse(req.url || '', true);
    const pathname = parsedUrl.pathname;
    
    // CORS headers
    res.setHeader('Access-Control-Allow-Origin', process.env.CORS_ORIGIN || '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
    
    if (req.method === 'OPTIONS') {
      res.writeHead(204);
      res.end();
      return;
    }
    
    // Health check endpoint
    if (pathname === '/health') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ status: 'ok', transport: TRANSPORT_MODE }));
      return;
    }
    
    // SSE endpoint
    if (pathname === '/sse' && req.method === 'GET') {
      log(LogLevel.INFO, 'New SSE connection');
      
      const transport = new SSEServerTransport('/messages', res);
      const sessionId = Date.now().toString(36) + Math.random().toString(36).substring(2);
      activeTransports.set(sessionId, transport);
      
      // Handle connection close
      req.on('close', () => {
        log(LogLevel.INFO, `SSE connection closed: ${sessionId}`);
        activeTransports.delete(sessionId);
      });
      
      try {
        await server.connect(transport);
      } catch (error) {
        log(LogLevel.ERROR, `SSE connection error: ${error}`);
        activeTransports.delete(sessionId);
      }
      return;
    }
    
    // Message endpoint for SSE
    if (pathname === '/messages' && req.method === 'POST') {
      let body = '';
      req.on('data', chunk => { body += chunk; });
      req.on('end', async () => {
        try {
          // Find the transport and handle the message
          // The SSEServerTransport handles this internally
          res.writeHead(202, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ status: 'accepted' }));
        } catch (error) {
          res.writeHead(500, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: String(error) }));
        }
      });
      return;
    }
    
    // HTTP Streamable endpoint
    if (pathname === '/mcp' && req.method === 'POST') {
      let body = '';
      req.on('data', chunk => { body += chunk; });
      req.on('end', async () => {
        try {
          const request = JSON.parse(body);
          log(LogLevel.DEBUG, `HTTP request: ${JSON.stringify(request)}`);
          
          // For HTTP streamable, we need to create a one-shot SSE response
          res.writeHead(200, {
            'Content-Type': 'text/event-stream',
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive'
          });
          
          // Create a temporary SSE transport for this request
          const transport = new SSEServerTransport('/mcp', res);
          
          try {
            await server.connect(transport);
            // Send the request through the transport
            await transport.handlePostMessage(req, res, body);
          } catch (error) {
            log(LogLevel.ERROR, `HTTP stream error: ${error}`);
          }
        } catch (error) {
          res.writeHead(400, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ error: 'Invalid JSON' }));
        }
      });
      return;
    }
    
    // API info endpoint
    if (pathname === '/' && req.method === 'GET') {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        name: 'CCXT MCP Server',
        version: '1.2.0',
        transport: TRANSPORT_MODE,
        endpoints: {
          sse: '/sse',
          messages: '/messages',
          httpStream: '/mcp',
          health: '/health'
        },
        documentation: 'https://github.com/doggybee/mcp-server-ccxt'
      }, null, 2));
      return;
    }
    
    // 404 for unknown paths
    res.writeHead(404, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Not found' }));
  });
  
  return httpServer;
}

// Start the server
// 启动服务器
async function main() {
  try {
    log(LogLevel.INFO, `Starting CCXT MCP Server (transport: ${TRANSPORT_MODE})...`);
    
    // Register all tools
    registerAllTools(server);
    
    if (TRANSPORT_MODE === 'stdio') {
      // Configure transport to use pure stdio
      // 配置传输以使用纯stdio
      const transport = new StdioServerTransport();
      
      // Connect to stdio transport
      await server.connect(transport);
      
      log(LogLevel.INFO, "CCXT MCP Server is running (STDIO mode)");
    } else if (TRANSPORT_MODE === 'sse' || TRANSPORT_MODE === 'http-stream') {
      // Start HTTP server for SSE/HTTP-Stream
      // 启动HTTP服务器用于SSE/HTTP-Stream
      const httpServer = createHttpServer();
      
      httpServer.listen(HTTP_PORT, HTTP_HOST, () => {
        log(LogLevel.INFO, `CCXT MCP Server is running (${TRANSPORT_MODE.toUpperCase()} mode)`);
        log(LogLevel.INFO, `Listening on http://${HTTP_HOST}:${HTTP_PORT}`);
        log(LogLevel.INFO, `SSE endpoint: http://${HTTP_HOST}:${HTTP_PORT}/sse`);
        log(LogLevel.INFO, `HTTP Stream endpoint: http://${HTTP_HOST}:${HTTP_PORT}/mcp`);
      });
      
      // Graceful shutdown
      process.on('SIGINT', () => {
        log(LogLevel.INFO, 'Shutting down server...');
        httpServer.close(() => {
          log(LogLevel.INFO, 'Server shut down');
          process.exit(0);
        });
      });
      
      process.on('SIGTERM', () => {
        log(LogLevel.INFO, 'Shutting down server...');
        httpServer.close(() => {
          log(LogLevel.INFO, 'Server shut down');
          process.exit(0);
        });
      });
    } else {
      throw new Error(`Unknown transport mode: ${TRANSPORT_MODE}. Use 'stdio', 'sse', or 'http-stream'`);
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

// Export server for programmatic use
export { server, createHttpServer };

// Start the MCP server
main();