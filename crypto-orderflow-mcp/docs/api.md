# API 文档

## 概述

Crypto Orderflow MCP Server 提供三种 API 接口：

1. **MCP Protocol**: 通过 `/mcp` 端点使用 JSON-RPC 2.0 协议
2. **SSE**: 通过 `/sse` 端点获取实时数据流
3. **REST API**: 传统 HTTP REST 接口

## MCP Protocol

### 端点
```
POST /mcp
Content-Type: application/json
```

### 请求格式
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "tool_name",
    "arguments": {...}
  }
}
```

### 可用方法

#### tools/list
列出所有可用工具。

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/list"
}
```

#### tools/call
调用指定工具。

---

## Tools 详细说明

### get_market_snapshot

获取交易对的市场快照。

**参数**
| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| symbol | string | 是 | 交易对，如 BTCUSDT |

**返回字段**
| 字段 | 类型 | 说明 |
|------|------|------|
| timestamp | integer | 时间戳 (毫秒) |
| symbol | string | 交易对 |
| exchange | string | 交易所 |
| marketType | string | 市场类型 |
| price | string | 最新价格 (USDT) |
| markPrice | string | 标记价格 (USDT) |
| indexPrice | string | 指数价格 (USDT) |
| high24h | string | 24小时最高价 |
| low24h | string | 24小时最低价 |
| volume24h | string | 24小时成交量 (BTC/ETH) |
| quoteVolume24h | string | 24小时成交额 (USDT) |
| fundingRate | string | 当前资金费率 |
| nextFundingTime | integer | 下次结算时间 (ms) |
| openInterest | string | 持仓量 (BTC/ETH) |
| openInterestValue | string | 持仓价值 (USDT) |

---

### get_key_levels

获取关键价位。

**参数**
| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| symbol | string | 是 | 交易对 |
| date | string | 否 | 日期 (YYYY-MM-DD)，默认今天 |
| sessionTZ | string | 否 | 时区，默认 UTC |

**返回字段**
```json
{
  "timestamp": 1703001234567,
  "symbol": "BTCUSDT",
  "date": "2024-01-15",
  "vwap": {
    "dVWAP": "43250.50",      // 今日 VWAP
    "pdVWAP": "43100.25"      // 昨日 VWAP
  },
  "volumeProfile": {
    "developing": {
      "POC": "43300.00",       // 今日 POC
      "VAH": "43500.00",       // 今日 VAH
      "VAL": "43100.00"        // 今日 VAL
    },
    "previous": {
      "POC": "43200.00",       // 昨日 POC
      "VAH": "43400.00",       // 昨日 VAH
      "VAL": "43000.00"        // 昨日 VAL
    }
  },
  "sessions": {
    "Tokyo": {"high": "43400.00", "low": "43100.00", "isComplete": true},
    "London": {"high": "43500.00", "low": "43150.00", "isComplete": true},
    "NY": {"high": "43450.00", "low": "43200.00", "isComplete": false}
  }
}
```

---

### get_footprint

获取 Footprint 柱状图数据。

**参数**
| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| symbol | string | 是 | 交易对 |
| timeframe | string | 是 | 周期: 1m, 5m, 15m, 30m, 1h |
| startTime | integer | 否 | 开始时间 (ms) |
| endTime | integer | 否 | 结束时间 (ms) |

**返回示例**
```json
{
  "timestamp": 1703001234567,
  "symbol": "BTCUSDT",
  "timeframe": "5m",
  "bars": [
    {
      "openTime": 1703001000000,
      "closeTime": 1703001300000,
      "open": "43250.00",
      "high": "43280.00",
      "low": "43230.00",
      "close": "43260.00",
      "totalBuyVolume": "125.50",
      "totalSellVolume": "98.25",
      "totalVolume": "223.75",
      "delta": "27.25",
      "pocPrice": "43260.00",
      "levels": [
        {
          "price": "43280.00",
          "buyVolume": "15.25",
          "sellVolume": "8.50",
          "delta": "6.75"
        }
      ]
    }
  ]
}
```

