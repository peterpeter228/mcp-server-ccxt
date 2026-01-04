/**
 * Unit Tests for Data Source Tools
 * Tests for infrastructure modules and tool behaviors
 * 
 * 数据源工具单元测试
 * 基础设施模块和工具行为的测试
 */

import {
  normalizeSymbol,
  getBaseAsset,
  getVenueSymbol,
  getVenueQuoteCurrency,
  ALLOWED_SYMBOLS
} from '../src/lib/symbol.js';

import {
  QualityFlagBuilder,
  QUALITY_FLAGS,
  isStale,
  hasTimeRollback,
  calculateAge
} from '../src/lib/quality.js';

import {
  applySizeGuard,
  trimArray,
  createGuardedResponse,
  getJsonByteSize,
  isWithinSizeLimit,
  MAX_OUTPUT_SIZE,
  MAX_ARRAY_ITEMS
} from '../src/lib/size_guard.js';

import {
  dataSourceCache,
  getDataSourceCacheStats,
  clearDataSourceCache,
  TOOL_TTL
} from '../src/lib/cache.js';

// =============================================================================
// Symbol Module Tests
// =============================================================================
describe('Symbol Module', () => {
  describe('normalizeSymbol', () => {
    test('should accept BTCUSDT', () => {
      expect(normalizeSymbol('BTCUSDT')).toBe('BTCUSDT');
    });

    test('should accept ETHUSDT', () => {
      expect(normalizeSymbol('ETHUSDT')).toBe('ETHUSDT');
    });

    test('should normalize lowercase btcusdt', () => {
      expect(normalizeSymbol('btcusdt')).toBe('BTCUSDT');
    });

    test('should normalize BTC/USDT format', () => {
      expect(normalizeSymbol('BTC/USDT')).toBe('BTCUSDT');
    });

    test('should normalize BTC-USDT format', () => {
      expect(normalizeSymbol('BTC-USDT')).toBe('BTCUSDT');
    });

    test('should normalize BTC_USDT format', () => {
      expect(normalizeSymbol('BTC_USDT')).toBe('BTCUSDT');
    });

    test('should normalize ETH/USDT:USDT format', () => {
      expect(normalizeSymbol('ETH/USDT:USDT')).toBe('ETHUSDT');
    });

    test('should reject unsupported symbols', () => {
      expect(() => normalizeSymbol('SOLUSDT')).toThrow('not allowed');
      expect(() => normalizeSymbol('XRPUSDT')).toThrow('not allowed');
      expect(() => normalizeSymbol('random')).toThrow('not allowed');
    });
  });

  describe('getBaseAsset', () => {
    test('should return BTC for BTCUSDT', () => {
      expect(getBaseAsset('BTCUSDT')).toBe('BTC');
    });

    test('should return ETH for ETHUSDT', () => {
      expect(getBaseAsset('ETHUSDT')).toBe('ETH');
    });
  });

  describe('getVenueSymbol', () => {
    test('should return correct format for binance_futures', () => {
      expect(getVenueSymbol('BTCUSDT', 'binance_futures')).toBe('BTCUSDT');
    });

    test('should return correct format for coinbase_spot', () => {
      expect(getVenueSymbol('BTCUSDT', 'coinbase_spot')).toBe('BTC-USD');
    });

    test('should return correct format for kraken_spot', () => {
      expect(getVenueSymbol('BTCUSDT', 'kraken_spot')).toBe('XBTUSD');
      expect(getVenueSymbol('ETHUSDT', 'kraken_spot')).toBe('ETHUSD');
    });

    test('should throw for unknown venue', () => {
      expect(() => getVenueSymbol('BTCUSDT', 'unknown_venue')).toThrow('Unknown venue');
    });
  });

  describe('getVenueQuoteCurrency', () => {
    test('should return USDT for binance venues', () => {
      expect(getVenueQuoteCurrency('binance_futures')).toBe('USDT');
      expect(getVenueQuoteCurrency('binance_spot')).toBe('USDT');
    });

    test('should return USD for coinbase and kraken', () => {
      expect(getVenueQuoteCurrency('coinbase_spot')).toBe('USD');
      expect(getVenueQuoteCurrency('kraken_spot')).toBe('USD');
    });
  });
});

