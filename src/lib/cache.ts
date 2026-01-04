/**
 * Enhanced Cache Module for Data Source Tools
 * LRU + TTL cache with tool+params fingerprinting
 * 
 * 数据源工具增强缓存模块
 * 带有工具+参数指纹的LRU + TTL缓存
 */

import { LRUCache } from 'lru-cache';
import { log, LogLevel } from '../utils/logging.js';
import { createHash } from 'crypto';

// Cache configuration
const MAX_CACHE_ENTRIES = 500;
const DEFAULT_TTL_MS = 5000; // 5 seconds

// Tool-specific TTL configuration (ms)
export const TOOL_TTL: Record<string, number> = {
  'cross_exchange_anchor_consensus': 2000,   // 2s - fast anchor
  'spot_perp_basis_digest': 2000,            // 2s
  'orderbook_ws_qos_diagnostics': 1000,      // 1s - diagnostic needs fresh
  'trade_activity_proxy_binance': 2000,      // 2s
  'exchange_status_aggregator': 30000,       // 30s - status doesn't change fast
  'rate_limit_qos_state': 1000,              // 1s
  'us_macro_event_window_fred': 21600000,    // 6h
  'onchain_fee_congestion': 30000,           // 30s
  'stablecoin_depeg_monitor': 10000,         // 10s
  'volatility_regime_fallback_binance': 5000, // 5s
  'data_conflict_digest': 0,                  // No cache (pure computation)
  'cache_maintenance_digest': 0,              // No cache (returns cache state)
};

/**
 * Cache entry structure
 */
interface CacheEntry<T> {
  data: T;
  cachedAt: number;
  expiresAt: number;
  hitCount: number;
}

/**
 * Cache statistics
 */
export interface CacheStats {
  hits: number;
  misses: number;
  hitRatio: number;
  size: number;
  maxSize: number;
  evictions: number;
  expiredPurged: number;
  toolStats: Record<string, { hits: number; misses: number }>;
}

/**
 * Enhanced cache for data source tools
 */
class DataSourceCache {
  private cache: LRUCache<string, CacheEntry<any>>;
  private stats = {
    hits: 0,
    misses: 0,
    evictions: 0,
    expiredPurged: 0,
    toolStats: {} as Record<string, { hits: number; misses: number }>
  };
  
  constructor() {
    this.cache = new LRUCache({
      max: MAX_CACHE_ENTRIES,
      ttl: DEFAULT_TTL_MS,
      updateAgeOnGet: false,
      allowStale: false,
      dispose: () => {
        this.stats.evictions++;
      }
    });
  }
  
  /**
   * Generate cache key fingerprint from tool name and params
   */
  generateKey(tool: string, params: Record<string, any>): string {
    const sortedParams = Object.keys(params)
      .sort()
      .reduce((acc, key) => {
        if (params[key] !== undefined) {
          acc[key] = params[key];
        }
        return acc;
      }, {} as Record<string, any>);
    
    const paramStr = JSON.stringify(sortedParams);
    const hash = createHash('md5').update(paramStr).digest('hex').substring(0, 8);
    return `${tool}:${hash}`;
  }
  
  /**
   * Get cached data or fetch using provided function
   */
  async getOrFetch<T>(
    tool: string,
    params: Record<string, any>,
    fetchFn: () => Promise<T>,
    customTtl?: number
  ): Promise<{ data: T; cacheHit: boolean; cachedAt?: number }> {
    const ttl = customTtl ?? TOOL_TTL[tool] ?? DEFAULT_TTL_MS;
    
    // Skip cache for tools with TTL = 0
    if (ttl === 0) {
      const data = await fetchFn();
      return { data, cacheHit: false };
    }
    
    const key = this.generateKey(tool, params);
    
    // Initialize tool stats
    if (!this.stats.toolStats[tool]) {
      this.stats.toolStats[tool] = { hits: 0, misses: 0 };
    }
    
    // Try cache first
    const cached = this.cache.get(key);
    if (cached) {
      const now = Date.now();
      if (now < cached.expiresAt) {
        this.stats.hits++;
        this.stats.toolStats[tool].hits++;
        cached.hitCount++;
        log(LogLevel.DEBUG, `Cache hit for ${tool}: ${key}`);
        return { data: cached.data, cacheHit: true, cachedAt: cached.cachedAt };
      } else {
        // Expired, purge it
        this.cache.delete(key);
        this.stats.expiredPurged++;
      }
    }
    
    // Cache miss, fetch data
    this.stats.misses++;
    this.stats.toolStats[tool].misses++;
    log(LogLevel.DEBUG, `Cache miss for ${tool}: ${key}`);
    
    const data = await fetchFn();
    const now = Date.now();
    
    // Store in cache
    this.cache.set(key, {
      data,
      cachedAt: now,
      expiresAt: now + ttl,
      hitCount: 0
    }, { ttl });
    
    return { data, cacheHit: false };
  }
  
