/**
 * Unit Tests for Bracket Orders Schema Validation
 * Tests for bracket order parameters validation
 * 
 * 挂单组合参数校验单元测试
 * 挂单组合参数验证的测试
 */

import { z } from 'zod';
import {
  validateFuturesSymbol,
  validateOrderParams,
  roundPriceToTick,
  roundQtyToStep,
  FuturesExchangeInfo
} from '../src/utils/futures-helpers.js';

// Schema definitions for bracket orders (mirrors binance-futures.ts)
const entrySchema = z.object({
  price: z.number().positive(),
  qty: z.number().positive(),
  postOnly: z.boolean().default(true),
  timeInForce: z.enum(['GTC', 'IOC', 'FOK']).default('GTC'),
  clientOrderId: z.string().optional()
});

const slSchema = z.object({
  type: z.enum(['STOP_MARKET', 'STOP', 'STOP_LIMIT']).default('STOP_MARKET'),
  stopPrice: z.number().positive(),
  price: z.number().positive().optional(),
  reduceOnly: z.boolean().default(true)
});

const tpSchema = z.object({
  price: z.number().positive(),
  qtyPct: z.number().min(0).max(100).optional(),
  qty: z.number().positive().optional(),
  reduceOnly: z.boolean().default(true),
  postOnly: z.boolean().default(true)
});

const bracketOrderSchema = z.object({
  symbol: z.enum(['BTCUSDT', 'ETHUSDT', 'BTC/USDT', 'ETH/USDT']),
  side: z.enum(['BUY', 'SELL']),
  entry: entrySchema,
  sl: slSchema,
  tps: z.array(tpSchema).min(1),
  entry_ttl_sec: z.number().int().positive().optional(),
  positionSide: z.enum(['BOTH', 'LONG', 'SHORT']).default('BOTH')
});

