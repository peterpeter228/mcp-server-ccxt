# Data Source Tools

MCP tools for cross-exchange data, diagnostics, and quality assessment. Compatible with Trading-COG-OS kernel constraints.

## Overview

These tools provide:
- Cross-exchange price consensus for anchor validation
- Orderbook/WS diagnostics for data freshness assessment  
- Trade activity metrics for fill probability estimation
- Exchange status aggregation
- Rate limit and QoS monitoring
- Macro event and on-chain fee data
- Stablecoin depeg monitoring
- Volatility fallback calculations

## Constraints

All tools follow these constraints for kernel compatibility:

| Constraint | Value |
|------------|-------|
| Symbols | BTCUSDT, ETHUSDT only (accepts BTC/USDT, BTC-USDT, etc.) |
| Output size | ≤ 2KB JSON |
| Array items | ≤ 8 per array |
| Quality flags | ≤ 6 per output |
| HTTP retries | ≤ 2 with exponential backoff |
| Per-host concurrency | ≤ 2 |

## Environment Variables

### Optional API Keys

| Variable | Tool | Notes |
|----------|------|-------|
| `FRED_API_KEY` | `us_macro_event_window_fred` | Free tier from [FRED](https://fred.stlouisfed.org/docs/api/api_key.html) |
| `ETHERSCAN_API_KEY` | `onchain_fee_congestion` (ETH) | Free tier from [Etherscan](https://etherscan.io/apis) |

**Key missing behavior**: Tools return `success: true` with `quality_flags: ["no_api_key"]` rather than failing.

## Tool Reference

### P0 Tools (Critical Path)

#### `mcp_ext-cross_exchange_anchor_consensus_a9YOaP`

Cross-exchange price consensus for anchor validation.

**Request:**
```json
{
  "symbol": "BTCUSDT",
  "venues": ["binance_futures", "binance_spot", "coinbase_spot", "kraken_spot"],
  "timeout_ms": 1200
}
```

**Response:**
```json
{
  "success": true,
  "ts_ms": 1704067200000,
  "schema_version": "1.0",
  "source": "mcp_ext",
  "quality_flags": [],
  "inputs": { "symbol": "BTCUSDT", "venues_used": ["binance_futures", "binance_spot"] },
  "quotes": [
    { "venue": "binance_futures_mark", "quote_ccy": "USDT", "px": 100000.5, "px_type": "mark" },
    { "venue": "binance_spot", "quote_ccy": "USDT", "px": 100001.2, "px_type": "mid" }
  ],
  "consensus": {
    "median_px": 100000.85,
    "min_px": 100000.5,
    "max_px": 100001.2,
    "max_dev_bps": 3,
    "dev_bps_by_venue": [{ "venue": "binance_futures_mark", "dev_bps": 3 }],
    "consensus_ok": true
  }
}
```

#### `mcp_ext-spot_perp_basis_digest_a9YOaP`

Spot-perp basis and funding rate for entry depth adjustment.

**Request:**
```json
{ "symbol": "BTCUSDT" }
```

**Response:**
```json
{
  "success": true,
  "ts_ms": 1704067200000,
  "schema_version": "1.0",
  "source": "mcp_ext",
  "quality_flags": [],
  "spot_mid": 100000.5,
  "perp_mark": 100005.2,
  "perp_index": 100000.8,
  "basis": {
    "mark_minus_spot_bps": 5,
    "index_minus_spot_bps": 0
  },
  "funding": {
    "last_funding_rate": 0.0001,
    "next_funding_time_ms": 1704096000000
  }
}
```

#### `mcp_ext-orderbook_ws_qos_diagnostics_a9YOaP`

Orderbook data freshness and update rate diagnostics.

**Request:**
```json
{ "symbol": "BTCUSDT", "window_sec": 10, "mode": "ws_prefer" }
```

**Response:**
```json
{
  "success": true,
  "ts_ms": 1704067200000,
  "schema_version": "1.0",
  "source": "mcp_ext",
  "quality_flags": ["ws_disconnected", "rest_sample_used"],
  "ws": { "connected": false, "last_update_age_ms": 0, "updates_per_sec": 0, "seq_gap_count": 0, "l1_mid": 0, "spread_bps": 0 },
  "rest": { "sampled": true, "sample_count": 3, "last_update_id_delta": 150, "l1_mid": 100000.5, "spread_bps": 2 }
}
```

#### `mcp_ext-trade_activity_proxy_binance_a9YOaP`

Trade activity metrics for fill probability estimation.

**Request:**
```json
{ "symbol": "BTCUSDT", "lookback_sec": 120, "bin_count": 6 }
```

**Response:**
```json
{
  "success": true,
  "ts_ms": 1704067200000,
  "schema_version": "1.0",
  "source": "mcp_ext",
  "quality_flags": [],
  "window_sec": 120,
  "trade_count": 847,
  "vol_quote": 1250000.5,
  "vwap": 100000.35,
  "last_px": 100000.8,
  "maker_buy_ratio_0_1": 0.52,
  "bins": [
    { "sec_ago": 10, "trade_count": 150, "vol_quote": 210000 },
    { "sec_ago": 30, "trade_count": 142, "vol_quote": 195000 }
  ]
}
```

### P1 Tools (Robustness)

#### `mcp_ext-exchange_status_aggregator_a9YOaP`

Exchange status from statuspage and connectivity.

**Request:**
```json
{ "venues": ["binance_futures", "coinbase", "kraken"] }
```

**Response:**
```json
{
  "success": true,
  "ts_ms": 1704067200000,
  "schema_version": "1.0",
  "source": "mcp_ext",
  "quality_flags": [],
  "overall": "ok",
  "venues": [
    { "venue": "binance_futures", "status": "ok", "detail_short": "API responding" },
    { "venue": "coinbase", "status": "ok", "detail_short": "All Systems Operational" }
  ]
}
```

#### `mcp_ext-rate_limit_qos_state_a9YOaP`

Internal rate limiting state and QoS metrics.

**Request:**
```json
{ "window_sec": 120 }
```

**Response:**
```json
{
  "success": true,
  "ts_ms": 1704067200000,
  "schema_version": "1.0",
  "source": "mcp_ext",
  "quality_flags": [],
  "window_sec": 120,
  "hosts": [
    { "host": "fapi.binance.com", "req_count": 50, "err_429": 0, "err_5xx": 0, "cooldown_ms": 0, "cache_hit_ratio": 0.6 }
  ]
}
```

#### `mcp_ext-us_macro_event_window_fred_a9YOaP`

US macro events from FRED (requires FRED_API_KEY).

**Request:**
```json
{ "days_ahead": 3, "max_events": 8 }
```

**Response:**
```json
{
  "success": true,
  "ts_ms": 1704067200000,
  "schema_version": "1.0",
  "source": "mcp_ext",
  "quality_flags": [],
  "next_event": { "ts_ms": 1704153600000, "title_short": "Employment Situation", "impact": "H" },
  "events": [
    { "ts_ms": 1704153600000, "title_short": "Employment Situation", "impact": "H" },
    { "ts_ms": 1704240000000, "title_short": "Consumer Credit", "impact": "L" }
  ]
}
```

#### `mcp_ext-onchain_fee_congestion_a9YOaP`

On-chain fee levels for BTC/ETH.

**Request:**
```json
{ "chain": "BTC" }
```

**Response:**
```json
{
  "success": true,
  "ts_ms": 1704067200000,
  "schema_version": "1.0",
  "source": "mcp_ext",
  "quality_flags": [],
  "chain": "BTC",
  "fees": { "fast": 45, "medium": 25, "slow": 10, "unit": "sat/vB" }
}
```

### P2 Tools (Supplementary)

#### `mcp_ext-stablecoin_depeg_monitor_a9YOaP`

USDT/USDC depeg from USD.

**Request:**
```json
{ "symbols": ["USDT", "USDC"] }
```

**Response:**
```json
{
  "success": true,
  "ts_ms": 1704067200000,
  "schema_version": "1.0",
  "source": "mcp_ext",
  "quality_flags": [],
  "quotes": [
    { "sym": "USDT", "px_usd": 0.9998, "depeg_bps": -2 },
    { "sym": "USDC", "px_usd": 1.0001, "depeg_bps": 1 }
  ]
}
```

#### `mcp_ext-volatility_regime_fallback_binance_a9YOaP`

Lightweight RV/ATR from klines.

**Request:**
```json
{ "symbol": "BTCUSDT", "interval": "1m", "limit": 240, "period_atr": 14 }
```

**Response:**
```json
{
  "success": true,
  "ts_ms": 1704067200000,
  "schema_version": "1.0",
  "source": "mcp_ext",
  "quality_flags": [],
  "interval": "1m",
  "rv_bps": 45,
  "atr_points": 125.5,
  "range_points": 850.2
}
```

### Bonus Tools

#### `mcp_ext-data_conflict_digest_a9YOaP`

Analyze price conflicts from other tool outputs.

**Request:**
```json
{
  "anchor_set": {
    "micro_mid": 100000.5,
    "snapshot_mid": 100005.2,
    "consensus_median": 100002.1,
    "basis_bps": 50
  }
}
```

**Response:**
```json
{
  "success": true,
  "ts_ms": 1704067200000,
  "schema_version": "1.0",
  "source": "mcp_ext",
  "quality_flags": [],
  "conflicts": [
    { "tag": "micro_snapshot_divergence", "severity": "M", "note": "47 bps difference" }
  ],
  "sot_preference": "consensus"
}
```

#### `mcp_ext-cache_maintenance_digest_a9YOaP`

Cache health and maintenance metrics.

**Request:**
```json
{}
```

**Response:**
```json
{
  "success": true,
  "ts_ms": 1704067200000,
  "schema_version": "1.0",
  "source": "mcp_ext",
  "quality_flags": [],
  "cache_keys_count": 15,
  "evicted": 2,
  "expired_purged": 8,
  "hit_ratio": 0.65
}
```

## Quality Flags Reference

| Flag | Description |
|------|-------------|
| `source_partial` | Fewer than expected sources responded |
| `no_data` | No data returned |
| `insufficient_trade_data` | Not enough data for analysis |
| `rate_limited` | Got 429 response |
| `stale_source` | Data older than expected TTL |
| `time_rollback` | Timestamp went backwards |
| `critical_source_failed` | Essential data source failed |
| `ws_disconnected` | WebSocket not connected |
| `stall_suspected` | Data not updating |
| `dev_high` | High price deviation detected |
| `quote_mismatch_usd_usdt` | Mixed USD/USDT quotes |
| `basis_extreme` | Extreme basis detected |
| `no_api_key` | API key not configured |
| `fallback_used` | Fallback data source used |
| `trimmed_output` | Output was truncated for size |

## Cache TTL Configuration

| Tool | TTL |
|------|-----|
| cross_exchange_anchor_consensus | 2s |
| spot_perp_basis_digest | 2s |
| orderbook_ws_qos_diagnostics | 1s |
| trade_activity_proxy_binance | 2s |
| exchange_status_aggregator | 30s |
| rate_limit_qos_state | 1s |
| us_macro_event_window_fred | 6h |
| onchain_fee_congestion | 30s |
| stablecoin_depeg_monitor | 10s |
| volatility_regime_fallback_binance | 5s |
| data_conflict_digest | no cache |
| cache_maintenance_digest | no cache |

## Infrastructure Modules

### `src/lib/http_client.ts`
- Timeout (default 1200ms)
- Retry (≤2) with exponential backoff + jitter
- 429 detection → circuit breaker (5-15s cooldown)
- Per-host semaphore (max 2 concurrent)

### `src/lib/cache.ts`
- LRU cache with tool+params fingerprinting
- Per-tool TTL configuration
- Cache hit/miss statistics

### `src/lib/symbol.ts`
- Symbol normalization (BTCUSDT/ETHUSDT only)
- Venue-specific format mapping
- Quote currency tracking

### `src/lib/quality.ts`
- Quality flag constants and builder
- Staleness/rollback detection
- Threshold constants

### `src/lib/size_guard.ts`
- Output size limit (2KB)
- Array trimming (max 8 items)
- Optional field dropping by priority