  /**
   * Manually set cache entry
   */
  set<T>(tool: string, params: Record<string, any>, data: T, ttl?: number): void {
    const actualTtl = ttl ?? TOOL_TTL[tool] ?? DEFAULT_TTL_MS;
    if (actualTtl === 0) return;
    
    const key = this.generateKey(tool, params);
    const now = Date.now();
    
    this.cache.set(key, {
      data,
      cachedAt: now,
      expiresAt: now + actualTtl,
      hitCount: 0
    }, { ttl: actualTtl });
  }
  
  /**
   * Check if entry exists and is not expired
   */
  has(tool: string, params: Record<string, any>): boolean {
    const key = this.generateKey(tool, params);
    const entry = this.cache.get(key);
    return entry !== undefined && Date.now() < entry.expiresAt;
  }
  
  /**
   * Delete specific cache entry
   */
  delete(tool: string, params: Record<string, any>): boolean {
    const key = this.generateKey(tool, params);
    return this.cache.delete(key);
  }
  
  /**
   * Clear all cache entries
   */
  clear(): void {
    this.cache.clear();
    this.stats.hits = 0;
    this.stats.misses = 0;
    this.stats.evictions = 0;
    this.stats.expiredPurged = 0;
    this.stats.toolStats = {};
    log(LogLevel.INFO, 'Data source cache cleared');
  }
  
  /**
   * Clear cache entries for a specific tool
   */
  clearTool(tool: string): number {
    const prefix = `${tool}:`;
    let cleared = 0;
    
    for (const key of this.cache.keys()) {
      if (key.startsWith(prefix)) {
        this.cache.delete(key);
        cleared++;
      }
    }
    
    log(LogLevel.INFO, `Cleared ${cleared} cache entries for tool ${tool}`);
    return cleared;
  }
  
  /**
   * Get cache statistics
   */
  getStats(): CacheStats {
    const total = this.stats.hits + this.stats.misses;
    return {
      hits: this.stats.hits,
      misses: this.stats.misses,
      hitRatio: total > 0 ? this.stats.hits / total : 0,
      size: this.cache.size,
      maxSize: MAX_CACHE_ENTRIES,
      evictions: this.stats.evictions,
      expiredPurged: this.stats.expiredPurged,
      toolStats: { ...this.stats.toolStats }
    };
  }
  
  /**
   * Get number of keys in cache
   */
  get size(): number {
    return this.cache.size;
  }
  
  /**
   * Purge expired entries
   */
  purgeExpired(): number {
    const now = Date.now();
    let purged = 0;
    
    for (const [key, entry] of this.cache.entries()) {
      if (now >= entry.expiresAt) {
        this.cache.delete(key);
        purged++;
      }
    }
    
    this.stats.expiredPurged += purged;
    return purged;
  }
}

// Singleton instance
export const dataSourceCache = new DataSourceCache();

/**
 * Helper function for simple caching
 */
export async function getCachedOrFetch<T>(
  tool: string,
  params: Record<string, any>,
  fetchFn: () => Promise<T>,
  customTtl?: number
): Promise<{ data: T; cacheHit: boolean; cachedAt?: number }> {
  return dataSourceCache.getOrFetch(tool, params, fetchFn, customTtl);
}

/**
 * Get cache statistics
 */
export function getDataSourceCacheStats(): CacheStats {
  return dataSourceCache.getStats();
}

/**
 * Clear all data source cache
 */
export function clearDataSourceCache(): void {
  dataSourceCache.clear();
}