// =============================================================================
// Quality Flags Tests
// =============================================================================
describe('Quality Flags Module', () => {
  describe('QualityFlagBuilder', () => {
    test('should add flags up to max limit', () => {
      const builder = new QualityFlagBuilder(3);
      builder.add(QUALITY_FLAGS.STALE_SOURCE);
      builder.add(QUALITY_FLAGS.RATE_LIMITED);
      builder.add(QUALITY_FLAGS.SOURCE_PARTIAL);
      builder.add(QUALITY_FLAGS.DEV_HIGH); // Should be ignored
      
      const flags = builder.toArray();
      expect(flags).toHaveLength(3);
      expect(flags).toContain(QUALITY_FLAGS.STALE_SOURCE);
      expect(flags).toContain(QUALITY_FLAGS.RATE_LIMITED);
      expect(flags).toContain(QUALITY_FLAGS.SOURCE_PARTIAL);
      expect(flags).not.toContain(QUALITY_FLAGS.DEV_HIGH);
    });

    test('should add flag conditionally', () => {
      const builder = new QualityFlagBuilder();
      builder.addIf(true, QUALITY_FLAGS.STALE_SOURCE);
      builder.addIf(false, QUALITY_FLAGS.RATE_LIMITED);
      
      expect(builder.has(QUALITY_FLAGS.STALE_SOURCE)).toBe(true);
      expect(builder.has(QUALITY_FLAGS.RATE_LIMITED)).toBe(false);
    });

    test('should detect critical flags', () => {
      const builder = new QualityFlagBuilder();
      builder.add(QUALITY_FLAGS.STALE_SOURCE);
      expect(builder.hasCritical()).toBe(false);
      
      builder.add(QUALITY_FLAGS.CRITICAL_SOURCE_FAILED);
      expect(builder.hasCritical()).toBe(true);
    });

    test('should default to max 6 flags', () => {
      const builder = new QualityFlagBuilder();
      expect(builder.count).toBe(0);
      
      for (let i = 0; i < 10; i++) {
        builder.add(`flag_${i}` as any);
      }
      
      expect(builder.toArray()).toHaveLength(6);
    });
  });

  describe('isStale', () => {
    test('should detect stale timestamp', () => {
      const oldTs = Date.now() - 10000; // 10 seconds ago
      expect(isStale(oldTs, 5000)).toBe(true);
      expect(isStale(oldTs, 15000)).toBe(false);
    });

    test('should not detect fresh timestamp as stale', () => {
      const freshTs = Date.now() - 100; // 100ms ago
      expect(isStale(freshTs, 5000)).toBe(false);
    });
  });

  describe('hasTimeRollback', () => {
    test('should detect time rollback', () => {
      expect(hasTimeRollback(1000, 3000)).toBe(true);
    });

    test('should allow small variance', () => {
      expect(hasTimeRollback(1000, 1500)).toBe(false);
    });

    test('should not flag forward time', () => {
      expect(hasTimeRollback(3000, 1000)).toBe(false);
    });
  });

  describe('calculateAge', () => {
    test('should calculate positive age', () => {
      const ts = Date.now() - 5000;
      const age = calculateAge(ts);
      expect(age).toBeGreaterThanOrEqual(4900);
      expect(age).toBeLessThanOrEqual(5100);
    });

    test('should return 0 for future timestamp', () => {
      const futureTs = Date.now() + 10000;
      expect(calculateAge(futureTs)).toBe(0);
    });
  });
});

