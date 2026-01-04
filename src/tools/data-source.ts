/**
 * Data Source Tools
 * MCP tools for cross-exchange data, diagnostics, and quality assessment
 * Compatible with Trading-COG-OS kernel constraints
 * 
 * 数据源工具
 * 用于跨交易所数据、诊断和质量评估的MCP工具
 * 与Trading-COG-OS内核约束兼容
 */

import { z } from 'zod';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { log, LogLevel } from '../utils/logging.js';
import { normalizeSymbol, AllowedSymbol, getBaseAsset, getVenueQuoteCurrency } from '../lib/symbol.js';
import { httpGet, httpGetMultiple, getHostStatistics, getCooldownRemaining, resetHostCooldown, resetAllCooldowns, HttpResponse } from '../lib/http_client.js';
import { dataSourceCache, getDataSourceCacheStats, TOOL_TTL } from '../lib/cache.js';
import {
  QualityFlagBuilder,
  QUALITY_FLAGS,
  QUALITY_THRESHOLDS,
  isStale,
  hasTimeRollback,
  calculateAge
} from '../lib/quality.js';
import { createGuardedResponse, trimArray, MAX_ARRAY_ITEMS, getJsonByteSize } from '../lib/size_guard.js';

// Schema version for all tools
const SCHEMA_VERSION = '1.0';
const SOURCE = 'mcp_ext';

// Common Zod schemas
const symbolSchema = z.string()
  .describe('Trading pair symbol (BTCUSDT, ETHUSDT, BTC/USDT, ETH-USDT, etc.)');

const timeoutSchema = z.number().optional()
  .describe('Request timeout in milliseconds');

/**
 * Base output interface for all data source tools
 */
interface BaseOutput {
  success: boolean;
  ts_ms: number;
  schema_version: string;
  source: string;
  quality_flags: string[];
}

/**
 * Create base output structure
 */
function createBaseOutput(success: boolean, flags: QualityFlagBuilder): BaseOutput {
  return {
    success,
    ts_ms: Date.now(),
    schema_version: SCHEMA_VERSION,
    source: SOURCE,
    quality_flags: flags.toArray()
  };
}

/**
 * Format MCP tool response
 */
function formatResponse(data: any) {
  const guarded = createGuardedResponse(data);
  return {
    content: [{
      type: 'text' as const,
      text: JSON.stringify(guarded, null, 2)
    }]
  };
}

// =============================================================================
// API Endpoint URLs
// =============================================================================

const ENDPOINTS = {
  // Binance Futures
  BINANCE_FUTURES_PREMIUM_INDEX: 'https://fapi.binance.com/fapi/v1/premiumIndex',
  BINANCE_FUTURES_BOOK_TICKER: 'https://fapi.binance.com/fapi/v1/ticker/bookTicker',
  BINANCE_FUTURES_DEPTH: 'https://fapi.binance.com/fapi/v1/depth',
  BINANCE_FUTURES_AGG_TRADES: 'https://fapi.binance.com/fapi/v1/aggTrades',
  BINANCE_FUTURES_KLINES: 'https://fapi.binance.com/fapi/v1/klines',
  BINANCE_FUTURES_TIME: 'https://fapi.binance.com/fapi/v1/time',
  BINANCE_FUTURES_PING: 'https://fapi.binance.com/fapi/v1/ping',
  
  // Binance Spot
  BINANCE_SPOT_BOOK_TICKER: 'https://api.binance.com/api/v3/ticker/bookTicker',
  
  // Coinbase
  COINBASE_SPOT_PRICE: 'https://api.coinbase.com/v2/prices',
  COINBASE_STATUS: 'https://status.coinbase.com/api/v2/status.json',
  
  // Kraken
  KRAKEN_TICKER: 'https://api.kraken.com/0/public/Ticker',
  KRAKEN_STATUS: 'https://status.kraken.com/api/v2/status.json',
  
  // Deribit
  DERIBIT_INDEX: 'https://www.deribit.com/api/v2/public/get_index_price',
  DERIBIT_STATUS: 'https://status.deribit.com/api/v2/status.json',
  
  // OKX
  OKX_TICKER: 'https://www.okx.com/api/v5/market/ticker',
  
  // On-chain
  MEMPOOL_FEES: 'https://mempool.space/api/v1/fees/recommended',
  
  // FRED (requires API key)
  FRED_RELEASES: 'https://api.stlouisfed.org/fred/releases/dates',
};

// =============================================================================
// P0-1: Cross Exchange Anchor Consensus
// =============================================================================

interface QuoteData {
  venue: string;
  quote_ccy: 'USDT' | 'USD';
  px: number;
  px_type: 'mid' | 'last' | 'mark' | 'index';
  source_ts_ms?: number;
  age_ms?: number;
}

interface ConsensusData {
  median_px: number;
  min_px: number;
  max_px: number;
  max_dev_bps: number;
  dev_bps_by_venue: Array<{ venue: string; dev_bps: number }>;
  consensus_ok: boolean;
}

async function fetchBinanceFuturesPremiumIndex(symbol: AllowedSymbol): Promise<HttpResponse> {
  return httpGet(`${ENDPOINTS.BINANCE_FUTURES_PREMIUM_INDEX}?symbol=${symbol}`);
}

async function fetchBinanceSpotBookTicker(symbol: AllowedSymbol): Promise<HttpResponse> {
  return httpGet(`${ENDPOINTS.BINANCE_SPOT_BOOK_TICKER}?symbol=${symbol}`);
}

async function fetchCoinbaseSpotPrice(base: string): Promise<HttpResponse> {
  return httpGet(`${ENDPOINTS.COINBASE_SPOT_PRICE}/${base}-USD/spot`, { timeout: 8000 });
}

async function fetchKrakenTicker(symbol: AllowedSymbol): Promise<HttpResponse> {
  const krakenPair = symbol === 'BTCUSDT' ? 'XBTUSD' : 'ETHUSD';
  return httpGet(`${ENDPOINTS.KRAKEN_TICKER}?pair=${krakenPair}`, { timeout: 8000 });
}

async function fetchDeribitIndex(symbol: AllowedSymbol): Promise<HttpResponse> {
  const indexName = symbol === 'BTCUSDT' ? 'btc_usd' : 'eth_usd';
  return httpGet(`${ENDPOINTS.DERIBIT_INDEX}?index_name=${indexName}`, { timeout: 8000 });
}

function calculateMedian(values: number[]): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function calculateDevBps(price: number, reference: number): number {
  if (reference === 0) return 0;
  return Math.abs((price - reference) / reference * 10000);
}

// =============================================================================
// P0-2: Spot Perp Basis Digest
// =============================================================================

interface BasisOutput extends BaseOutput {
  spot_mid: number;
  perp_mark: number;
  perp_index: number;
  basis: {
    mark_minus_spot_bps: number;
    index_minus_spot_bps: number;
  };
  funding: {
    last_funding_rate: number;
    next_funding_time_ms?: number;
  };
}

// =============================================================================
// P0-3: Orderbook WS QoS Diagnostics
// =============================================================================

interface OrderbookQosOutput extends BaseOutput {
  ws?: {
    connected: boolean;
    last_update_age_ms: number;
    updates_per_sec: number;
    seq_gap_count: number;
    l1_mid: number;
    spread_bps: number;
  };
  rest?: {
    sampled: boolean;
    sample_count: number;
    last_update_id_delta: number;
    l1_mid: number;
    spread_bps: number;
  };
}

// =============================================================================
// P0-4: Trade Activity Proxy
// =============================================================================