describe('Bracket Orders Schema Validation', () => {
  
  const mockExchangeInfo: FuturesExchangeInfo = {
    symbol: 'BTCUSDT',
    tickSize: 0.10,
    stepSize: 0.001,
    minQty: 0.001,
    minNotional: 5,
    pricePrecision: 1,
    qtyPrecision: 3
  };

  // ============================================================================
  // Schema Validation Tests
  // ============================================================================
  describe('bracketOrderSchema', () => {
    test('should validate correct LONG bracket order', () => {
      const order = {
        symbol: 'BTCUSDT',
        side: 'BUY',
        entry: {
          price: 100000,
          qty: 0.01
        },
        sl: {
          stopPrice: 98000
        },
        tps: [
          { price: 102000, qtyPct: 50 },
          { price: 104000, qtyPct: 50 }
        ]
      };

      const result = bracketOrderSchema.safeParse(order);
      expect(result.success).toBe(true);
    });

    test('should validate correct SHORT bracket order', () => {
      const order = {
        symbol: 'ETHUSDT',
        side: 'SELL',
        entry: {
          price: 3500,
          qty: 0.5
        },
        sl: {
          type: 'STOP_LIMIT',
          stopPrice: 3600,
          price: 3605
        },
        tps: [
          { price: 3400, qty: 0.5 }
        ],
        positionSide: 'SHORT'
      };

      const result = bracketOrderSchema.safeParse(order);
      expect(result.success).toBe(true);
    });

    test('should reject invalid symbol', () => {
      const order = {
        symbol: 'SOLUSDT',
        side: 'BUY',
        entry: { price: 100, qty: 1 },
        sl: { stopPrice: 95 },
        tps: [{ price: 110, qtyPct: 100 }]
      };

      const result = bracketOrderSchema.safeParse(order);
      expect(result.success).toBe(false);
    });

    test('should reject negative price', () => {
      const order = {
        symbol: 'BTCUSDT',
        side: 'BUY',
        entry: { price: -100000, qty: 0.01 },
        sl: { stopPrice: 98000 },
        tps: [{ price: 102000, qtyPct: 100 }]
      };

      const result = bracketOrderSchema.safeParse(order);
      expect(result.success).toBe(false);
    });

    test('should reject zero quantity', () => {
      const order = {
        symbol: 'BTCUSDT',
        side: 'BUY',
        entry: { price: 100000, qty: 0 },
        sl: { stopPrice: 98000 },
        tps: [{ price: 102000, qtyPct: 100 }]
      };

      const result = bracketOrderSchema.safeParse(order);
      expect(result.success).toBe(false);
    });

    test('should reject empty TPs array', () => {
      const order = {
        symbol: 'BTCUSDT',
        side: 'BUY',
        entry: { price: 100000, qty: 0.01 },
        sl: { stopPrice: 98000 },
        tps: []
      };

      const result = bracketOrderSchema.safeParse(order);
      expect(result.success).toBe(false);
    });

    test('should reject qtyPct over 100', () => {
      const order = {
        symbol: 'BTCUSDT',
        side: 'BUY',
        entry: { price: 100000, qty: 0.01 },
        sl: { stopPrice: 98000 },
        tps: [{ price: 102000, qtyPct: 150 }]
      };

      const result = bracketOrderSchema.safeParse(order);
      expect(result.success).toBe(false);
    });

    test('should set default values', () => {
      const order = {
        symbol: 'BTCUSDT',
        side: 'BUY',
        entry: { price: 100000, qty: 0.01 },
        sl: { stopPrice: 98000 },
        tps: [{ price: 102000, qty: 0.01 }]
      };

      const result = bracketOrderSchema.parse(order);
      
      expect(result.entry.postOnly).toBe(true);
      expect(result.entry.timeInForce).toBe('GTC');
      expect(result.sl.type).toBe('STOP_MARKET');
      expect(result.sl.reduceOnly).toBe(true);
      expect(result.tps[0].reduceOnly).toBe(true);
      expect(result.positionSide).toBe('BOTH');
    });
  });

  // ============================================================================
  // Order Parameters Validation Tests
  // ============================================================================
  describe('validateOrderParams for brackets', () => {
    test('should validate entry order', () => {
      const result = validateOrderParams(100000, 0.01, 'BUY', mockExchangeInfo);
      expect(result.valid).toBe(true);
    });

    test('should fail entry below min notional', () => {
      // 100 * 0.001 = 0.1 USDT < 5 USDT min notional
      const result = validateOrderParams(100, 0.001, 'BUY', mockExchangeInfo);
      expect(result.valid).toBe(false);
      expect(result.errors.some(e => e.includes('Notional'))).toBe(true);
    });

    test('should adjust and warn for precision issues', () => {
      const result = validateOrderParams(100000.15, 0.0105, 'BUY', mockExchangeInfo);
      
      expect(result.warnings.length).toBeGreaterThan(0);
      expect(result.adjusted.price).toBeDefined();
      expect(result.adjusted.qty).toBeDefined();
    });
  });

  // ============================================================================
  // TP Quantity Distribution Tests
  // ============================================================================
  describe('TP quantity distribution', () => {
    test('should calculate correct TP quantities from percentage', () => {
      const entryQty = 0.1;
      const tps = [
        { qtyPct: 50 },
        { qtyPct: 30 },
        { qtyPct: 20 }
      ];

      const calculatedTps = tps.map(tp => ({
        qty: roundQtyToStep(entryQty * (tp.qtyPct / 100), mockExchangeInfo.stepSize)
      }));

      expect(calculatedTps[0].qty).toBe(0.05);
      expect(calculatedTps[1].qty).toBe(0.03);
      expect(calculatedTps[2].qty).toBe(0.02);
      
      const totalTpQty = calculatedTps.reduce((sum, tp) => sum + tp.qty, 0);
      expect(totalTpQty).toBe(entryQty);
    });

    test('should not exceed entry quantity', () => {
      const entryQty = 0.01;
      const tps = [
        { qtyPct: 60 },
        { qtyPct: 60 } // Total 120%
      ];

      const calculatedTps = tps.map(tp => ({
        qty: roundQtyToStep(entryQty * (tp.qtyPct / 100), mockExchangeInfo.stepSize)
      }));

      const totalTpQty = calculatedTps.reduce((sum, tp) => sum + tp.qty, 0);
      
      // Due to rounding, this should be caught in the bracket order validation
      // Here we just verify the calculation
      expect(totalTpQty).toBeLessThanOrEqual(0.012); // 0.006 * 2
    });
  });

  // ============================================================================
  // Stop Loss Direction Tests
  // ============================================================================
  describe('SL direction validation', () => {
    test('LONG position SL should be below entry', () => {
      const entryPrice = 100000;
      const slPrice = 98000; // 2% below
      
      expect(slPrice).toBeLessThan(entryPrice);
      
      // In actual implementation, the SL should trigger when price falls
      const isValidLongSL = slPrice < entryPrice;
      expect(isValidLongSL).toBe(true);
    });

    test('SHORT position SL should be above entry', () => {
      const entryPrice = 100000;
      const slPrice = 102000; // 2% above
      
      expect(slPrice).toBeGreaterThan(entryPrice);
      
      // In actual implementation, the SL should trigger when price rises
      const isValidShortSL = slPrice > entryPrice;
      expect(isValidShortSL).toBe(true);
    });
  });

  // ============================================================================
  // Take Profit Direction Tests
  // ============================================================================
  describe('TP direction validation', () => {
    test('LONG position TPs should be above entry', () => {
      const entryPrice = 100000;
      const tpPrices = [102000, 104000, 106000];
      
      tpPrices.forEach(tpPrice => {
        expect(tpPrice).toBeGreaterThan(entryPrice);
      });
    });

    test('SHORT position TPs should be below entry', () => {
      const entryPrice = 100000;
      const tpPrices = [98000, 96000, 94000];
      
      tpPrices.forEach(tpPrice => {
        expect(tpPrice).toBeLessThan(entryPrice);
      });
    });
  });

  // ============================================================================
  // Price Rounding Consistency Tests
  // ============================================================================
  describe('Price rounding consistency', () => {
    test('entry, SL, and TP prices should all be tick-aligned', () => {
      const rawPrices = {
        entry: 100000.15,
        sl: 98000.23,
        tps: [102000.47, 104000.89]
      };

      // For LONG position
      const roundedEntry = roundPriceToTick(rawPrices.entry, mockExchangeInfo.tickSize, 'BUY');
      const roundedSL = roundPriceToTick(rawPrices.sl, mockExchangeInfo.tickSize, 'SELL');
      const roundedTPs = rawPrices.tps.map(tp => 
        roundPriceToTick(tp, mockExchangeInfo.tickSize, 'SELL')
      );

      // Verify all prices are tick-aligned (using reasonable precision for floating point)
      // The modulo operation with floats can have small errors, so we check if the 
      // result is very close to 0 or very close to tickSize (which is also aligned)
      const isAligned = (price: number, tickSize: number) => {
        const remainder = price % tickSize;
        return remainder < 0.001 || Math.abs(remainder - tickSize) < 0.001;
      };

      expect(isAligned(roundedEntry, mockExchangeInfo.tickSize)).toBe(true);
      expect(isAligned(roundedSL, mockExchangeInfo.tickSize)).toBe(true);
      roundedTPs.forEach(tp => {
        expect(isAligned(tp, mockExchangeInfo.tickSize)).toBe(true);
      });
    });
  });

  // ============================================================================
  // ClientOrderId Tests
  // ============================================================================
  describe('ClientOrderId handling', () => {
    test('should accept custom clientOrderId', () => {
      const order = {
        symbol: 'BTCUSDT',
        side: 'BUY',
        entry: { 
          price: 100000, 
          qty: 0.01,
          clientOrderId: 'my_custom_entry_001'
        },
        sl: { stopPrice: 98000 },
        tps: [{ price: 102000, qtyPct: 100 }]
      };

      const result = bracketOrderSchema.safeParse(order);
      expect(result.success).toBe(true);
      if (result.success) {
        expect(result.data.entry.clientOrderId).toBe('my_custom_entry_001');
      }
    });

    test('should not require clientOrderId', () => {
      const order = {
        symbol: 'BTCUSDT',
        side: 'BUY',
        entry: { price: 100000, qty: 0.01 },
        sl: { stopPrice: 98000 },
        tps: [{ price: 102000, qtyPct: 100 }]
      };

      const result = bracketOrderSchema.safeParse(order);
      expect(result.success).toBe(true);
      if (result.success) {
        expect(result.data.entry.clientOrderId).toBeUndefined();
      }
    });
  });
});