// =============================================================================
// Size Guard Tests
// =============================================================================
describe('Size Guard Module', () => {
  describe('trimArray', () => {
    test('should trim array to max items', () => {
      const arr = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
      expect(trimArray(arr, 5)).toHaveLength(5);
      expect(trimArray(arr, 5)).toEqual([1, 2, 3, 4, 5]);
    });

    test('should not modify array under limit', () => {
      const arr = [1, 2, 3];
      expect(trimArray(arr, 5)).toHaveLength(3);
    });

    test('should use default MAX_ARRAY_ITEMS', () => {
      const arr = Array.from({ length: 20 }, (_, i) => i);
      expect(trimArray(arr)).toHaveLength(MAX_ARRAY_ITEMS);
    });
  });

  describe('applySizeGuard', () => {
    test('should not modify small objects', () => {
      const obj = {
        success: true,
        ts_ms: Date.now(),
        data: 'small'
      };
      const { output, trimmed } = applySizeGuard(obj);
      expect(trimmed).toBe(false);
      expect(output).toEqual(obj);
    });

    test('should trim large arrays', () => {
      const obj = {
        success: true,
        ts_ms: Date.now(),
        items: Array.from({ length: 20 }, (_, i) => ({ id: i, data: 'test' }))
      };
      const { output, trimmed } = applySizeGuard(obj);
      expect(trimmed).toBe(true);
      expect(output.items).toHaveLength(MAX_ARRAY_ITEMS);
    });

    test('should trim nested arrays', () => {
      const obj = {
        success: true,
        nested: {
          items: Array.from({ length: 20 }, (_, i) => i)
        }
      };
      const { output, trimmed } = applySizeGuard(obj);
      expect(trimmed).toBe(true);
      expect(output.nested.items).toHaveLength(MAX_ARRAY_ITEMS);
    });
  });

  describe('createGuardedResponse', () => {
    test('should add trimmed_output flag when trimmed', () => {
      const data = {
        success: true,
        ts_ms: Date.now(),
        quality_flags: [] as string[],
        items: Array.from({ length: 20 }, (_, i) => i)
      };
      const result = createGuardedResponse(data);
      expect(result.quality_flags).toContain(QUALITY_FLAGS.TRIMMED_OUTPUT);
    });

    test('should not add flag when not trimmed', () => {
      const data = {
        success: true,
        ts_ms: Date.now(),
        quality_flags: [] as string[],
        items: [1, 2, 3]
      };
      const result = createGuardedResponse(data);
      expect(result.quality_flags).not.toContain(QUALITY_FLAGS.TRIMMED_OUTPUT);
    });
  });

  describe('getJsonByteSize', () => {
    test('should calculate correct byte size', () => {
      const obj = { a: 'test' };
      const size = getJsonByteSize(obj);
      expect(size).toBe(JSON.stringify(obj).length);
    });
  });

  describe('isWithinSizeLimit', () => {
    test('should return true for small objects', () => {
      expect(isWithinSizeLimit({ a: 'test' })).toBe(true);
    });

    test('should return false for objects over limit', () => {
      const largeObj = { data: 'x'.repeat(MAX_OUTPUT_SIZE + 100) };
      expect(isWithinSizeLimit(largeObj)).toBe(false);
    });
  });

  describe('output size validation', () => {
    test('typical tool output should be under 2KB', () => {
      // Simulate typical cross_exchange_anchor_consensus output
      const output = {
        success: true,
        ts_ms: Date.now(),
        schema_version: '1.0',
        source: 'mcp_ext',
        quality_flags: ['source_partial'],
        inputs: {
          symbol: 'BTCUSDT',
          venues_used: ['binance_futures', 'binance_spot', 'coinbase', 'kraken']
        },
        quotes: Array.from({ length: 8 }, (_, i) => ({
          venue: `venue_${i}`,
          quote_ccy: 'USDT',
          px: 100000 + i * 10,
          px_type: 'mid',
          age_ms: 100
        })),
        consensus: {
          median_px: 100035,
          min_px: 100000,
          max_px: 100070,
          max_dev_bps: 35,
          dev_bps_by_venue: Array.from({ length: 6 }, (_, i) => ({
            venue: `venue_${i}`,
            dev_bps: i * 5
          })),
          consensus_ok: true
        }
      };
      
      expect(isWithinSizeLimit(output, MAX_OUTPUT_SIZE)).toBe(true);
    });
  });
});

