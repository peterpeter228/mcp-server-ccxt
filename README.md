# CCXT MCP Server

<img src="assets/ccxt-logo.png" alt="CCXT Logo" width="100" height="100"/>

![Version](https://img.shields.io/badge/version-1.3.0-blue.svg)
[![MCP Standard](https://img.shields.io/badge/MCP-Standard-green.svg)](https://www.modelcontextprotocol.org/)
[![CCXT](https://img.shields.io/badge/CCXT-4.0.0-orange.svg)](https://github.com/ccxt/ccxt)
[![smithery badge](https://smithery.ai/badge/@doggybee/mcp-server-ccxt)](https://smithery.ai/server/@doggybee/mcp-server-ccxt)

High-performance cryptocurrency exchange integration using MCP (Model Context Protocol) and CCXT. Now with **Binance USDT-M Futures risk management and order engineering tools**.

## Features

- 🚀 **Exchange Support**: Connects to 20+ cryptocurrency exchanges
- 🔃 **Market Types**: Supports spot, futures, swap markets and more
- 🔧 **Proxy Configuration**: Options for accessing exchanges through proxies
- 📊 **Fast & Reliable**: Optimized caching and rate limiting
- 🌐 **MCP Standard**: Compatible with LLMs like Claude and GPT via MCP
- 🎯 **NEW: Binance Futures Tools**: Complete risk management for BTCUSDT/ETHUSDT
- 🔌 **Multiple Transport Modes**: Supports STDIO, SSE, and HTTP Streamable

## What's New in v1.3.0

### Binance USDT-M Futures Risk & Order Tools

Complete set of tools for accurate trading execution and risk management:

| Tool | Description |
|------|-------------|
| `get_exchange_info_futures` | Get tickSize, stepSize, minQty, minNotional, pricePrecision, qtyPrecision |
| `get_commission_rate_futures` | Get real maker/taker fee rates for your account |
| `get_position_risk` | Get markPrice, liquidationPrice, maintenanceMarginRate, isolatedMargin, leverage |
| `get_leverage_brackets` | Get notional tiers with maintMarginRatio, initialLeverage |
| `set_leverage_futures` | Set leverage (1-125x) with exchange response |
| `set_margin_type_futures` | Set ISOLATED or CROSSED margin |
| `place_bracket_orders` | Entry + SL + multiple TPs with auto-validation and rounding |
| `amend_order` | Modify orders (editOrder or cancel+recreate) |
| `log_trade_plan_snapshot` | Log trade plans for backtesting |
| `get_template_stats` | Get winrate, RR stats, fill metrics, suggested P_base/RR_min |

**Helper Tools:**
- `round_price_to_tick` - Round price conservatively based on order side
- `round_qty_to_step` - Round quantity down to step size
- `validate_order_params` - Validate orders against exchange rules

### Transport Modes

The server now supports three transport modes:

1. **STDIO** (default) - For Claude Desktop and similar integrations
2. **SSE** - Server-Sent Events for web applications
3. **HTTP Streamable** - HTTP POST with streaming response

## CCXT MCP Server Integration Architecture

![CCXT MCP Server Integration Architecture](docs/images/mcp-integration.svg)

The CCXT MCP Server connects language models to cryptocurrency exchanges through the Model Context Protocol. It serves as a bridge that allows LLMs to access real-time market data and execute trading operations across multiple exchanges through a unified API.

## Quick Start

### Installing via Smithery

To install mcp-server-ccxt for Claude Desktop automatically via [Smithery](https://smithery.ai/server/@doggybee/mcp-server-ccxt):

```bash
npx -y @smithery/cli install @doggybee/mcp-server-ccxt --client claude
```

### NPM Package (Recommended)

```bash
# Install globally
npm install -g @mcpfun/mcp-server-ccxt

# Start the server (STDIO mode)
mcp-server-ccxt

# Start in SSE mode
MCP_TRANSPORT=sse MCP_HTTP_PORT=3000 mcp-server-ccxt

# Start in HTTP Streamable mode
MCP_TRANSPORT=http-stream MCP_HTTP_PORT=3000 mcp-server-ccxt
```

### Manual Installation

```bash
# Clone the repository
git clone https://github.com/doggybee/mcp-server-ccxt.git
cd mcp-server-ccxt

# Install dependencies
npm install

# Build the server
npm run build

# Run tests
npm test

# Start the server
npm start
```

## Configuration

### Environment Variables

Create a `.env` file based on `.env.example`:

```bash
cp .env.example .env
```

Key configuration options:

```env
# Default exchange and market type
DEFAULT_EXCHANGE=binance
DEFAULT_MARKET_TYPE=spot

# Transport mode: stdio, sse, or http-stream
MCP_TRANSPORT=stdio
MCP_HTTP_PORT=3000
MCP_HTTP_HOST=127.0.0.1

# Binance API credentials (required for futures tools)
BINANCE_API_KEY=your_api_key
BINANCE_SECRET=your_api_secret

# Trade data storage (for logging and stats)
TRADE_DATA_DIR=./data

# CORS (for SSE/HTTP modes)
CORS_ORIGIN=*

# Proxy configuration (optional)
USE_PROXY=false
PROXY_URL=http://your-proxy-server:port
```

## Usage Examples

### Using with Claude Desktop (STDIO)

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ccxt": {
      "command": "mcp-server-ccxt",
      "env": {
        "BINANCE_API_KEY": "your_api_key",
        "BINANCE_SECRET": "your_secret"
      }
    }
  }
}
```

### Using with Cursor (STDIO)

Add to your Cursor MCP settings (`.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "ccxt-futures": {
      "command": "npx",
      "args": ["-y", "@mcpfun/mcp-server-ccxt"],
      "env": {
        "BINANCE_API_KEY": "your_api_key",
        "BINANCE_SECRET": "your_secret"
      }
    }
  }
}
```

### Using with CherryStudio (SSE)

1. Start the server in SSE mode:
```bash
MCP_TRANSPORT=sse MCP_HTTP_PORT=3000 mcp-server-ccxt
```

2. Configure CherryStudio MCP connection:
```json
{
  "name": "ccxt-futures",
  "type": "sse",
  "url": "http://localhost:3000/sse"
}
```

### Using with HTTP Streamable

For custom integrations using HTTP:

```bash
# Start server
MCP_TRANSPORT=http-stream MCP_HTTP_PORT=3000 mcp-server-ccxt
```

```javascript
// Example client code
const response = await fetch('http://localhost:3000/mcp', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    jsonrpc: '2.0',
    method: 'tools/call',
    params: {
      name: 'get_exchange_info_futures',
      arguments: { symbol: 'BTCUSDT' }
    },
    id: 1
  })
});
```

## Binance Futures Tools Examples

### 1. Get Exchange Info

Get tick size, step size, and precision for BTCUSDT:

**Input:**
```json
{
  "symbol": "BTCUSDT"
}
```

**Output:**
```json
{
  "symbol": "BTCUSDT",
  "tickSize": 0.1,
  "stepSize": 0.001,
  "minQty": 0.001,
  "minNotional": 5,
  "pricePrecision": 1,
  "qtyPrecision": 3,
  "maxLeverage": 125
}
```

### 2. Get Position Risk

Get current position information including liquidation price:

**Input:**
```json
{
  "symbol": "BTCUSDT",
  "apiKey": "your_key",
  "secret": "your_secret"
}
```

**Output:**
```json
{
  "symbol": "BTCUSDT",
  "markPrice": 100500.5,
  "liquidationPrice": 92450.3,
  "maintenanceMarginRate": 0.004,
  "isolatedMargin": 1005.5,
  "leverage": 10,
  "positionAmt": 0.1,
  "entryPrice": 100000,
  "marginType": "ISOLATED",
  "unrealizedPnl": 50.05
}
```

### 3. Place Bracket Orders

Place entry + SL + multiple TPs in one call:

**Input:**
```json
{
  "symbol": "BTCUSDT",
  "side": "BUY",
  "entry": {
    "price": 100000,
    "qty": 0.01,
    "postOnly": true
  },
  "sl": {
    "type": "STOP_MARKET",
    "stopPrice": 98000
  },
  "tps": [
    { "price": 102000, "qtyPct": 50 },
    { "price": 104000, "qtyPct": 50 }
  ],
  "entry_ttl_sec": 300,
  "apiKey": "your_key",
  "secret": "your_secret"
}
```

**Output:**
```json
{
  "success": true,
  "symbol": "BTCUSDT",
  "orders_submitted": [
    {
      "order_id": "123456789",
      "type": "ENTRY",
      "price": 100000,
      "qty": 0.01,
      "status": "NEW"
    },
    {
      "order_id": "123456790",
      "type": "SL",
      "stop_price": 98000,
      "qty": 0.01,
      "status": "NEW"
    },
    {
      "order_id": "123456791",
      "type": "TP",
      "price": 102000,
      "qty": 0.005,
      "status": "NEW"
    },
    {
      "order_id": "123456792",
      "type": "TP",
      "price": 104000,
      "qty": 0.005,
      "status": "NEW"
    }
  ],
  "entry_ttl_active": "Will auto-cancel in 300s if unfilled"
}
```

### 4. Get Template Stats

Get historical statistics for a trading template:

**Input:**
```json
{
  "template_id": "breakout_v1",
  "session": "ASIA",
  "v_regime": "MEDIUM",
  "symbol": "BTCUSDT"
}
```

**Output:**
```json
{
  "template_id": "breakout_v1",
  "session": "ASIA",
  "v_regime": "MEDIUM",
  "symbol": "BTCUSDT",
  "total_trades": 50,
  "wins": 28,
  "losses": 22,
  "winrate": 0.56,
  "avg_rr": 1.8,
  "p50_rr": 1.5,
  "p90_rr": 3.2,
  "avg_mae": 0.5,
  "avg_mfe": 2.1,
  "fill_rate": 0.75,
  "avg_time_to_fill_seconds": 180,
  "stop_slippage_p95": 0.08,
  "suggested_p_base_range": {
    "min": 0.46,
    "max": 0.66
  },
  "suggested_rr_min": 1.58,
  "sample_size": 50,
  "interpretation": {
    "winrate_quality": "GOOD",
    "sample_size_quality": "SUFFICIENT",
    "fill_rate_quality": "GOOD",
    "slippage_quality": "GOOD"
  }
}
```

## Available Tools

### Public API Tools

- `list-exchanges`: List all available cryptocurrency exchanges
- `get-ticker`: Get current ticker information for a trading pair
- `batch-get-tickers`: Get ticker information for multiple trading pairs at once
- `get-orderbook`: Get market order book for a trading pair
- `get-ohlcv`: Get OHLCV candlestick data for a trading pair
- `get-trades`: Get recent trades for a trading pair
- `get-markets`: Get all available markets for an exchange
- `get-exchange-info`: Get exchange information and status
- `get-leverage-tiers`: Get futures leverage tiers
- `get-funding-rates`: Get current funding rates
- `get-market-types`: Get market types supported by an exchange

### Private API Tools (requires API keys)

- `account-balance`: Get your account balance from a crypto exchange
- `place-market-order`: Place a market order on an exchange
- `set-leverage`: Set leverage for futures
- `set-margin-mode`: Set margin mode for futures
- `place-futures-market-order`: Place futures market orders

### Binance Futures Risk & Order Tools (NEW)

**Note:** Only BTCUSDT and ETHUSDT are supported (whitelist enforced).

- `get_exchange_info_futures`: Get tickSize, stepSize, minQty, minNotional
- `get_commission_rate_futures`: Get real maker/taker fee rates
- `get_position_risk`: Get liquidation price, margin info
- `get_leverage_brackets`: Get leverage tiers and notional caps
- `set_leverage_futures`: Set leverage (1-125x)
- `set_margin_type_futures`: Set ISOLATED or CROSSED margin
- `place_bracket_orders`: Entry + SL + TPs with validation
- `amend_order`: Modify existing orders
- `log_trade_plan_snapshot`: Log trade plans for backtesting
- `get_template_stats`: Get performance statistics

**Helper Tools:**
- `round_price_to_tick`: Round price to tick size
- `round_qty_to_step`: Round quantity to step size  
- `validate_order_params`: Validate order parameters

### Configuration & Utility Tools

- `cache-stats`: Get CCXT cache statistics
- `clear-cache`: Clear CCXT cache
- `set-log-level`: Set logging level
- `get-proxy-config`: Get proxy settings
- `set-proxy-config`: Configure proxy settings
- `set-market-type`: Set default market type

## Symbol Whitelist

The Binance Futures tools only support:
- **BTCUSDT** - Bitcoin/USDT Perpetual
- **ETHUSDT** - Ethereum/USDT Perpetual

Any other symbol will be rejected. This is intentional for risk management.

## Price & Quantity Rounding

The tools automatically round prices and quantities to comply with exchange rules:

- **BUY orders**: Price rounded DOWN (more conservative - may not fill)
- **SELL orders**: Price rounded UP (more conservative - may not fill)
- **Quantities**: Always rounded DOWN (prevents exceeding limits)

Example:
```
Input: price=100000.15, tickSize=0.10, side=BUY
Output: 100000.10 (rounded down)

