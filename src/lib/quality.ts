/**
 * Quality Flags Module
 * Standardized quality flags and helpers for data source tools
 * 
 * 数据质量标志模块
 * 数据源工具的标准化质量标志和辅助函数
 */

// Standard quality flags
export const QUALITY_FLAGS = {
  // Data availability
  SOURCE_PARTIAL: 'source_partial',           // Less than expected sources responded
  NO_DATA: 'no_data',                         // No data returned
  INSUFFICIENT_DATA: 'insufficient_trade_data', // Not enough data for analysis
  
  // Rate limiting
  RATE_LIMITED: 'rate_limited',               // Got 429 response
  THROTTLED: 'throttled',                     // Internal throttle triggered
  
  // Staleness
  STALE_SOURCE: 'stale_source',               // Data older than expected TTL
  TIME_ROLLBACK: 'time_rollback',             // Timestamp went backwards
  
  // Schema issues
  SCHEMA_VIOLATION: 'schema_violation',       // Response doesn't match expected schema
  TRIMMED_OUTPUT: 'trimmed_output',           // Output was truncated for size
  
  // Critical failures
  CRITICAL_SOURCE_FAILED: 'critical_source_failed', // Essential data source failed
  
  // WS specific
  WS_DISCONNECTED: 'ws_disconnected',         // WebSocket not connected
  WS_STALE: 'ws_stale',                       // WS data is stale
  STALL_SUSPECTED: 'stall_suspected',         // Data not updating
  
  // Data quality
  DEV_HIGH: 'dev_high',                       // High deviation detected
  QUOTE_MISMATCH_USD_USDT: 'quote_mismatch_usd_usdt', // Mixed USD/USDT quotes
  BASIS_EXTREME: 'basis_extreme',             // Extreme basis detected
  SPOT_MISSING: 'spot_missing',               // Spot data unavailable
  PERP_MISSING: 'perp_missing',               // Perpetual data unavailable
  
  // External services
  NO_API_KEY: 'no_api_key',                   // API key not configured
  FALLBACK_USED: 'fallback_used',             // Fallback data source used
  REST_SAMPLE_USED: 'rest_sample_used',       // REST fallback instead of WS
} as const;

export type QualityFlag = typeof QUALITY_FLAGS[keyof typeof QUALITY_FLAGS];

/**
 * Quality flag builder for consistent flag management
 */
export class QualityFlagBuilder {
  private flags: Set<QualityFlag> = new Set();
  private maxFlags: number;
  
  constructor(maxFlags: number = 6) {
    this.maxFlags = maxFlags;
  }
  
  /**
   * Add a flag if condition is true
   */
  addIf(condition: boolean, flag: QualityFlag): this {
    if (condition && this.flags.size < this.maxFlags) {
      this.flags.add(flag);
    }
    return this;
  }
  
  /**
   * Add a flag unconditionally
   */
  add(flag: QualityFlag): this {
    if (this.flags.size < this.maxFlags) {
      this.flags.add(flag);
    }
    return this;
  }
  
  /**
   * Check if a flag exists
   */
  has(flag: QualityFlag): boolean {
    return this.flags.has(flag);
  }
  
  /**
   * Check if any critical flag exists
   */
  hasCritical(): boolean {
    const criticalFlags: QualityFlag[] = [
      QUALITY_FLAGS.CRITICAL_SOURCE_FAILED,
      QUALITY_FLAGS.NO_DATA,
    ];
    return criticalFlags.some(f => this.flags.has(f));
  }
  
  /**
   * Get flags as array (limited to maxFlags)
   */
  toArray(): QualityFlag[] {
    return Array.from(this.flags).slice(0, this.maxFlags);
  }
  
  /**
   * Get count of flags
   */
  get count(): number {
    return this.flags.size;
  }
}

/**
 * Check if timestamp is stale (older than threshold)
 */
export function isStale(timestampMs: number, thresholdMs: number): boolean {
  return Date.now() - timestampMs > thresholdMs;
}

/**
 * Check for time rollback (new timestamp older than previous)
 */
export function hasTimeRollback(newTs: number, previousTs: number): boolean {
  return newTs < previousTs && previousTs - newTs > 1000; // Allow 1s tolerance
}

/**
 * Calculate age in milliseconds
 */
export function calculateAge(timestampMs: number): number {
  return Math.max(0, Date.now() - timestampMs);
}

/**
 * Thresholds for quality checks (internal, not exposed to output)
 */
export const QUALITY_THRESHOLDS = {
  // Deviation thresholds (bps)
  MAX_DEV_BPS: 100,           // 1% max deviation for consensus
  EXTREME_BASIS_BPS: 200,     // 2% extreme basis
  
  // Staleness thresholds (ms)
  MAX_QUOTE_AGE_MS: 5000,     // 5s for quotes
  MAX_WS_UPDATE_AGE_MS: 3000, // 3s for WS updates
  MAX_TRADE_DATA_AGE_MS: 30000, // 30s for trade data
  
  // Minimum counts
  MIN_QUOTES_FOR_CONSENSUS: 3,
  MIN_TRADES_FOR_ANALYSIS: 10,
} as const;