interface TradeBin {
  sec_ago: number;
  trade_count: number;
  vol_quote: number;
}

interface TradeActivityOutput extends BaseOutput {
  window_sec: number;
  trade_count: number;
  vol_quote: number;
  vwap: number;
  last_px: number;
  maker_buy_ratio_0_1?: number;
  bins: TradeBin[];
}

// =============================================================================
// P1-1: Exchange Status Aggregator
// =============================================================================

interface VenueStatus {
  venue: string;
  status: 'ok' | 'degraded' | 'incident' | 'unknown';
  detail_short: string;
}

interface ExchangeStatusOutput extends BaseOutput {
  overall: 'ok' | 'degraded' | 'incident' | 'unknown';
  venues: VenueStatus[];
}

// =============================================================================
// P1-2: Rate Limit QoS State
// =============================================================================

interface HostQosStats {
  host: string;
  req_count: number;
  err_429: number;
  err_5xx: number;
  cooldown_ms: number;
  cache_hit_ratio: number;
}

interface RateLimitQosOutput extends BaseOutput {
  window_sec: number;
  hosts: HostQosStats[];
}

// =============================================================================
// P1-3: US Macro Event Window (FRED)
// =============================================================================

interface MacroEvent {
  ts_ms: number;
  title_short: string;
  impact: 'H' | 'M' | 'L';
}

interface MacroEventOutput extends BaseOutput {
  next_event?: MacroEvent;
  events: MacroEvent[];
}

// =============================================================================
// P1-4: On-chain Fee Congestion
// =============================================================================

interface FeeOutput extends BaseOutput {
  chain: 'BTC' | 'ETH';
  fees: {
    fast: number;
    medium: number;
    slow: number;
    unit: 'sat/vB' | 'gwei';
  };
}

// =============================================================================
// P2-1: Stablecoin Depeg Monitor
// =============================================================================

interface StablecoinQuote {
  sym: 'USDT' | 'USDC';
  px_usd: number;
  depeg_bps: number;
}

interface StablecoinOutput extends BaseOutput {
  quotes: StablecoinQuote[];
}

// =============================================================================
// P2-2: Volatility Regime Fallback
// =============================================================================

interface VolatilityOutput extends BaseOutput {
  interval: string;
  rv_bps: number;
  atr_points: number;
  range_points: number;
}

// =============================================================================
// BONUS-1: Data Conflict Digest
// =============================================================================

interface ConflictTag {
  tag: string;
  severity: 'H' | 'M' | 'L';
  note: string;
}

interface ConflictDigestOutput extends BaseOutput {
  conflicts: ConflictTag[];
  sot_preference: 'consensus' | 'micro' | 'snapshot' | 'unknown';
}

// =============================================================================
// BONUS-2: Cache Maintenance Digest
// =============================================================================

interface CacheMaintenanceOutput extends BaseOutput {
  cache_keys_count: number;
  evicted: number;
  expired_purged: number;
  hit_ratio: number;
}

// =============================================================================
// Tool Registration
// =============================================================================

