/**
 * Trade Statistics and Plan Logging
 * SQLite-based storage for trade plans and performance statistics
 * 
 * 交易统计和计划日志
 * 基于SQLite的交易计划和绩效统计存储
 */

import * as fs from 'fs';
import * as path from 'path';
import { log, LogLevel } from './logging.js';

// Trade plan snapshot structure
// 交易计划快照结构
export interface TradePlanSnapshot {
  plan_id: string;
  template_id: string;
  session: string;
  v_regime: string;
  symbol: string;
  side: 'LONG' | 'SHORT';
  inputs_summary: {
    entry_price: number;
    sl_price: number;
    tp_prices: number[];
    qty: number;
    leverage: number;
    risk_amount?: number;
  };
  orders_submitted: OrderSubmitted[];
  fills: OrderFill[];
  outcome: TradeOutcome;
  created_at: string;
  updated_at: string;
}

export interface OrderSubmitted {
  order_id: string;
  client_order_id?: string;
  type: 'ENTRY' | 'SL' | 'TP';
  order_type: string;
  price?: number;
  stop_price?: number;
  qty: number;
  status: string;
  submitted_at: string;
}

export interface OrderFill {
  order_id: string;
  type: 'ENTRY' | 'SL' | 'TP';
  filled_price: number;
  filled_qty: number;
  commission: number;
  commission_asset: string;
  filled_at: string;
  slippage?: number;
}

export interface TradeOutcome {
  status: 'PENDING' | 'FILLED' | 'PARTIAL' | 'CANCELLED' | 'STOPPED_OUT' | 'TP_HIT' | 'MANUAL_CLOSE';
  pnl?: number;
  pnl_percent?: number;
  rr_realized?: number;
  mae?: number; // Maximum Adverse Excursion
  mfe?: number; // Maximum Favorable Excursion
  hold_time_seconds?: number;
  exit_reason?: string;
}

// Template statistics structure
// 模板统计结构
export interface TemplateStats {
  template_id: string;
  session?: string;
  v_regime?: string;
  symbol?: string;
  total_trades: number;
  wins: number;
  losses: number;
  winrate: number;
  avg_rr: number;
  p50_rr: number;
  p90_rr: number;
  avg_mae: number;
  avg_mfe: number;
  fill_rate: number;
  avg_time_to_fill_seconds: number;
  stop_slippage_p95: number;
  suggested_p_base_range: {
    min: number;
    max: number;
  };
  suggested_rr_min: number;
  sample_size: number;
  last_updated: string;
}

// Data storage directory
const DATA_DIR = process.env.TRADE_DATA_DIR || path.join(process.cwd(), 'data');
const PLANS_FILE = path.join(DATA_DIR, 'trade_plans.jsonl');
const STATS_CACHE_FILE = path.join(DATA_DIR, 'template_stats_cache.json');

// In-memory cache for stats
let statsCache: Record<string, TemplateStats> = {};
let plansCache: TradePlanSnapshot[] = [];
let cacheLoaded = false;

/**
 * Ensure data directory exists
 * 确保数据目录存在
 */
function ensureDataDir(): void {
  if (!fs.existsSync(DATA_DIR)) {
    fs.mkdirSync(DATA_DIR, { recursive: true });
    log(LogLevel.INFO, `Created data directory: ${DATA_DIR}`);
  }
}

/**
 * Load plans from JSONL file
 * 从JSONL文件加载计划
 */
function loadPlans(): TradePlanSnapshot[] {
  ensureDataDir();
  
  if (!fs.existsSync(PLANS_FILE)) {
    return [];
  }
  
  try {
    const content = fs.readFileSync(PLANS_FILE, 'utf-8');
    const lines = content.trim().split('\n').filter(line => line.trim());
    return lines.map(line => JSON.parse(line) as TradePlanSnapshot);
  } catch (error) {
    log(LogLevel.ERROR, `Error loading trade plans: ${error}`);
    return [];
  }
}

/**
 * Load stats cache from file
 * 从文件加载统计缓存
 */
function loadStatsCache(): Record<string, TemplateStats> {
  ensureDataDir();
  
  if (!fs.existsSync(STATS_CACHE_FILE)) {
    return {};
  }
  
  try {
    const content = fs.readFileSync(STATS_CACHE_FILE, 'utf-8');
    return JSON.parse(content);
  } catch (error) {
    log(LogLevel.ERROR, `Error loading stats cache: ${error}`);
    return {};
  }
}

/**
 * Save plan to JSONL file
 * 将计划保存到JSONL文件
 */
function savePlan(plan: TradePlanSnapshot): void {
  ensureDataDir();
  
  const line = JSON.stringify(plan) + '\n';
  fs.appendFileSync(PLANS_FILE, line, 'utf-8');
  
  // Update in-memory cache
  const existingIndex = plansCache.findIndex(p => p.plan_id === plan.plan_id);
  if (existingIndex >= 0) {
    plansCache[existingIndex] = plan;
  } else {
    plansCache.push(plan);
  }
}