---

### get_orderflow_metrics

获取订单流指标。

**参数**
| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| symbol | string | 是 | 交易对 |
| timeframe | string | 是 | 周期 |
| startTime | integer | 否 | 开始时间 |
| endTime | integer | 否 | 结束时间 |

**返回字段**
```json
{
  "delta": {
    "series": [...],
    "stats": {
      "totalDelta": "1250.50",
      "avgDelta": "12.50",
      "positiveBars": 65,
      "negativeBars": 35
    },
    "currentCVD": "5280.25"
  },
  "cvd": {
    "series": [...],
    "divergence": {
      "hasDivergence": true,
      "divergenceType": "bearish"
    }
  },
  "imbalances": {
    "recent": [...],
    "summary": {
      "totalBuyImbalances": 12,
      "totalSellImbalances": 8,
      "significantBuyLevels": [...],
      "significantSellLevels": [...]
    }
  }
}
```

---

### get_orderbook_depth_delta

获取订单簿深度变化。

**参数**
| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| symbol | string | 是 | 交易对 |
| percent | number | 否 | 价格范围百分比，默认 1.0 |
| windowSec | integer | 否 | 采样间隔秒，默认 5 |
| lookback | integer | 否 | 历史条数，默认 100 |

**返回字段**
```json
{
  "current": {
    "bidVolume": "1250.50",
    "askVolume": "980.25",
    "net": "270.25"
  },
  "summary": {
    "totalBidDelta": "125.50",
    "totalAskDelta": "-85.25",
    "totalNetDelta": "210.75",
    "trend": "bullish"
  },
  "history": [...],
  "deltaHistory": [...]
}
```

---

### stream_liquidations

获取清算事件。

**参数**
| 名称 | 类型 | 必填 | 说明 |
|------|------|------|------|
| symbol | string | 是 | 交易对 |
| limit | integer | 否 | 返回条数，默认 100 |

**返回字段**
```json
{
  "liquidations": [
    {
      "symbol": "BTCUSDT",
      "side": "SELL",
      "price": "43250.50",
      "quantity": "0.125",
      "timestamp": 1703001234567
    }
  ],
  "summary": {
    "buyCount": 45,
    "sellCount": 55,
    "totalBuyQuantity": "125.50",
    "totalSellQuantity": "180.25",
    "dominantSide": "sell"
  }
}
```

---

## SSE 端点

### 连接
```
GET /sse
```

### 事件类型

#### connected
连接成功事件。

```json
{
  "event": "connected",
  "data": {
    "timestamp": 1703001234567,
    "symbols": ["BTCUSDT", "ETHUSDT"]
  }
}
```

#### market_snapshot
市场快照更新 (每秒)。

```json
{
  "event": "market_snapshot",
  "data": {...}
}
```

---

## REST API

### GET /api/market/{symbol}
等同于 `get_market_snapshot`

### GET /api/key-levels/{symbol}
等同于 `get_key_levels`

**Query 参数**
- `date`: 日期
- `sessionTZ`: 时区

### GET /api/footprint/{symbol}
等同于 `get_footprint`

**Query 参数**
- `timeframe`: 周期
- `startTime`: 开始时间
- `endTime`: 结束时间
- `limit`: 条数限制

### GET /api/orderflow/{symbol}
等同于 `get_orderflow_metrics`

### GET /api/depth-delta/{symbol}
等同于 `get_orderbook_depth_delta`

**Query 参数**
- `percent`: 价格范围百分比
- `windowSec`: 采样间隔
- `lookback`: 历史条数

### GET /api/liquidations/{symbol}
等同于 `stream_liquidations`

**Query 参数**
- `limit`: 返回条数

---

## 错误处理

### 错误响应格式
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": {
    "code": -32603,
    "message": "Error description"
  }
}
```

### 错误码
| 代码 | 说明 |
|------|------|
| -32700 | Parse error |
| -32600 | Invalid Request |
| -32601 | Method not found |
| -32602 | Invalid params |
| -32603 | Internal error |