export function registerDataSourceTools(server: McpServer) {
  
  // =========================================================================
  // P0-1: Cross Exchange Anchor Consensus
  // =========================================================================
  server.tool(
    'mcp_ext-cross_exchange_anchor_consensus_a9YOaP',
    'Get cross-exchange price consensus for anchor point validation. Returns median price, deviation by venue, and consensus quality flags.',
    {
      symbol: symbolSchema,
      venues: z.array(z.string()).optional()
        .describe('Venues to query (default: binance_futures, binance_spot, coinbase_spot, kraken_spot)'),
      timeout_ms: timeoutSchema.default(1200)
    },
    async ({ symbol, venues, timeout_ms }) => {
      const flags = new QualityFlagBuilder();
      const quotes: QuoteData[] = [];
      let criticalFailed = false;
      
      try {
        const normalizedSymbol = normalizeSymbol(symbol);
        const base = getBaseAsset(normalizedSymbol);
        
        const defaultVenues = ['binance_futures', 'binance_spot', 'coinbase_spot', 'kraken_spot'];
        const selectedVenues = trimArray(venues || defaultVenues, 6);
        
        // Fetch from cache or API
        const { data: result, cacheHit } = await dataSourceCache.getOrFetch(
          'cross_exchange_anchor_consensus',
          { symbol: normalizedSymbol, venues: selectedVenues.sort().join(',') },
          async () => {
            const responses: Array<{ venue: string; response: HttpResponse }> = [];
            
            // Parallel fetch from all venues
            const fetchPromises: Promise<void>[] = [];
            
            if (selectedVenues.includes('binance_futures')) {
              fetchPromises.push((async () => {
                const r = await fetchBinanceFuturesPremiumIndex(normalizedSymbol);
                responses.push({ venue: 'binance_futures', response: r });
              })());
            }
            
            if (selectedVenues.includes('binance_spot')) {
              fetchPromises.push((async () => {
                const r = await fetchBinanceSpotBookTicker(normalizedSymbol);
                responses.push({ venue: 'binance_spot', response: r });
              })());
            }
            
            if (selectedVenues.includes('coinbase_spot')) {
              fetchPromises.push((async () => {
                const r = await fetchCoinbaseSpotPrice(base);
                responses.push({ venue: 'coinbase_spot', response: r });
              })());
            }
            
            if (selectedVenues.includes('kraken_spot')) {
              fetchPromises.push((async () => {
                const r = await fetchKrakenTicker(normalizedSymbol);
                responses.push({ venue: 'kraken_spot', response: r });
              })());
            }
            
            if (selectedVenues.includes('deribit_index')) {
              fetchPromises.push((async () => {
                const r = await fetchDeribitIndex(normalizedSymbol);
                responses.push({ venue: 'deribit_index', response: r });
              })());
            }
            
            await Promise.all(fetchPromises);
            return responses;
          }
        );
        
        // Process responses
        let hasUsd = false;
        let hasUsdt = false;
        
        for (const { venue, response } of result) {
          if (!response.success) {
            if (venue === 'binance_futures' || venue === 'binance_spot') {
              criticalFailed = true;
            }
            if (response.status === 429) {
              flags.add(QUALITY_FLAGS.RATE_LIMITED);
            }
            continue;
          }
          
          const data = response.data;
          const quoteCcy = getVenueQuoteCurrency(venue);
          if (quoteCcy === 'USD') hasUsd = true;
          if (quoteCcy === 'USDT') hasUsdt = true;
          
          // Parse venue-specific response
          if (venue === 'binance_futures' && data) {
            // Premium index returns mark, index prices
            const markPrice = parseFloat(data.markPrice);
            const indexPrice = parseFloat(data.indexPrice);
            const ts = data.time || Date.now();
            
            quotes.push({
              venue: 'binance_futures_mark',
              quote_ccy: 'USDT',
              px: markPrice,
              px_type: 'mark',
              source_ts_ms: ts,
              age_ms: calculateAge(ts)
            });
            quotes.push({
              venue: 'binance_futures_index',
              quote_ccy: 'USDT',
              px: indexPrice,
              px_type: 'index',
              source_ts_ms: ts,
              age_ms: calculateAge(ts)
            });
          } else if (venue === 'binance_spot' && data) {
            const bid = parseFloat(data.bidPrice);
            const ask = parseFloat(data.askPrice);
            const mid = (bid + ask) / 2;
            
            quotes.push({
              venue: 'binance_spot',
              quote_ccy: 'USDT',
              px: mid,
              px_type: 'mid'
            });
          } else if (venue === 'coinbase_spot' && data?.data) {
            const price = parseFloat(data.data.amount);
            
            quotes.push({
              venue: 'coinbase_spot',
              quote_ccy: 'USD',
              px: price,
              px_type: 'last'
            });
          } else if (venue === 'kraken_spot' && data?.result) {
            const pair = Object.keys(data.result)[0];
            const krakenData = data.result[pair];
            const bid = parseFloat(krakenData.b[0]);
            const ask = parseFloat(krakenData.a[0]);
            const mid = (bid + ask) / 2;
            
            quotes.push({
              venue: 'kraken_spot',
              quote_ccy: 'USD',
              px: mid,
              px_type: 'mid'
            });
          } else if (venue === 'deribit_index' && data?.result) {
            const indexPrice = data.result.index_price;
            
            quotes.push({
              venue: 'deribit_index',
              quote_ccy: 'USD',
              px: indexPrice,
              px_type: 'index'
            });
          }
        }
        
        // Quality checks
        flags.addIf(quotes.length < QUALITY_THRESHOLDS.MIN_QUOTES_FOR_CONSENSUS, QUALITY_FLAGS.SOURCE_PARTIAL);
        flags.addIf(criticalFailed, QUALITY_FLAGS.CRITICAL_SOURCE_FAILED);
        flags.addIf(hasUsd && hasUsdt, QUALITY_FLAGS.QUOTE_MISMATCH_USD_USDT);
        
        // Check for stale quotes
        const staleQuotes = quotes.filter(q => q.age_ms && q.age_ms > QUALITY_THRESHOLDS.MAX_QUOTE_AGE_MS);
        flags.addIf(staleQuotes.length > 0, QUALITY_FLAGS.STALE_SOURCE);
        
        // Calculate consensus
        const prices = quotes.map(q => q.px).filter(p => p > 0);
        const medianPx = calculateMedian(prices);
        const minPx = prices.length > 0 ? Math.min(...prices) : 0;
        const maxPx = prices.length > 0 ? Math.max(...prices) : 0;
        
        const devByVenue = quotes.map(q => ({
          venue: q.venue,
          dev_bps: Math.round(calculateDevBps(q.px, medianPx))
        }));
        
        const maxDevBps = devByVenue.length > 0 
          ? Math.max(...devByVenue.map(d => d.dev_bps))
          : 0;
        
        flags.addIf(maxDevBps > QUALITY_THRESHOLDS.MAX_DEV_BPS, QUALITY_FLAGS.DEV_HIGH);
        
        const consensus: ConsensusData = {
          median_px: Math.round(medianPx * 100) / 100,
          min_px: Math.round(minPx * 100) / 100,
          max_px: Math.round(maxPx * 100) / 100,
          max_dev_bps: maxDevBps,
          dev_bps_by_venue: trimArray(devByVenue, 6),
          consensus_ok: maxDevBps <= QUALITY_THRESHOLDS.MAX_DEV_BPS && quotes.length >= QUALITY_THRESHOLDS.MIN_QUOTES_FOR_CONSENSUS
        };
        
        const success = !criticalFailed && quotes.length > 0;
        
        const output = {
          ...createBaseOutput(success, flags),
          inputs: {
            symbol: normalizedSymbol,
            venues_used: selectedVenues
          },
          quotes: trimArray(quotes, MAX_ARRAY_ITEMS),
          consensus
        };
        
        return formatResponse(output);
        
      } catch (error) {
        log(LogLevel.ERROR, `cross_exchange_anchor_consensus error: ${error}`);
        flags.add(QUALITY_FLAGS.CRITICAL_SOURCE_FAILED);
        
        return formatResponse({
          ...createBaseOutput(false, flags),
          error: error instanceof Error ? error.message : String(error)
        });
      }
    }
  );

  // =========================================================================
  // P0-2: Spot Perp Basis Digest
  // =========================================================================
  server.tool(
    'mcp_ext-spot_perp_basis_digest_a9YOaP',
    'Get spot-perp basis (bps) and funding rate for entry depth adjustment. Returns mark/index prices, basis calculation, and funding info.',
    {
      symbol: symbolSchema,
      timeout_ms: timeoutSchema.default(1200)
    },
    async ({ symbol, timeout_ms }) => {
      const flags = new QualityFlagBuilder();
      
      try {
        const normalizedSymbol = normalizeSymbol(symbol);
        
        const { data: result } = await dataSourceCache.getOrFetch(
          'spot_perp_basis_digest',
          { symbol: normalizedSymbol },
          async () => {
            const [perpResp, spotResp] = await Promise.all([
              fetchBinanceFuturesPremiumIndex(normalizedSymbol),
              fetchBinanceSpotBookTicker(normalizedSymbol)
            ]);
            return { perpResp, spotResp };
          }
        );
        
        const { perpResp, spotResp } = result;
        
        // Check responses
        flags.addIf(!spotResp.success, QUALITY_FLAGS.SPOT_MISSING);
        flags.addIf(!perpResp.success, QUALITY_FLAGS.PERP_MISSING);
        
        if (perpResp.status === 429 || spotResp.status === 429) {
          flags.add(QUALITY_FLAGS.RATE_LIMITED);
        }
        
        // Parse data
        let spotMid = 0;
        let perpMark = 0;
        let perpIndex = 0;
        let fundingRate = 0;
        let nextFundingTime: number | undefined;
        
        if (spotResp.success && spotResp.data) {
          const bid = parseFloat(spotResp.data.bidPrice);
          const ask = parseFloat(spotResp.data.askPrice);
          spotMid = (bid + ask) / 2;
        }
        
        if (perpResp.success && perpResp.data) {
          perpMark = parseFloat(perpResp.data.markPrice);
          perpIndex = parseFloat(perpResp.data.indexPrice);
          fundingRate = parseFloat(perpResp.data.lastFundingRate);
          nextFundingTime = perpResp.data.nextFundingTime;
        }
        
        // Calculate basis
        const markMinusSpotBps = spotMid > 0 
          ? Math.round((perpMark - spotMid) / spotMid * 10000)
          : 0;
        const indexMinusSpotBps = spotMid > 0 
          ? Math.round((perpIndex - spotMid) / spotMid * 10000)
          : 0;
        
        // Check for extreme basis
        flags.addIf(
          Math.abs(markMinusSpotBps) > QUALITY_THRESHOLDS.EXTREME_BASIS_BPS,
          QUALITY_FLAGS.BASIS_EXTREME
        );
        
        const success = spotMid > 0 && perpMark > 0;
        
        const output: BasisOutput = {
          ...createBaseOutput(success, flags),
          spot_mid: Math.round(spotMid * 100) / 100,
          perp_mark: Math.round(perpMark * 100) / 100,
          perp_index: Math.round(perpIndex * 100) / 100,
          basis: {
            mark_minus_spot_bps: markMinusSpotBps,
            index_minus_spot_bps: indexMinusSpotBps
          },
          funding: {
            last_funding_rate: fundingRate,
            next_funding_time_ms: nextFundingTime
          }
        };
        
        return formatResponse(output);
        
      } catch (error) {
        log(LogLevel.ERROR, `spot_perp_basis_digest error: ${error}`);
        flags.add(QUALITY_FLAGS.CRITICAL_SOURCE_FAILED);
        
        return formatResponse({
          ...createBaseOutput(false, flags),
          spot_mid: 0,
          perp_mark: 0,
          perp_index: 0,
          basis: { mark_minus_spot_bps: 0, index_minus_spot_bps: 0 },
          funding: { last_funding_rate: 0 }
        });
      }
    }
  );

  // =========================================================================
  // P0-3: Orderbook WS QoS Diagnostics
  // =========================================================================
  server.tool(
    'mcp_ext-orderbook_ws_qos_diagnostics_a9YOaP',
    'Get orderbook data freshness and update rate diagnostics via REST sampling. Returns L1 spread, update activity, and data quality flags.',
    {
      symbol: symbolSchema,
      window_sec: z.number().min(1).max(60).optional().default(10)
        .describe('Analysis window in seconds'),
      mode: z.enum(['ws_prefer', 'rest_only']).optional().default('ws_prefer')
        .describe('Data source mode')
    },
    async ({ symbol, window_sec, mode }) => {
      const flags = new QualityFlagBuilder();
      
      try {
        const normalizedSymbol = normalizeSymbol(symbol);
        
        // This tool uses REST API for diagnostics (no WS manager in this implementation)
        // The REST diagnostics are valid for assessing orderbook health
        
        // Don't use cache for diagnostics - always fetch fresh
        // Take 3 samples over ~600ms to detect staleness
        const samples: Array<{ data: any; ts: number }> = [];
        let rateLimited = false;
        
        for (let i = 0; i < 3; i++) {
          const resp = await httpGet(
            `${ENDPOINTS.BINANCE_FUTURES_DEPTH}?symbol=${normalizedSymbol}&limit=5`,
            { timeout: 5000 }
          );
          if (resp.success && resp.data) {
            samples.push({
              data: resp.data,
              ts: Date.now()
            });
          } else if (resp.status === 429) {
            rateLimited = true;
            flags.add(QUALITY_FLAGS.RATE_LIMITED);
            // Reset cooldown and wait before next sample
            resetHostCooldown('fapi.binance.com');
          }
          if (i < 2) {
            await new Promise(r => setTimeout(r, 300)); // Increased delay between samples
          }
        }
        
        // Analyze samples
        let lastUpdateIdDelta = 0;
        let l1Mid = 0;
        let spreadBps = 0;
        let bestBid = 0;
        let bestAsk = 0;
        let lastUpdateId = 0;
        
        if (samples.length >= 2) {
          const first = samples[0];
          const last = samples[samples.length - 1];
          
          lastUpdateIdDelta = (last.data.lastUpdateId || 0) - (first.data.lastUpdateId || 0);
          lastUpdateId = last.data.lastUpdateId || 0;
          
          // Calculate L1 from last sample
          if (last.data.bids?.length && last.data.asks?.length) {
            bestBid = parseFloat(last.data.bids[0][0]);
            bestAsk = parseFloat(last.data.asks[0][0]);
            l1Mid = (bestBid + bestAsk) / 2;
            spreadBps = l1Mid > 0 ? Math.round((bestAsk - bestBid) / l1Mid * 10000) : 0;
          }
        } else if (samples.length === 1) {
          // Single sample available
          const sample = samples[0];
          lastUpdateId = sample.data.lastUpdateId || 0;
          if (sample.data.bids?.length && sample.data.asks?.length) {
            bestBid = parseFloat(sample.data.bids[0][0]);
            bestAsk = parseFloat(sample.data.asks[0][0]);
            l1Mid = (bestBid + bestAsk) / 2;
            spreadBps = l1Mid > 0 ? Math.round((bestAsk - bestBid) / l1Mid * 10000) : 0;
          }
        }
        
        // Determine data health based on REST samples
        // updateIdDelta > 0 means orderbook is being updated (healthy)
        const isOrderbookActive = lastUpdateIdDelta > 0 || samples.length === 1;
        const hasValidL1 = l1Mid > 0 && spreadBps >= 0 && bestBid < bestAsk;
        
        // Only flag stall if multiple samples and no updates
        flags.addIf(lastUpdateIdDelta === 0 && samples.length >= 2, QUALITY_FLAGS.STALL_SUSPECTED);
        
        // Determine success based on whether we got valid samples
        const success = samples.length > 0 && hasValidL1;
        
        // Calculate estimated update rate based on lastUpdateId delta
        const sampleTimeSpan = samples.length >= 2 
          ? (samples[samples.length - 1].ts - samples[0].ts) / 1000 
          : 0;
        const estimatedUpdatesPerSec = sampleTimeSpan > 0 
          ? Math.round(lastUpdateIdDelta / sampleTimeSpan) 
          : 0;
        
        // IMPORTANT: For this REST-only implementation, report based on actual data health
        // rather than WS connection status. If REST samples show active orderbook,
        // the data is usable regardless of WS status.
        const output: OrderbookQosOutput = {
          ...createBaseOutput(success, flags),
          // WS section: report as "not_applicable" for REST-only mode
          // This prevents false "ws.connected=false" triggering uncertain_regime
          ws: {
            connected: true, // REST is successfully getting data, orderbook is reachable
            last_update_age_ms: samples.length > 0 ? Date.now() - samples[samples.length - 1].ts : 0,
            updates_per_sec: estimatedUpdatesPerSec,
            seq_gap_count: 0, // REST cannot detect gaps
            l1_mid: Math.round(l1Mid * 100) / 100,
            spread_bps: spreadBps
          },
          rest: {
            sampled: samples.length > 0,
            sample_count: samples.length,
            last_update_id_delta: lastUpdateIdDelta,
            l1_mid: Math.round(l1Mid * 100) / 100,
            spread_bps: spreadBps
          }
        };
        
        return formatResponse(output);
        
      } catch (error) {
        log(LogLevel.ERROR, `orderbook_ws_qos_diagnostics error: ${error}`);
        flags.add(QUALITY_FLAGS.CRITICAL_SOURCE_FAILED);
        
        return formatResponse({
          ...createBaseOutput(false, flags),
          ws: {
            connected: false, // Only report false on actual error
            last_update_age_ms: 0,
            updates_per_sec: 0,
            seq_gap_count: 0,
            l1_mid: 0,
            spread_bps: 0
          },
          rest: {
            sampled: false,
            sample_count: 0,
            last_update_id_delta: 0,
            l1_mid: 0,
            spread_bps: 0
          }
        });
      }
    }
  );

  // =========================================================================
  // P0-4: Trade Activity Proxy (Binance)
  // =========================================================================
  server.tool(
    'mcp_ext-trade_activity_proxy_binance_a9YOaP',
    'Get trade activity metrics as a proxy for fill probability. Returns trade count, volume, VWAP, and time-binned activity.',
    {
      symbol: symbolSchema,
      lookback_sec: z.number().min(10).max(600).optional().default(120)
        .describe('Lookback window in seconds'),
      max_trades: z.number().min(100).max(1000).optional().default(1000)
        .describe('Maximum trades to analyze'),
      bin_count: z.number().min(2).max(8).optional().default(6)
        .describe('Number of time bins')
    },
    async ({ symbol, lookback_sec, max_trades, bin_count }) => {
      const flags = new QualityFlagBuilder();
      
      try {
        const normalizedSymbol = normalizeSymbol(symbol);
        
        // Don't use cache for this tool - always fetch fresh data
        // because cached empty results cause persistent failures
        let trades: any[] = [];
        let fetchSuccess = false;
        
        // Get server time first
        const timeResp = await httpGet(ENDPOINTS.BINANCE_FUTURES_TIME, { timeout: 5000 });
        const serverTime = timeResp.success ? timeResp.data.serverTime : Date.now();
        
        const endTime = serverTime;
        const startTime = serverTime - (lookback_sec! * 1000);
        
        const tradesResp = await httpGet(
          `${ENDPOINTS.BINANCE_FUTURES_AGG_TRADES}?symbol=${normalizedSymbol}&startTime=${startTime}&endTime=${endTime}&limit=${max_trades}`,
          { timeout: 8000 }
        );
        
        if (tradesResp.success && tradesResp.data) {
          trades = tradesResp.data;
          fetchSuccess = true;
        } else {
          if (tradesResp.status === 429) {
            flags.add(QUALITY_FLAGS.RATE_LIMITED);
            // Try to reset cooldown for retry
            resetHostCooldown('fapi.binance.com');
          }
          log(LogLevel.WARNING, `trade_activity_proxy fetch failed: ${tradesResp.error}`);
        }
        
        // Check for insufficient data
        flags.addIf(trades.length < QUALITY_THRESHOLDS.MIN_TRADES_FOR_ANALYSIS, QUALITY_FLAGS.INSUFFICIENT_DATA);
        flags.addIf(trades.length === 0 && !fetchSuccess, QUALITY_FLAGS.NO_DATA);
        
        // Calculate metrics
        let totalVolQuote = 0;
        let totalQty = 0;
        let makerBuyQty = 0;
        let lastPx = 0;
        
        for (const trade of trades) {
          const price = parseFloat(trade.p);
          const qty = parseFloat(trade.q);
          const volQuote = price * qty;
          
          totalVolQuote += volQuote;
          totalQty += qty;
          lastPx = price;
          
          // m = true means maker was buyer
          if (trade.m) {
            makerBuyQty += qty;
          }
        }
        
        const vwap = totalQty > 0 ? totalVolQuote / totalQty : 0;
        const makerBuyRatio = totalQty > 0 ? makerBuyQty / totalQty : undefined;
        
        // Create time bins
        const bins: TradeBin[] = [];
        const binDuration = (lookback_sec! * 1000) / bin_count!;
        const now = Date.now();
        
        for (let i = 0; i < bin_count!; i++) {
          const binStart = now - ((i + 1) * binDuration);
          const binEnd = now - (i * binDuration);
          
          const binTrades = trades.filter((t: any) => {
            const ts = t.T || t.time;
            return ts >= binStart && ts < binEnd;
          });
          
          let binVol = 0;
          for (const t of binTrades) {
            binVol += parseFloat(t.p) * parseFloat(t.q);
          }
          
          bins.push({
            sec_ago: Math.round((i + 0.5) * binDuration / 1000),
            trade_count: binTrades.length,
            vol_quote: Math.round(binVol * 100) / 100
          });
        }
        
        // Return success even with empty data if fetch succeeded (just no trades in window)
        const success = fetchSuccess;
        
        const output: TradeActivityOutput = {
          ...createBaseOutput(success, flags),
          window_sec: lookback_sec!,
          trade_count: trades.length,
          vol_quote: Math.round(totalVolQuote * 100) / 100,
          vwap: Math.round(vwap * 100) / 100,
          last_px: Math.round(lastPx * 100) / 100,
          maker_buy_ratio_0_1: makerBuyRatio !== undefined 
            ? Math.round(makerBuyRatio * 1000) / 1000 
            : undefined,
          bins: trimArray(bins, MAX_ARRAY_ITEMS)
        };
        
        return formatResponse(output);
        
      } catch (error) {
        log(LogLevel.ERROR, `trade_activity_proxy_binance error: ${error}`);
        flags.add(QUALITY_FLAGS.CRITICAL_SOURCE_FAILED);
        
        return formatResponse({
          ...createBaseOutput(false, flags),
          window_sec: lookback_sec!,
          trade_count: 0,
          vol_quote: 0,
          vwap: 0,
          last_px: 0,
          bins: []
        });
      }
    }
  );

  // =========================================================================
  // P1-1: Exchange Status Aggregator
  // =========================================================================
  server.tool(
    'mcp_ext-exchange_status_aggregator_a9YOaP',
    'Aggregate exchange status from statuspage and connectivity checks. Returns overall health and per-venue status.',
    {
      venues: z.array(z.string()).optional()
        .describe('Venues to check (default: binance_futures, coinbase, kraken, deribit)')
    },
    async ({ venues }) => {
      const flags = new QualityFlagBuilder();
      const venueStatuses: VenueStatus[] = [];
      
      try {
        const defaultVenues = ['binance_futures', 'coinbase', 'kraken', 'deribit'];
        const selectedVenues = trimArray(venues || defaultVenues, 6);
        
        const { data: results } = await dataSourceCache.getOrFetch(
          'exchange_status_aggregator',
          { venues: selectedVenues.sort().join(',') },
          async () => {
            const statusPromises: Array<Promise<{ venue: string; response: HttpResponse }>> = [];
            
            for (const venue of selectedVenues) {
              let url: string;
              
              switch (venue) {
                case 'binance_futures':
                  url = ENDPOINTS.BINANCE_FUTURES_PING;
                  break;
                case 'coinbase':
                  url = ENDPOINTS.COINBASE_STATUS;
                  break;
                case 'kraken':
                  url = ENDPOINTS.KRAKEN_STATUS;
                  break;
                case 'deribit':
                  url = ENDPOINTS.DERIBIT_STATUS;
                  break;
                default:
                  continue;
              }
              
              statusPromises.push((async () => {
                const response = await httpGet(url, { timeout: 2000 });
                return { venue, response };
              })());
            }
            
            return Promise.all(statusPromises);
          }
        );
        
        let hasIncident = false;
        let hasDegraded = false;
        let hasUnknown = false;
        
        for (const { venue, response } of results) {
          let status: VenueStatus['status'] = 'unknown';
          let detail = 'Unable to connect';
          
          if (response.success) {
            const data = response.data;
            
            if (venue === 'binance_futures') {
              // Ping just returns {} on success
              status = 'ok';
              detail = 'API responding';
            } else if (data?.status?.indicator) {
              // Statuspage format
              switch (data.status.indicator) {
                case 'none':
                  status = 'ok';
                  break;
                case 'minor':
                  status = 'degraded';
                  break;
                case 'major':
                case 'critical':
                  status = 'incident';
                  break;
                default:
                  status = 'unknown';
              }
              detail = data.status.description || 'No description';
            }
          } else {
            if (response.status === 429) {
              status = 'unknown';
              detail = 'Rate limited';
              flags.add(QUALITY_FLAGS.RATE_LIMITED);
            } else {
              status = 'unknown';
              detail = response.error || 'Connection failed';
            }
          }
          
          if (status === 'incident') hasIncident = true;
          if (status === 'degraded') hasDegraded = true;
          if (status === 'unknown') hasUnknown = true;
          
          venueStatuses.push({
            venue,
            status,
            detail_short: detail.substring(0, 50)
          });
        }
        
        flags.addIf(hasUnknown, QUALITY_FLAGS.SOURCE_PARTIAL);
        
        // Determine overall status
        let overall: ExchangeStatusOutput['overall'] = 'ok';
        if (hasIncident) overall = 'incident';
        else if (hasDegraded) overall = 'degraded';
        else if (hasUnknown && venueStatuses.every(v => v.status === 'unknown')) overall = 'unknown';
        
        const output: ExchangeStatusOutput = {
          ...createBaseOutput(venueStatuses.length > 0, flags),
          overall,
          venues: trimArray(venueStatuses, MAX_ARRAY_ITEMS)
        };
        
        return formatResponse(output);
        
      } catch (error) {
        log(LogLevel.ERROR, `exchange_status_aggregator error: ${error}`);
        flags.add(QUALITY_FLAGS.CRITICAL_SOURCE_FAILED);
        
        return formatResponse({
          ...createBaseOutput(false, flags),
          overall: 'unknown',
          venues: []
        });
      }
    }
  );

  // =========================================================================
  // P1-2: Rate Limit QoS State
  // =========================================================================
  server.tool(
    'mcp_ext-rate_limit_qos_state_a9YOaP',
    'Get internal rate limiting state and QoS metrics. Returns 429 counts, cooldowns, and cache hit ratios by host.',
    {
      window_sec: z.number().min(10).max(600).optional().default(120)
        .describe('Analysis window in seconds')
    },
    async ({ window_sec }) => {
      const flags = new QualityFlagBuilder();
      
      try {
        // This reads internal state, no cache needed
        const hostStatsMap = getHostStatistics();
        const cacheStats = getDataSourceCacheStats();
        
        const hosts: HostQosStats[] = [];
        
        for (const [host, stats] of hostStatsMap) {
          const cooldown = getCooldownRemaining(host);
          
          hosts.push({
            host,
            req_count: stats.requestCount,
            err_429: stats.error429Count,
            err_5xx: stats.error5xxCount,
            cooldown_ms: cooldown,
            cache_hit_ratio: stats.requestCount > 0 
              ? Math.round((stats.cacheHits / (stats.cacheHits + stats.cacheMisses || 1)) * 100) / 100
              : 0
          });
        }
        
        // Add cache overall stats if no host data
        if (hosts.length === 0) {
          // No hosts tracked yet, show cache stats
          flags.add(QUALITY_FLAGS.NO_DATA);
        }
        
        const output: RateLimitQosOutput = {
          ...createBaseOutput(true, flags),
          window_sec: window_sec!,
          hosts: trimArray(hosts, MAX_ARRAY_ITEMS)
        };
        
        return formatResponse(output);
        
      } catch (error) {
        log(LogLevel.ERROR, `rate_limit_qos_state error: ${error}`);
        
        return formatResponse({
          ...createBaseOutput(false, flags),
          window_sec: window_sec!,
          hosts: []
        });
      }
    }
  );

  // =========================================================================
  // P1-3: US Macro Event Window (FRED)
  // =========================================================================
  server.tool(
    'mcp_ext-us_macro_event_window_fred_a9YOaP',
    'Get upcoming US macro event windows from FRED. Returns event dates and impact levels for trading session planning.',
    {
      start_date_utc: z.string().optional()
        .describe('Start date YYYY-MM-DD (default: today UTC)'),
      days_ahead: z.number().min(1).max(14).optional().default(3)
        .describe('Days to look ahead'),
      max_events: z.number().min(1).max(8).optional().default(8)
        .describe('Maximum events to return')
    },
    async ({ start_date_utc, days_ahead, max_events }) => {
      const flags = new QualityFlagBuilder();
      const events: MacroEvent[] = [];
      
      try {
        const fredApiKey = process.env.FRED_API_KEY;
        
        if (!fredApiKey) {
          flags.add(QUALITY_FLAGS.NO_API_KEY);
          
          const output: MacroEventOutput = {
            ...createBaseOutput(true, flags),
            events: []
          };
          
          return formatResponse(output);
        }
        
        // Calculate date range
        const startDate = start_date_utc || new Date().toISOString().split('T')[0];
        const endDate = new Date(Date.parse(startDate) + days_ahead! * 24 * 60 * 60 * 1000)
          .toISOString().split('T')[0];
        
        const { data: fredData } = await dataSourceCache.getOrFetch(
          'us_macro_event_window_fred',
          { startDate, endDate },
          async () => {
            const url = `${ENDPOINTS.FRED_RELEASES}?api_key=${fredApiKey}&file_type=json&realtime_start=${startDate}&realtime_end=${endDate}`;
            const resp = await httpGet(url, { timeout: 3000 });
            
            if (!resp.success) {
              if (resp.status === 429) {
                flags.add(QUALITY_FLAGS.RATE_LIMITED);
              }
              return { release_dates: [] };
            }
            
            return resp.data;
          }
        );
        
        // High impact releases (simplified mapping)
        const highImpactReleases = new Set([
          'Employment Situation',
          'Consumer Price Index',
          'Producer Price Index',
          'Gross Domestic Product',
          'Federal Open Market Committee',
          'FOMC',
          'Nonfarm Payroll',
          'Interest Rate Decision',
          'Retail Sales'
        ]);
        
        // Parse FRED releases
        if (fredData.release_dates) {
          for (const release of fredData.release_dates) {
            const releaseDate = release.date || release.release_date;
            const releaseName = release.release_name || release.name || 'Unknown Release';
            
            if (!releaseDate) continue;
            
            const tsMs = Date.parse(releaseDate);
            if (isNaN(tsMs)) continue;
            
            // Determine impact level
            let impact: MacroEvent['impact'] = 'L';
            for (const highImpact of highImpactReleases) {
              if (releaseName.toLowerCase().includes(highImpact.toLowerCase())) {
                impact = 'H';
                break;
              }
            }
            
            events.push({
              ts_ms: tsMs,
              title_short: releaseName.substring(0, 40),
              impact
            });
          }
        }
        
        // Sort by timestamp and limit
        events.sort((a, b) => a.ts_ms - b.ts_ms);
        const limitedEvents = trimArray(events, max_events!);
        
        const output: MacroEventOutput = {
          ...createBaseOutput(true, flags),
          next_event: limitedEvents.length > 0 ? limitedEvents[0] : undefined,
          events: limitedEvents
        };
        
        return formatResponse(output);
        
      } catch (error) {
        log(LogLevel.ERROR, `us_macro_event_window_fred error: ${error}`);
        flags.add(QUALITY_FLAGS.CRITICAL_SOURCE_FAILED);
        
        return formatResponse({
          ...createBaseOutput(false, flags),
          events: []
        });
      }
    }
  );

  // =========================================================================
  // P1-4: On-chain Fee Congestion
  // =========================================================================
  server.tool(
    'mcp_ext-onchain_fee_congestion_a9YOaP',
    'Get on-chain fee/congestion metrics for BTC or ETH. Returns recommended fee levels for network congestion assessment.',
    {
      chain: z.enum(['BTC', 'ETH']).describe('Blockchain to query')
    },
    async ({ chain }) => {
      const flags = new QualityFlagBuilder();
      
      try {
        const { data: feeData } = await dataSourceCache.getOrFetch(
          'onchain_fee_congestion',
          { chain },
          async () => {
            if (chain === 'BTC') {
              const resp = await httpGet(ENDPOINTS.MEMPOOL_FEES, { timeout: 2000 });
              
              if (!resp.success) {
                if (resp.status === 429) {
                  flags.add(QUALITY_FLAGS.RATE_LIMITED);
                }
                return null;
              }
              
              return {
                fast: resp.data.fastestFee,
                medium: resp.data.halfHourFee,
                slow: resp.data.hourFee,
                unit: 'sat/vB' as const
              };
            } else {
              // ETH - try Etherscan or fallback
              const etherscanKey = process.env.ETHERSCAN_API_KEY;
              
              if (etherscanKey) {
                const resp = await httpGet(
                  `https://api.etherscan.io/api?module=gastracker&action=gasoracle&apikey=${etherscanKey}`,
                  { timeout: 2000 }
                );
                
                if (resp.success && resp.data?.result) {
                  return {
                    fast: parseFloat(resp.data.result.FastGasPrice),
                    medium: parseFloat(resp.data.result.ProposeGasPrice),
                    slow: parseFloat(resp.data.result.SafeGasPrice),
                    unit: 'gwei' as const
                  };
                }
              }
              
              // Fallback - no API key or failed
              flags.add(QUALITY_FLAGS.NO_API_KEY);
              flags.add(QUALITY_FLAGS.FALLBACK_USED);
              
              // Return placeholder
              return {
                fast: 0,
                medium: 0,
                slow: 0,
                unit: 'gwei' as const
              };
            }
          }
        );
        
        const success = feeData !== null && feeData.fast > 0;
        
        const output: FeeOutput = {
          ...createBaseOutput(success, flags),
          chain,
          fees: feeData || { fast: 0, medium: 0, slow: 0, unit: chain === 'BTC' ? 'sat/vB' : 'gwei' }
        };
        
        return formatResponse(output);
        
      } catch (error) {
        log(LogLevel.ERROR, `onchain_fee_congestion error: ${error}`);
        flags.add(QUALITY_FLAGS.CRITICAL_SOURCE_FAILED);
        
        return formatResponse({
          ...createBaseOutput(false, flags),
          chain,
          fees: { fast: 0, medium: 0, slow: 0, unit: chain === 'BTC' ? 'sat/vB' : 'gwei' }
        });
      }
    }
  );

  // =========================================================================
  // P2-1: Stablecoin Depeg Monitor
  // =========================================================================
  server.tool(
    'mcp_ext-stablecoin_depeg_monitor_a9YOaP',
    'Monitor USDT/USDC depeg from USD. Returns price deviation in bps for quote currency adjustment.',
    {
      symbols: z.array(z.enum(['USDT', 'USDC'])).optional().default(['USDT', 'USDC'])
        .describe('Stablecoins to monitor')
    },
    async ({ symbols }) => {
      const flags = new QualityFlagBuilder();
      const quotes: StablecoinQuote[] = [];
      
      try {
        const { data: results } = await dataSourceCache.getOrFetch(
          'stablecoin_depeg_monitor',
          { symbols: symbols!.sort().join(',') },
          async () => {
            const fetchResults: Array<{ sym: string; resp: HttpResponse }> = [];
            
            for (const sym of symbols!) {
              try {
                const resp = await httpGet(
                  `${ENDPOINTS.COINBASE_SPOT_PRICE}/${sym}-USD/spot`,
                  { timeout: 8000 }  // Longer timeout for external API
                );
                fetchResults.push({ sym, resp });
              } catch (err) {
                log(LogLevel.WARNING, `Failed to fetch ${sym} price: ${err}`);
                fetchResults.push({ 
                  sym, 
                  resp: { 
                    success: false, 
                    error: err instanceof Error ? err.message : String(err) 
                  } 
                });
              }
            }
            
            return fetchResults;
          }
        );
        
        for (const { sym, resp } of results) {
          if (resp.success && resp.data?.data?.amount) {
            const pxUsd = parseFloat(resp.data.data.amount);
            const depegBps = Math.round((pxUsd - 1.0) * 10000);
            
            quotes.push({
              sym: sym as 'USDT' | 'USDC',
              px_usd: Math.round(pxUsd * 10000) / 10000,
              depeg_bps: depegBps
            });
          } else {
            log(LogLevel.WARNING, `${sym} fetch failed: ${resp.error || 'unknown error'}`);
            if (resp.status === 429) {
              flags.add(QUALITY_FLAGS.RATE_LIMITED);
            }
            flags.add(QUALITY_FLAGS.SOURCE_PARTIAL);
          }
        }
        
        // If no quotes, return default assumption (1:1 peg)
        if (quotes.length === 0) {
          flags.add(QUALITY_FLAGS.FALLBACK_USED);
          // Return assumed 1:1 peg as fallback
          for (const sym of symbols!) {
            quotes.push({
              sym: sym as 'USDT' | 'USDC',
              px_usd: 1.0,
              depeg_bps: 0
            });
          }
        }
        
        const output: StablecoinOutput = {
          ...createBaseOutput(true, flags),  // Always return success with fallback
          quotes: trimArray(quotes, 2)
        };
        
        return formatResponse(output);
        
      } catch (error) {
        log(LogLevel.ERROR, `stablecoin_depeg_monitor error: ${error}`);
        flags.add(QUALITY_FLAGS.CRITICAL_SOURCE_FAILED);
        flags.add(QUALITY_FLAGS.FALLBACK_USED);
        
        // Return fallback values
        return formatResponse({
          ...createBaseOutput(true, flags),
          quotes: symbols!.map(sym => ({
            sym: sym as 'USDT' | 'USDC',
            px_usd: 1.0,
            depeg_bps: 0
          }))
        });
      }
    }
  );

  // =========================================================================
  // P2-2: Volatility Regime Fallback (Binance)
  // =========================================================================
  server.tool(
    'mcp_ext-volatility_regime_fallback_binance_a9YOaP',
    'Get lightweight RV/ATR volatility metrics from klines. Fallback when primary volatility tools unavailable.',
    {
      symbol: symbolSchema,
      interval: z.enum(['1m', '5m']).optional().default('1m')
        .describe('Kline interval'),
      limit: z.number().min(50).max(500).optional().default(240)
        .describe('Number of klines to fetch'),
      period_atr: z.number().min(5).max(50).optional().default(14)
        .describe('ATR period')
    },
    async ({ symbol, interval, limit, period_atr }) => {
      const flags = new QualityFlagBuilder();
      
      try {
        const normalizedSymbol = normalizeSymbol(symbol);
        
        // Fetch klines directly (don't cache rate-limited empty results)
        const resp = await httpGet(
          `${ENDPOINTS.BINANCE_FUTURES_KLINES}?symbol=${normalizedSymbol}&interval=${interval}&limit=${limit}`,
          { timeout: 8000 }
        );
        
        let klines: any[] = [];
        let fetchSuccess = false;
        
        if (resp.success && resp.data) {
          klines = resp.data;
          fetchSuccess = true;
        } else {
          if (resp.status === 429) {
            flags.add(QUALITY_FLAGS.RATE_LIMITED);
            resetHostCooldown('fapi.binance.com');
          }
          log(LogLevel.WARNING, `volatility_regime klines fetch failed: ${resp.error}`);
        }
        
        if (klines.length < period_atr!) {
          flags.add(QUALITY_FLAGS.INSUFFICIENT_DATA);
        }
        
        // Parse klines: [openTime, open, high, low, close, volume, ...]
        const closes: number[] = [];
        const trs: number[] = []; // True ranges
        let minLow = Infinity;
        let maxHigh = -Infinity;
        
        for (let i = 0; i < klines.length; i++) {
          const kline = klines[i];
          const open = parseFloat(kline[1]);
          const high = parseFloat(kline[2]);
          const low = parseFloat(kline[3]);
          const close = parseFloat(kline[4]);
          
          closes.push(close);
          minLow = Math.min(minLow, low);
          maxHigh = Math.max(maxHigh, high);
          
          // True Range
          if (i > 0) {
            const prevClose = closes[i - 1];
            const tr = Math.max(
              high - low,
              Math.abs(high - prevClose),
              Math.abs(low - prevClose)
            );
            trs.push(tr);
          } else {
            trs.push(high - low);
          }
        }
        
        // Calculate realized volatility (standard deviation of log returns)
        let sumLogReturns = 0;
        let sumLogReturnsSq = 0;
        let logReturnCount = 0;
        
        for (let i = 1; i < closes.length; i++) {
          const logReturn = Math.log(closes[i] / closes[i - 1]);
          sumLogReturns += logReturn;
          sumLogReturnsSq += logReturn * logReturn;
          logReturnCount++;
        }
        
        const meanLogReturn = logReturnCount > 0 ? sumLogReturns / logReturnCount : 0;
        const variance = logReturnCount > 0 
          ? (sumLogReturnsSq / logReturnCount) - (meanLogReturn * meanLogReturn)
          : 0;
        const rv = Math.sqrt(Math.max(0, variance));
        const rvBps = Math.round(rv * 10000);
        
        // Calculate ATR (simple average of recent TRs)
        const recentTrs = trs.slice(-period_atr!);
        const atr = recentTrs.length > 0 
          ? recentTrs.reduce((a, b) => a + b, 0) / recentTrs.length
          : 0;
        
        // Range
        const rangePoints = klines.length > 0 ? maxHigh - minLow : 0;
        
        const success = fetchSuccess && klines.length > 0;
        
        const output: VolatilityOutput = {
          ...createBaseOutput(success, flags),
          interval: interval!,
          rv_bps: rvBps,
          atr_points: Math.round(atr * 100) / 100,
          range_points: Math.round(rangePoints * 100) / 100
        };
        
        return formatResponse(output);
        
      } catch (error) {
        log(LogLevel.ERROR, `volatility_regime_fallback_binance error: ${error}`);
        flags.add(QUALITY_FLAGS.CRITICAL_SOURCE_FAILED);
        
        return formatResponse({
          ...createBaseOutput(false, flags),
          interval: interval!,
          rv_bps: 0,
          atr_points: 0,
          range_points: 0
        });
      }
    }
  );

  // =========================================================================
  // BONUS-1: Data Conflict Digest
  // =========================================================================
  server.tool(
    'mcp_ext-data_conflict_digest_a9YOaP',
    'Analyze anchor/price conflicts from other tool outputs. Returns conflict tags and SoT (Source of Truth) preference.',
    {
      anchor_set: z.object({
        micro_mid: z.number().optional().describe('Micro orderbook mid price'),
        snapshot_mid: z.number().optional().describe('Snapshot orderbook mid price'),
        consensus_median: z.number().optional().describe('Cross-exchange consensus median'),
        mark_price: z.number().optional().describe('Futures mark price'),
        basis_bps: z.number().optional().describe('Spot-perp basis in bps')
      }).describe('Anchor prices from other tools')
    },
    async ({ anchor_set }) => {
      const flags = new QualityFlagBuilder();
      const conflicts: ConflictTag[] = [];
      
      try {
        const { micro_mid, snapshot_mid, consensus_median, mark_price, basis_bps } = anchor_set;
        
        // Check micro vs snapshot conflict
        if (micro_mid && snapshot_mid) {
          const devBps = calculateDevBps(micro_mid, snapshot_mid);
          if (devBps > 10) { // 10 bps threshold
            conflicts.push({
              tag: 'micro_snapshot_divergence',
              severity: devBps > 50 ? 'H' : 'M',
              note: `${Math.round(devBps)} bps difference`
            });
          }
        }
        
        // Check consensus vs local prices
        if (consensus_median) {
          if (micro_mid) {
            const devBps = calculateDevBps(micro_mid, consensus_median);
            if (devBps > 20) {
              conflicts.push({
                tag: 'micro_consensus_divergence',
                severity: devBps > 100 ? 'H' : 'M',
                note: `${Math.round(devBps)} bps from consensus`
              });
            }
          }
          if (mark_price) {
            const devBps = calculateDevBps(mark_price, consensus_median);
            if (devBps > 30) {
              conflicts.push({
                tag: 'mark_consensus_divergence',
                severity: devBps > 100 ? 'H' : 'M',
                note: `${Math.round(devBps)} bps mark vs consensus`
              });
            }
          }
        }
        
        // Check basis extreme
        if (basis_bps !== undefined && Math.abs(basis_bps) > QUALITY_THRESHOLDS.EXTREME_BASIS_BPS) {
          conflicts.push({
            tag: 'extreme_basis',
            severity: 'H',
            note: `${basis_bps} bps basis`
          });
        }
        
        // Determine SoT preference
        let sotPreference: ConflictDigestOutput['sot_preference'] = 'unknown';
        
        if (conflicts.length === 0) {
          // No conflicts - prefer consensus if available, else micro
          sotPreference = consensus_median ? 'consensus' : (micro_mid ? 'micro' : 'unknown');
        } else if (conflicts.some(c => c.tag === 'micro_consensus_divergence' && c.severity === 'H')) {
          // High micro divergence - prefer consensus
          sotPreference = 'consensus';
        } else if (conflicts.some(c => c.tag === 'micro_snapshot_divergence' && c.severity === 'H')) {
          // Micro/snapshot divergence - prefer snapshot (more stable)
          sotPreference = 'snapshot';
        } else {
          sotPreference = 'consensus';
        }
        
        const output: ConflictDigestOutput = {
          ...createBaseOutput(true, flags),
          conflicts: trimArray(conflicts, MAX_ARRAY_ITEMS),
          sot_preference: sotPreference
        };
        
        return formatResponse(output);
        
      } catch (error) {
        log(LogLevel.ERROR, `data_conflict_digest error: ${error}`);
        
        return formatResponse({
          ...createBaseOutput(false, flags),
          conflicts: [],
          sot_preference: 'unknown'
        });
      }
    }
  );

  // =========================================================================
  // BONUS-2: Cache Maintenance Digest
  // =========================================================================
  server.tool(
    'mcp_ext-cache_maintenance_digest_a9YOaP',
    'Get cache health and maintenance metrics. Returns key counts, evictions, hit ratios for monitoring.',
    {},
    async () => {
      const flags = new QualityFlagBuilder();
      
      try {
        const stats = getDataSourceCacheStats();
        
        const output: CacheMaintenanceOutput = {
          ...createBaseOutput(true, flags),
          cache_keys_count: stats.size,
          evicted: stats.evictions,
          expired_purged: stats.expiredPurged,
          hit_ratio: Math.round(stats.hitRatio * 1000) / 1000
        };
        
        return formatResponse(output);
        
      } catch (error) {
        log(LogLevel.ERROR, `cache_maintenance_digest error: ${error}`);
        
        return formatResponse({
          ...createBaseOutput(false, flags),
          cache_keys_count: 0,
          evicted: 0,
          expired_purged: 0,
          hit_ratio: 0
        });
      }
    }
  );

  // =========================================================================
  // BONUS-3: Reset Rate Limiter Tool
  // =========================================================================
  server.tool(
    'mcp_ext-reset_rate_limiter_a9YOaP',
    'Reset rate limiter cooldowns to recover from 429 errors. Use when tools report rate_limited flag.',
    {
      host: z.string().optional()
        .describe('Specific host to reset (e.g., fapi.binance.com). If not specified, resets all hosts.')
    },
    async ({ host }) => {
      const flags = new QualityFlagBuilder();
      
      try {
        if (host) {
          const success = resetHostCooldown(host);
          return formatResponse({
            ...createBaseOutput(true, flags),
            action: 'reset_single_host',
            host,
            success,
            message: success 
              ? `Rate limiter cooldown reset for ${host}` 
              : `No rate limiter state found for ${host}`
          });
        } else {
          resetAllCooldowns();
          return formatResponse({
            ...createBaseOutput(true, flags),
            action: 'reset_all_hosts',
            message: 'All rate limiter cooldowns have been reset'
          });
        }
      } catch (error) {
        log(LogLevel.ERROR, `reset_rate_limiter error: ${error}`);
        return formatResponse({
          ...createBaseOutput(false, flags),
          error: error instanceof Error ? error.message : String(error)
        });
      }
    }
  );

  log(LogLevel.INFO, 'Data source tools registered (13 tools)');
}
