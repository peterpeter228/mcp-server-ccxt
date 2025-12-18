/**
 * Unit Tests for Trade Statistics
 * Tests for trade plan logging and template statistics
 * 
 * 交易统计单元测试
 * 交易计划日志记录和模板统计的测试
 */

import * as fs from 'fs';
import * as path from 'path';
import {
  logTradePlanSnapshot,
  getTemplateStats,
  getTradePlans,
  getTradePlan,
  updateTradePlanOutcome,
  clearTradeStatsCache,
  getStorageInfo,
  TradePlanSnapshot,
  OrderSubmitted,
  OrderFill,
  TradeOutcome,
  TemplateStats
} from '../src/utils/trade-stats.js';

// Test data directory
const TEST_DATA_DIR = path.join(process.cwd(), 'data');

describe('Trade Statistics', () => {
  
  // Clean up before and after tests
  beforeEach(() => {
    clearTradeStatsCache();
    // Clean up test data files
    const plansFile = path.join(TEST_DATA_DIR, 'trade_plans.jsonl');
    const statsFile = path.join(TEST_DATA_DIR, 'template_stats_cache.json');
    if (fs.existsSync(plansFile)) {
      fs.unlinkSync(plansFile);
    }
    if (fs.existsSync(statsFile)) {
      fs.unlinkSync(statsFile);
    }
  });

  afterAll(() => {
    clearTradeStatsCache();
    // Clean up test data files
    const plansFile = path.join(TEST_DATA_DIR, 'trade_plans.jsonl');
    const statsFile = path.join(TEST_DATA_DIR, 'template_stats_cache.json');
    if (fs.existsSync(plansFile)) {
      fs.unlinkSync(plansFile);
    }
    if (fs.existsSync(statsFile)) {
      fs.unlinkSync(statsFile);
    }
  });

  // ============================================================================
  // Trade Plan Logging Tests
  // ============================================================================
  describe('logTradePlanSnapshot', () => {
    test('should log a new trade plan', () => {
      const mockInputs = {
        entry_price: 100000,
        sl_price: 98000,
        tp_prices: [102000, 104000],
        qty: 0.01,
        leverage: 10,
        risk_amount: 20
      };

      const mockOrders: OrderSubmitted[] = [{
        order_id: '123456',
        client_order_id: 'entry_001',
        type: 'ENTRY',
        order_type: 'LIMIT',
        price: 100000,
        qty: 0.01,
        status: 'NEW',
        submitted_at: new Date().toISOString()
      }];

      const mockFills: OrderFill[] = [];
      const mockOutcome: TradeOutcome = { status: 'PENDING' };

      const snapshot = logTradePlanSnapshot(
        'plan_001',
        'template_breakout_v1',
        'ASIA',
        'MEDIUM',
        'BTCUSDT',
        'LONG',
        mockInputs,
        mockOrders,
        mockFills,
        mockOutcome
      );

      expect(snapshot.plan_id).toBe('plan_001');
      expect(snapshot.template_id).toBe('template_breakout_v1');
      expect(snapshot.session).toBe('ASIA');
      expect(snapshot.v_regime).toBe('MEDIUM');
      expect(snapshot.symbol).toBe('BTCUSDT');
      expect(snapshot.side).toBe('LONG');
      expect(snapshot.inputs_summary.entry_price).toBe(100000);
      expect(snapshot.orders_submitted).toHaveLength(1);
      expect(snapshot.outcome.status).toBe('PENDING');
    });

    test('should update existing trade plan', () => {
      const mockInputs = {
        entry_price: 100000,
        sl_price: 98000,
        tp_prices: [102000],
        qty: 0.01,
        leverage: 10
      };

      // First log
      logTradePlanSnapshot(
        'plan_002',
        'template_v1',
        'NY',
        'HIGH',
        'ETHUSDT',
        'SHORT',
        mockInputs,
        [],
        [],
        { status: 'PENDING' }
      );

      // Update with outcome
      const updatedSnapshot = logTradePlanSnapshot(
        'plan_002',
        'template_v1',
        'NY',
        'HIGH',
        'ETHUSDT',
        'SHORT',
        mockInputs,
        [],
        [{
          order_id: '789',
          type: 'SL',
          filled_price: 102000,
          filled_qty: 0.01,
          commission: 0.01,
          commission_asset: 'USDT',
          filled_at: new Date().toISOString()
        }],
        { 
          status: 'STOPPED_OUT',
          pnl: -20,
          pnl_percent: -2,
          rr_realized: -1
        }
      );

      expect(updatedSnapshot.outcome.status).toBe('STOPPED_OUT');
      expect(updatedSnapshot.fills).toHaveLength(1);
    });
  });

  // ============================================================================
  // Get Trade Plans Tests
  // ============================================================================
  describe('getTradePlans', () => {
    test('should return empty array when no plans', () => {
      const plans = getTradePlans();
      expect(plans).toEqual([]);
    });

    test('should return logged plans', () => {
      const mockInputs = {
        entry_price: 100000,
        sl_price: 98000,
        tp_prices: [102000],
        qty: 0.01,
        leverage: 10
      };

      logTradePlanSnapshot(
        'plan_list_001',
        'template_v1',
        'ASIA',
        'LOW',
        'BTCUSDT',
        'LONG',
        mockInputs,
        [],
        [],
        { status: 'PENDING' }
      );

      const plans = getTradePlans();
      expect(plans).toHaveLength(1);
      expect(plans[0].plan_id).toBe('plan_list_001');
    });

    test('should filter by symbol', () => {
      const mockInputs = {
        entry_price: 100000,
        sl_price: 98000,
        tp_prices: [102000],
        qty: 0.01,
        leverage: 10
      };

      logTradePlanSnapshot('plan_btc', 'template_v1', 'ASIA', 'LOW', 'BTCUSDT', 'LONG', mockInputs, [], [], { status: 'PENDING' });
      logTradePlanSnapshot('plan_eth', 'template_v1', 'ASIA', 'LOW', 'ETHUSDT', 'LONG', mockInputs, [], [], { status: 'PENDING' });

      const btcPlans = getTradePlans('BTCUSDT');
      expect(btcPlans).toHaveLength(1);
      expect(btcPlans[0].plan_id).toBe('plan_btc');

      const ethPlans = getTradePlans('ETHUSDT');
      expect(ethPlans).toHaveLength(1);
      expect(ethPlans[0].plan_id).toBe('plan_eth');
    });
  });

  // ============================================================================
  // Get Single Trade Plan Tests
  // ============================================================================
  describe('getTradePlan', () => {
    test('should return null for non-existent plan', () => {
      const plan = getTradePlan('non_existent');
      expect(plan).toBeNull();
    });

    test('should return specific plan by ID', () => {
      const mockInputs = {
        entry_price: 100000,
        sl_price: 98000,
        tp_prices: [102000],
        qty: 0.01,
        leverage: 10
      };

      logTradePlanSnapshot('plan_specific', 'template_v1', 'NY', 'HIGH', 'BTCUSDT', 'SHORT', mockInputs, [], [], { status: 'PENDING' });

      const plan = getTradePlan('plan_specific');
      expect(plan).not.toBeNull();
      expect(plan?.plan_id).toBe('plan_specific');
    });
  });

  // ============================================================================
  // Update Outcome Tests
  // ============================================================================
  describe('updateTradePlanOutcome', () => {
    test('should return null for non-existent plan', () => {
      const result = updateTradePlanOutcome('non_existent', { status: 'TP_HIT' });
      expect(result).toBeNull();
    });

    test('should update plan outcome', () => {
      const mockInputs = {
        entry_price: 100000,
        sl_price: 98000,
        tp_prices: [102000],
        qty: 0.01,
        leverage: 10
      };

      logTradePlanSnapshot('plan_update', 'template_v1', 'LONDON', 'MEDIUM', 'BTCUSDT', 'LONG', mockInputs, [], [], { status: 'PENDING' });

      const updated = updateTradePlanOutcome('plan_update', {
        status: 'TP_HIT',
        pnl: 40,
        pnl_percent: 4,
        rr_realized: 2
      });

      expect(updated).not.toBeNull();
      expect(updated?.outcome.status).toBe('TP_HIT');
      expect(updated?.outcome.pnl).toBe(40);
      expect(updated?.outcome.rr_realized).toBe(2);
    });
  });

  // ============================================================================
  // Template Statistics Tests
  // ============================================================================
  describe('getTemplateStats', () => {
    test('should return empty stats for new template', () => {
      const stats = getTemplateStats('new_template');
      
      expect(stats.template_id).toBe('new_template');
      expect(stats.total_trades).toBe(0);
      expect(stats.winrate).toBe(0);
      expect(stats.sample_size).toBe(0);
    });

    test('should calculate correct stats for completed trades', () => {
      const mockInputs = {
        entry_price: 100000,
        sl_price: 98000,
        tp_prices: [102000],
        qty: 0.01,
        leverage: 10
      };

      // Win trade
      logTradePlanSnapshot('stats_win_1', 'stats_template', 'ASIA', 'MEDIUM', 'BTCUSDT', 'LONG', mockInputs, [], [{
        order_id: '1',
        type: 'TP',
        filled_price: 102000,
        filled_qty: 0.01,
        commission: 0.01,
        commission_asset: 'USDT',
        filled_at: new Date().toISOString()
      }], { 
        status: 'TP_HIT',
        pnl: 20,
        pnl_percent: 2,
        rr_realized: 1
      });

      // Loss trade
      logTradePlanSnapshot('stats_loss_1', 'stats_template', 'ASIA', 'MEDIUM', 'BTCUSDT', 'LONG', mockInputs, [], [{
        order_id: '2',
        type: 'SL',
        filled_price: 98000,
        filled_qty: 0.01,
        commission: 0.01,
        commission_asset: 'USDT',
        filled_at: new Date().toISOString()
      }], { 
        status: 'STOPPED_OUT',
        pnl: -20,
        pnl_percent: -2,
        rr_realized: -1
      });

      const stats = getTemplateStats('stats_template');
      
      expect(stats.total_trades).toBe(2);
      expect(stats.wins).toBe(1);
      expect(stats.losses).toBe(1);
      expect(stats.winrate).toBe(0.5);
      expect(stats.sample_size).toBe(2);
    });

    test('should filter by session', () => {
      const mockInputs = {
        entry_price: 100000,
        sl_price: 98000,
        tp_prices: [102000],
        qty: 0.01,
        leverage: 10
      };

      logTradePlanSnapshot('session_asia', 'session_template', 'ASIA', 'LOW', 'BTCUSDT', 'LONG', mockInputs, [], [], { status: 'PENDING' });
      logTradePlanSnapshot('session_ny', 'session_template', 'NY', 'LOW', 'BTCUSDT', 'LONG', mockInputs, [], [], { status: 'PENDING' });

      const asiaStats = getTemplateStats('session_template', 'ASIA');
      expect(asiaStats.total_trades).toBe(1);

      const nyStats = getTemplateStats('session_template', 'NY');
      expect(nyStats.total_trades).toBe(1);
    });

    test('should provide suggested P_base range', () => {
      const stats = getTemplateStats('suggested_template');
      
      expect(stats.suggested_p_base_range).toBeDefined();
      expect(stats.suggested_p_base_range.min).toBeGreaterThanOrEqual(0.3);
      expect(stats.suggested_p_base_range.max).toBeLessThanOrEqual(0.7);
    });

    test('should provide suggested RR_min', () => {
      const stats = getTemplateStats('rr_template');
      
      expect(stats.suggested_rr_min).toBeDefined();
      expect(stats.suggested_rr_min).toBeGreaterThanOrEqual(1.5);
    });
  });

  // ============================================================================
  // Storage Info Tests
  // ============================================================================
  describe('getStorageInfo', () => {
    test('should return storage info', () => {
      const info = getStorageInfo();
      
      expect(info.dataDir).toBeDefined();
      expect(info.plansFile).toBeDefined();
      expect(typeof info.totalPlans).toBe('number');
      expect(typeof info.cachedStats).toBe('number');
    });
  });
});