/**
 * Save stats cache to file
 * 将统计缓存保存到文件
 */
function saveStatsCache(): void {
  ensureDataDir();
  fs.writeFileSync(STATS_CACHE_FILE, JSON.stringify(statsCache, null, 2), 'utf-8');
}

/**
 * Initialize cache if not loaded
 * 如果未加载则初始化缓存
 */
function ensureCacheLoaded(): void {
  if (!cacheLoaded) {
    plansCache = loadPlans();
    statsCache = loadStatsCache();
    cacheLoaded = true;
    log(LogLevel.INFO, `Loaded ${plansCache.length} trade plans from storage`);
  }
}

/**
 * Log a trade plan snapshot
 * 记录交易计划快照
 */
export function logTradePlanSnapshot(
  plan_id: string,
  template_id: string,
  session: string,
  v_regime: string,
  symbol: string,
  side: 'LONG' | 'SHORT',
  inputs_summary: TradePlanSnapshot['inputs_summary'],
  orders_submitted: OrderSubmitted[],
  fills: OrderFill[],
  outcome: TradeOutcome
): TradePlanSnapshot {
  ensureCacheLoaded();
  
  const now = new Date().toISOString();
  
  // Check if plan exists
  const existingPlan = plansCache.find(p => p.plan_id === plan_id);
  
  const plan: TradePlanSnapshot = existingPlan ? {
    ...existingPlan,
    orders_submitted: orders_submitted.length > 0 ? orders_submitted : existingPlan.orders_submitted,
    fills: fills.length > 0 ? fills : existingPlan.fills,
    outcome,
    updated_at: now
  } : {
    plan_id,
    template_id,
    session,
    v_regime,
    symbol,
    side,
    inputs_summary,
    orders_submitted,
    fills,
    outcome,
    created_at: now,
    updated_at: now
  };
  
  savePlan(plan);
  log(LogLevel.INFO, `Logged trade plan snapshot: ${plan_id}`);
  
  // Invalidate stats cache for this template
  const cacheKey = `${template_id}:${session}:${v_regime}:${symbol}`;
  delete statsCache[cacheKey];
  
  return plan;
}

/**
 * Calculate percentile from sorted array
 * 从排序数组计算百分位数
 */
function percentile(sortedArr: number[], p: number): number {
  if (sortedArr.length === 0) return 0;
  const index = Math.ceil((p / 100) * sortedArr.length) - 1;
  return sortedArr[Math.max(0, Math.min(index, sortedArr.length - 1))];
}

/**
 * Calculate template statistics
 * 计算模板统计
 */