// =============================================================================
// Cache Module Tests
// =============================================================================
describe('Cache Module', () => {
  beforeEach(() => {
    clearDataSourceCache();
  });

  describe('dataSourceCache', () => {
    test('should cache and retrieve data', async () => {
      let fetchCount = 0;
      const fetchFn = async () => {
        fetchCount++;
        return { value: 'test' };
      };
      
      const result1 = await dataSourceCache.getOrFetch('test_tool', { key: 'value' }, fetchFn, 5000);
      expect(result1.cacheHit).toBe(false);
      expect(result1.data).toEqual({ value: 'test' });
      expect(fetchCount).toBe(1);
      
      const result2 = await dataSourceCache.getOrFetch('test_tool', { key: 'value' }, fetchFn, 5000);
      expect(result2.cacheHit).toBe(true);
      expect(result2.data).toEqual({ value: 'test' });
      expect(fetchCount).toBe(1); // Should not fetch again
    });

    test('should not cache when TTL is 0', async () => {
      let fetchCount = 0;
      const fetchFn = async () => {
        fetchCount++;
        return { value: 'test' };
      };
      
      await dataSourceCache.getOrFetch('test_tool', {}, fetchFn, 0);
      await dataSourceCache.getOrFetch('test_tool', {}, fetchFn, 0);
      
      expect(fetchCount).toBe(2);
    });

    test('should generate different keys for different params', () => {
      const key1 = dataSourceCache.generateKey('tool', { a: 1, b: 2 });
      const key2 = dataSourceCache.generateKey('tool', { a: 1, b: 3 });
      const key3 = dataSourceCache.generateKey('tool', { a: 1, b: 2 });
      
      expect(key1).not.toBe(key2);
      expect(key1).toBe(key3);
    });

    test('should handle param order consistently', () => {
      const key1 = dataSourceCache.generateKey('tool', { b: 2, a: 1 });
      const key2 = dataSourceCache.generateKey('tool', { a: 1, b: 2 });
      
      expect(key1).toBe(key2);
    });
  });

  describe('getDataSourceCacheStats', () => {
    test('should return stats object', async () => {
      const stats = getDataSourceCacheStats();
      
      expect(stats).toHaveProperty('hits');
      expect(stats).toHaveProperty('misses');
      expect(stats).toHaveProperty('hitRatio');
      expect(stats).toHaveProperty('size');
      expect(stats).toHaveProperty('maxSize');
    });

    test('should track hits and misses', async () => {
      const fetchFn = async () => ({ value: 'test' });
      
      await dataSourceCache.getOrFetch('test', {}, fetchFn, 5000);
      let stats = getDataSourceCacheStats();
      expect(stats.misses).toBe(1);
      
      await dataSourceCache.getOrFetch('test', {}, fetchFn, 5000);
      stats = getDataSourceCacheStats();
      expect(stats.hits).toBe(1);
    });
  });

  describe('clearDataSourceCache', () => {
    test('should clear all cache entries', async () => {
      const fetchFn = async () => ({ value: 'test' });
      
      await dataSourceCache.getOrFetch('tool1', {}, fetchFn, 5000);
      await dataSourceCache.getOrFetch('tool2', {}, fetchFn, 5000);
      
      expect(dataSourceCache.size).toBe(2);
      
      clearDataSourceCache();
      
      expect(dataSourceCache.size).toBe(0);
    });
  });

  describe('TOOL_TTL configuration', () => {
    test('should have TTL for all tools', () => {
      const expectedTools = [
        'cross_exchange_anchor_consensus',
        'spot_perp_basis_digest',
        'orderbook_ws_qos_diagnostics',
        'trade_activity_proxy_binance',
        'exchange_status_aggregator',
        'rate_limit_qos_state',
        'us_macro_event_window_fred',
        'onchain_fee_congestion',
        'stablecoin_depeg_monitor',
        'volatility_regime_fallback_binance',
        'data_conflict_digest',
        'cache_maintenance_digest'
      ];
      
      for (const tool of expectedTools) {
        expect(TOOL_TTL).toHaveProperty(tool);
        expect(typeof TOOL_TTL[tool]).toBe('number');
      }
    });

    test('should have short TTL for time-sensitive tools', () => {
      expect(TOOL_TTL['cross_exchange_anchor_consensus']).toBeLessThanOrEqual(5000);
      expect(TOOL_TTL['spot_perp_basis_digest']).toBeLessThanOrEqual(5000);
      expect(TOOL_TTL['orderbook_ws_qos_diagnostics']).toBeLessThanOrEqual(2000);
    });

    test('should have longer TTL for status tools', () => {
      expect(TOOL_TTL['exchange_status_aggregator']).toBeGreaterThanOrEqual(30000);
      expect(TOOL_TTL['us_macro_event_window_fred']).toBeGreaterThanOrEqual(3600000);
    });
  });
});

// =============================================================================
// Constants and Invariants
// =============================================================================
describe('Constants and Invariants', () => {
  test('ALLOWED_SYMBOLS should only contain BTCUSDT and ETHUSDT', () => {
    expect(ALLOWED_SYMBOLS).toContain('BTCUSDT');
    expect(ALLOWED_SYMBOLS).toContain('ETHUSDT');
    expect(ALLOWED_SYMBOLS).toHaveLength(2);
  });

  test('MAX_OUTPUT_SIZE should be 2048 bytes', () => {
    expect(MAX_OUTPUT_SIZE).toBe(2048);
  });

  test('MAX_ARRAY_ITEMS should be 8', () => {
    expect(MAX_ARRAY_ITEMS).toBe(8);
  });
});