Input: price=100000.15, tickSize=0.10, side=SELL
Output: 100000.20 (rounded up)
```

## Performance Optimizations

1. **LRU Caching System**:
   - Exchange info: 5 minutes
   - Leverage brackets: 1 hour
   - Ticker data: 10 seconds
   - Order book: 5 seconds

2. **Adaptive Rate Limiting**:
   - Automatically adjusts request rates
   - Exponential backoff for errors
   - Per-exchange concurrency control

3. **Exchange Connection Management**:
   - Efficient instance pooling
   - Proper error handling and retries

## Testing

Run the test suite:

```bash
# Run all tests
npm test

# Run with coverage
npm run test:coverage

# Run in watch mode
npm run test:watch
```

## Security Best Practices

### API Key Security

1. **Create Dedicated API Keys**:
   - Create separate API keys for different applications
   - Never reuse API keys across services

2. **Limit API Key Permissions**:
   - Enable only required permissions
   - Disable withdrawal permissions if not needed
   - Use IP whitelisting when available

3. **Secure Storage**:
   - Never commit API keys to version control
   - Use environment variables
   - Use `.env` files excluded from git

## Troubleshooting

See [docs/troubleshooting.md](docs/troubleshooting.md) for common issues.

### Common Issues

1. **"Symbol not allowed"**: Only BTCUSDT and ETHUSDT are supported
2. **"Notional value below minimum"**: Increase qty or price
3. **"leverage not changed"**: Leverage already set to requested value
4. **"marginType already set"**: Margin type already configured

## Risk Disclaimer

This software is provided for informational purposes only. Using this software to interact with cryptocurrency exchanges involves significant risks:

- **Financial Risk**: Cryptocurrency trading involves risk of loss
- **API Security**: Ensure your API keys have appropriate permission limits
- **No Investment Advice**: This tool does not provide investment advice
- **No Warranty**: The software is provided "as is" without warranty of any kind

## License

This project is licensed under the MIT License - see the [LICENSE.txt](LICENSE.txt) file for details.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history.

---

For issues, feature requests, or contributions, please visit [the GitHub repository](https://github.com/doggybee/mcp-server-ccxt).