export function getTemplateStats(
  template_id: string,
  session?: string,
  v_regime?: string,
  symbol?: string
): TemplateStats {
  ensureCacheLoaded();
  
  // Check cache
  const cacheKey = `${template_id}:${session || 'all'}:${v_regime || 'all'}:${symbol || 'all'}`;
  if (statsCache[cacheKey]) {
    return statsCache[cacheKey];
  }
  
  // Filter plans
  let filteredPlans = plansCache.filter(p => p.template_id === template_id);
  
  if (session) {
    filteredPlans = filteredPlans.filter(p => p.session === session);
  }
  if (v_regime) {
    filteredPlans = filteredPlans.filter(p => p.v_regime === v_regime);
  }
  if (symbol) {
    filteredPlans = filteredPlans.filter(p => p.symbol === symbol);
  }
  
  // Calculate statistics
  const completedTrades = filteredPlans.filter(p => 
    p.outcome.status !== 'PENDING' && p.outcome.rr_realized !== undefined
  );
  
  const wins = completedTrades.filter(p => (p.outcome.pnl || 0) > 0);
  const losses = completedTrades.filter(p => (p.outcome.pnl || 0) <= 0);
  
  const rrValues = completedTrades
    .map(p => p.outcome.rr_realized || 0)
    .sort((a, b) => a - b);
  
  const maeValues = completedTrades
    .filter(p => p.outcome.mae !== undefined)
    .map(p => p.outcome.mae!)
    .sort((a, b) => a - b);
  
  const mfeValues = completedTrades
    .filter(p => p.outcome.mfe !== undefined)
    .map(p => p.outcome.mfe!)
    .sort((a, b) => a - b);
  
  // Calculate fill metrics
  const filledEntries = filteredPlans.filter(p => 
    p.fills.some(f => f.type === 'ENTRY')
  );
  
  const fillTimes = filledEntries.map(p => {
    const submitted = p.orders_submitted.find(o => o.type === 'ENTRY');
    const filled = p.fills.find(f => f.type === 'ENTRY');
    if (submitted && filled) {
      return (new Date(filled.filled_at).getTime() - new Date(submitted.submitted_at).getTime()) / 1000;
    }
    return 0;
  }).filter(t => t > 0);
  
  // Calculate stop slippage
  const stopSlippages = filteredPlans
    .filter(p => p.outcome.status === 'STOPPED_OUT')
    .map(p => {
      const slOrder = p.orders_submitted.find(o => o.type === 'SL');
      const slFill = p.fills.find(f => f.type === 'SL');
      if (slOrder && slFill && slOrder.stop_price) {
        return Math.abs(slFill.filled_price - slOrder.stop_price) / slOrder.stop_price * 100;
      }
      return 0;
    })
    .filter(s => s > 0)
    .sort((a, b) => a - b);
  
  const avgRr = rrValues.length > 0 
    ? rrValues.reduce((a, b) => a + b, 0) / rrValues.length 
    : 0;
  
  const winrate = completedTrades.length > 0 
    ? wins.length / completedTrades.length 
    : 0;
  
  // Calculate suggested P_base range based on historical winrate
  const suggestedPBaseMin = Math.max(0.3, winrate - 0.1);
  const suggestedPBaseMax = Math.min(0.7, winrate + 0.1);
  
  // Calculate suggested minimum RR based on winrate to be profitable
  // Required RR = (1 - winrate) / winrate for breakeven
  const breakEvenRr = winrate > 0 ? (1 - winrate) / winrate : 2;
  const suggestedRrMin = Math.max(1.5, breakEvenRr * 1.2); // 20% buffer above breakeven
  
  const stats: TemplateStats = {
    template_id,
    session,
    v_regime,
    symbol,
    total_trades: filteredPlans.length,
    wins: wins.length,
    losses: losses.length,
    winrate,
    avg_rr: avgRr,
    p50_rr: percentile(rrValues, 50),
    p90_rr: percentile(rrValues, 90),
    avg_mae: maeValues.length > 0 ? maeValues.reduce((a, b) => a + b, 0) / maeValues.length : 0,
    avg_mfe: mfeValues.length > 0 ? mfeValues.reduce((a, b) => a + b, 0) / mfeValues.length : 0,
    fill_rate: filteredPlans.length > 0 ? filledEntries.length / filteredPlans.length : 0,
    avg_time_to_fill_seconds: fillTimes.length > 0 
      ? fillTimes.reduce((a, b) => a + b, 0) / fillTimes.length 
      : 0,
    stop_slippage_p95: percentile(stopSlippages, 95),
    suggested_p_base_range: {
      min: suggestedPBaseMin,
      max: suggestedPBaseMax
    },
    suggested_rr_min: suggestedRrMin,
    sample_size: completedTrades.length,
    last_updated: new Date().toISOString()
  };
  
  // Cache the result
  statsCache[cacheKey] = stats;
  saveStatsCache();
  
  return stats;
}

/**
 * Get all trade plans for a symbol
 * 获取某交易对的所有交易计划
 */
export function getTradePlans(
  symbol?: string,
  limit: number = 100,
  offset: number = 0
): TradePlanSnapshot[] {
  ensureCacheLoaded();
  
  let plans = plansCache;
  
  if (symbol) {
    plans = plans.filter(p => p.symbol === symbol);
  }
  
  // Sort by created_at descending
  plans.sort((a, b) => 
    new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  );
  
  return plans.slice(offset, offset + limit);
}

/**
 * Get a specific trade plan by ID
 * 根据ID获取特定交易计划
 */
export function getTradePlan(plan_id: string): TradePlanSnapshot | null {
  ensureCacheLoaded();
  return plansCache.find(p => p.plan_id === plan_id) || null;
}

/**
 * Update trade plan outcome
 * 更新交易计划结果
 */
export function updateTradePlanOutcome(
  plan_id: string,
  outcome: Partial<TradeOutcome>,
  newFills?: OrderFill[]
): TradePlanSnapshot | null {
  ensureCacheLoaded();
  
  const plan = plansCache.find(p => p.plan_id === plan_id);
  if (!plan) {
    log(LogLevel.WARNING, `Trade plan not found: ${plan_id}`);
    return null;
  }
  
  const updatedPlan: TradePlanSnapshot = {
    ...plan,
    outcome: { ...plan.outcome, ...outcome },
    fills: newFills ? [...plan.fills, ...newFills] : plan.fills,
    updated_at: new Date().toISOString()
  };
  
  savePlan(updatedPlan);
  
  // Invalidate stats cache
  const cacheKey = `${plan.template_id}:${plan.session}:${plan.v_regime}:${plan.symbol}`;
  delete statsCache[cacheKey];
  
  return updatedPlan;
}

/**
 * Clear all cached data (for testing)
 * 清除所有缓存数据（用于测试）
 */
export function clearTradeStatsCache(): void {
  plansCache = [];
  statsCache = {};
  cacheLoaded = false;
}

/**
 * Get storage info
 * 获取存储信息
 */
export function getStorageInfo(): {
  dataDir: string;
  plansFile: string;
  totalPlans: number;
  cachedStats: number;
} {
  ensureCacheLoaded();
  
  return {
    dataDir: DATA_DIR,
    plansFile: PLANS_FILE,
    totalPlans: plansCache.length,
    cachedStats: Object.keys(statsCache).length
  };
}
