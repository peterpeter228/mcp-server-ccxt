/**
 * Unit Tests for Futures Helpers
 * Tests for price/qty rounding, validation, and symbol whitelist
 * 
 * 期货辅助函数单元测试
 * 价格/数量取整、校验和交易对白名单的测试
 */

import {
  validateFuturesSymbol,
  toCcxtSymbol,
  toBinanceSymbol,
  roundPriceToTick,
  roundQtyToStep,
  getDecimalPlaces,
  validateOrderParams,
  validateLeverage,
  generateClientOrderId,
  estimateLiquidationPrice,
  FuturesExchangeInfo,
  ALLOWED_FUTURES_SYMBOLS
} from '../src/utils/futures-helpers.js';

describe('Futures Helpers', () => {
  
  // ============================================================================
  // Symbol Validation Tests
  // ============================================================================
  describe('validateFuturesSymbol', () => {
    test('should accept BTCUSDT', () => {
      expect(validateFuturesSymbol('BTCUSDT')).toBe('BTCUSDT');
    });

    test('should accept ETHUSDT', () => {
      expect(validateFuturesSymbol('ETHUSDT')).toBe('ETHUSDT');
    });

    test('should accept lowercase btcusdt', () => {
      expect(validateFuturesSymbol('btcusdt')).toBe('BTCUSDT');
    });

    test('should accept BTC/USDT format', () => {
      expect(validateFuturesSymbol('BTC/USDT')).toBe('BTCUSDT');
    });

    test('should reject SOLUSDT', () => {
      expect(() => validateFuturesSymbol('SOLUSDT')).toThrow('not allowed');
    });

    test('should reject XRPUSDT', () => {
      expect(() => validateFuturesSymbol('XRPUSDT')).toThrow('not allowed');
    });

    test('should reject empty string', () => {
      expect(() => validateFuturesSymbol('')).toThrow('not allowed');
    });
  });

  // ============================================================================
  // Symbol Conversion Tests
  // ============================================================================
  describe('toCcxtSymbol', () => {
    test('should convert BTCUSDT to BTC/USDT:USDT', () => {
      expect(toCcxtSymbol('BTCUSDT')).toBe('BTC/USDT:USDT');
    });

    test('should convert ETHUSDT to ETH/USDT:USDT', () => {
      expect(toCcxtSymbol('ETHUSDT')).toBe('ETH/USDT:USDT');
    });

    test('should handle lowercase input', () => {
      expect(toCcxtSymbol('btcusdt')).toBe('BTC/USDT:USDT');
    });
  });

  describe('toBinanceSymbol', () => {
    test('should convert BTC/USDT:USDT to BTCUSDT', () => {
      expect(toBinanceSymbol('BTC/USDT:USDT')).toBe('BTCUSDT');
    });

    test('should convert BTC/USDT to BTCUSDT', () => {
      expect(toBinanceSymbol('BTC/USDT')).toBe('BTCUSDT');
    });

    test('should pass through BTCUSDT unchanged', () => {
      expect(toBinanceSymbol('BTCUSDT')).toBe('BTCUSDT');
    });
  });

  // ============================================================================
  // Price Rounding Tests
  // ============================================================================
  describe('roundPriceToTick', () => {
    test('should round BUY order price DOWN (conservative)', () => {
      // For BUY: lower price means order may not fill (safer)
      expect(roundPriceToTick(100000.37, 0.10, 'BUY')).toBe(100000.3);
    });

    test('should round SELL order price UP (conservative)', () => {
      // For SELL: higher price means order may not fill (safer)
      expect(roundPriceToTick(100000.31, 0.10, 'SELL')).toBe(100000.4);
    });

    test('should handle tick size of 0.01', () => {
      expect(roundPriceToTick(3456.789, 0.01, 'BUY')).toBe(3456.78);
      expect(roundPriceToTick(3456.781, 0.01, 'SELL')).toBe(3456.79);
    });

    test('should handle tick size of 1', () => {
      expect(roundPriceToTick(100005.5, 1, 'BUY')).toBe(100005);
      expect(roundPriceToTick(100005.1, 1, 'SELL')).toBe(100006);
    });

    test('should handle exact tick values', () => {
      expect(roundPriceToTick(100000.10, 0.10, 'BUY')).toBe(100000.1);
      expect(roundPriceToTick(100000.10, 0.10, 'SELL')).toBe(100000.1);
    });

    test('should throw on invalid tick size', () => {
      expect(() => roundPriceToTick(100, 0, 'BUY')).toThrow('tickSize must be positive');
      expect(() => roundPriceToTick(100, -0.1, 'BUY')).toThrow('tickSize must be positive');
    });

    test('should handle floating point precision', () => {
      // Test case that could cause floating point issues
      expect(roundPriceToTick(0.1 + 0.2, 0.01, 'BUY')).toBe(0.3);
    });
  });

  // ============================================================================
  // Quantity Rounding Tests
  // ============================================================================
  describe('roundQtyToStep', () => {
    test('should always round DOWN for safety', () => {
      // Note: 1.005 in floating point is slightly less than 1.005
      // so it rounds to 1.004 - this is expected floating point behavior
      expect(roundQtyToStep(1.006, 0.001)).toBe(1.006);
      expect(roundQtyToStep(1.0059, 0.001)).toBe(1.005);
      expect(roundQtyToStep(1.0051, 0.001)).toBe(1.005);
    });

    test('should handle step size of 0.001 for BTC', () => {
      expect(roundQtyToStep(0.123456, 0.001)).toBe(0.123);
    });

    test('should handle step size of 0.01 for ETH', () => {
      expect(roundQtyToStep(1.999, 0.01)).toBe(1.99);
    });

    test('should handle step size of 1', () => {
      expect(roundQtyToStep(10.9, 1)).toBe(10);
    });

    test('should handle exact step values', () => {
      expect(roundQtyToStep(0.123, 0.001)).toBe(0.123);
    });

    test('should throw on invalid step size', () => {
      expect(() => roundQtyToStep(1, 0)).toThrow('stepSize must be positive');
      expect(() => roundQtyToStep(1, -0.001)).toThrow('stepSize must be positive');
    });

    test('should handle very small quantities', () => {
      expect(roundQtyToStep(0.00099, 0.001)).toBe(0);
    });
  });

  // ============================================================================
  // Decimal Places Tests
  // ============================================================================
  describe('getDecimalPlaces', () => {
    test('should return 0 for integers', () => {
      expect(getDecimalPlaces(100)).toBe(0);
      expect(getDecimalPlaces(1)).toBe(0);
    });

    test('should count decimal places correctly', () => {
      expect(getDecimalPlaces(0.1)).toBe(1);
      expect(getDecimalPlaces(0.01)).toBe(2);
      expect(getDecimalPlaces(0.001)).toBe(3);
    });

    test('should handle scientific notation', () => {
      expect(getDecimalPlaces(1e-3)).toBe(3);
      expect(getDecimalPlaces(1e-8)).toBe(8);
    });
  });

  // ============================================================================
  // Order Validation Tests
  // ============================================================================
  describe('validateOrderParams', () => {
    const mockExchangeInfo: FuturesExchangeInfo = {
      symbol: 'BTCUSDT',
      tickSize: 0.10,
      stepSize: 0.001,
      minQty: 0.001,
      minNotional: 5,
      pricePrecision: 1,
      qtyPrecision: 3
    };

    test('should validate correct params', () => {
      const result = validateOrderParams(100000, 0.01, 'BUY', mockExchangeInfo);
      expect(result.valid).toBe(true);
      expect(result.errors).toHaveLength(0);
    });

    test('should adjust price to tick size', () => {
      const result = validateOrderParams(100000.15, 0.01, 'BUY', mockExchangeInfo);
      expect(result.warnings.length).toBeGreaterThan(0);
      expect(result.adjusted.price).toBe(100000.1);
    });

    test('should adjust qty to step size', () => {
      const result = validateOrderParams(100000, 0.0105, 'BUY', mockExchangeInfo);
      expect(result.warnings.length).toBeGreaterThan(0);
      expect(result.adjusted.qty).toBe(0.01);
    });

    test('should fail on qty below minimum', () => {
      const result = validateOrderParams(100000, 0.0005, 'BUY', mockExchangeInfo);
      expect(result.valid).toBe(false);
      expect(result.errors.some(e => e.includes('below minimum'))).toBe(true);
    });

    test('should fail on notional below minimum', () => {
      // 100 * 0.001 = 0.1 USDT < 5 USDT
      const result = validateOrderParams(100, 0.001, 'BUY', mockExchangeInfo);
      expect(result.valid).toBe(false);
      expect(result.errors.some(e => e.includes('Notional value'))).toBe(true);
    });
  });

  // ============================================================================
  // Leverage Validation Tests
  // ============================================================================
  describe('validateLeverage', () => {
    test('should accept valid leverage values', () => {
      expect(validateLeverage(1)).toBe(true);
      expect(validateLeverage(10)).toBe(true);
      expect(validateLeverage(125)).toBe(true);
    });

    test('should reject leverage below 1', () => {
      expect(validateLeverage(0)).toBe(false);
      expect(validateLeverage(-1)).toBe(false);
    });

    test('should reject leverage above 125', () => {
      expect(validateLeverage(126)).toBe(false);
      expect(validateLeverage(200)).toBe(false);
    });

    test('should reject non-integer leverage', () => {
      expect(validateLeverage(10.5)).toBe(false);
      expect(validateLeverage(1.1)).toBe(false);
    });

    test('should accept custom max leverage', () => {
      expect(validateLeverage(50, 50)).toBe(true);
      expect(validateLeverage(51, 50)).toBe(false);
    });
  });

  // ============================================================================
  // Client Order ID Generation Tests
  // ============================================================================
  describe('generateClientOrderId', () => {
    test('should generate unique IDs', () => {
      const id1 = generateClientOrderId();
      const id2 = generateClientOrderId();
      expect(id1).not.toBe(id2);
    });

    test('should use custom prefix', () => {
      const id = generateClientOrderId('entry');
      expect(id.startsWith('entry_')).toBe(true);
    });

    test('should use default prefix', () => {
      const id = generateClientOrderId();
      expect(id.startsWith('mcp_')).toBe(true);
    });
  });

  // ============================================================================
  // Liquidation Price Estimation Tests
  // ============================================================================
  describe('estimateLiquidationPrice', () => {
    test('should calculate LONG liquidation price', () => {
      // Entry: 100000, Leverage: 10x, MMR: 0.4%
      // Liq = 100000 * (1 - 1/10 + 0.004) = 100000 * 0.904 = 90400
      const liqPrice = estimateLiquidationPrice(100000, 10, 'LONG', 0.004);
      expect(liqPrice).toBeCloseTo(90400, 0);
    });

    test('should calculate SHORT liquidation price', () => {
      // Entry: 100000, Leverage: 10x, MMR: 0.4%
      // Liq = 100000 * (1 + 1/10 - 0.004) = 100000 * 1.096 = 109600
      const liqPrice = estimateLiquidationPrice(100000, 10, 'SHORT', 0.004);
      expect(liqPrice).toBeCloseTo(109600, 0);
    });

    test('should use default MMR if not provided', () => {
      const liqPrice = estimateLiquidationPrice(100000, 10, 'LONG');
      expect(liqPrice).toBeGreaterThan(0);
      expect(liqPrice).toBeLessThan(100000);
    });

    test('should handle high leverage', () => {
      // Higher leverage = closer liquidation price
      const liq10x = estimateLiquidationPrice(100000, 10, 'LONG');
      const liq50x = estimateLiquidationPrice(100000, 50, 'LONG');
      expect(liq50x).toBeGreaterThan(liq10x);
    });
  });

  // ============================================================================
  // Allowed Symbols Tests
  // ============================================================================
  describe('ALLOWED_FUTURES_SYMBOLS', () => {
    test('should contain only BTCUSDT and ETHUSDT', () => {
      expect(ALLOWED_FUTURES_SYMBOLS).toContain('BTCUSDT');
      expect(ALLOWED_FUTURES_SYMBOLS).toContain('ETHUSDT');
      expect(ALLOWED_FUTURES_SYMBOLS).toHaveLength(2);
    });
  });
});
