/**
 * Binance Futures Helpers
 * Utility functions for price/quantity rounding, validation, and symbol whitelisting
 * 
 * 币安期货辅助工具
 * 价格/数量取整、校验和交易对白名单的实用函数
 */

import { log, LogLevel } from './logging.js';

// Symbol whitelist for Binance USDT-M Futures
// 币安USDT永续合约交易对白名单
export const ALLOWED_FUTURES_SYMBOLS = ['BTCUSDT', 'ETHUSDT'] as const;
export type AllowedFuturesSymbol = typeof ALLOWED_FUTURES_SYMBOLS[number];

/**
 * Validate if a symbol is in the whitelist
 * @param symbol Symbol to validate
 * @returns Validated symbol or throws error
 * 
 * 验证交易对是否在白名单中
 */
export function validateFuturesSymbol(symbol: string): AllowedFuturesSymbol {
  const normalizedSymbol = symbol.toUpperCase().replace('/', '');
  if (!ALLOWED_FUTURES_SYMBOLS.includes(normalizedSymbol as AllowedFuturesSymbol)) {
    throw new Error(
      `Symbol '${symbol}' is not allowed. Only ${ALLOWED_FUTURES_SYMBOLS.join(', ')} are supported.`
    );
  }
  return normalizedSymbol as AllowedFuturesSymbol;
}

/**
 * Convert symbol format between CCXT (BTC/USDT) and Binance (BTCUSDT)
 * 
 * 在CCXT格式(BTC/USDT)和币安格式(BTCUSDT)之间转换
 */
export function toCcxtSymbol(symbol: string): string {
  const normalized = symbol.toUpperCase().replace('/', '');
  if (normalized === 'BTCUSDT') return 'BTC/USDT:USDT';
  if (normalized === 'ETHUSDT') return 'ETH/USDT:USDT';
  return symbol;
}

export function toBinanceSymbol(symbol: string): string {
  return symbol.toUpperCase().replace('/', '').replace(':USDT', '');
}

/**
 * Exchange info structure for futures trading
 * 期货交易的交易所信息结构
 */
export interface FuturesExchangeInfo {
  symbol: string;
  tickSize: number;
  stepSize: number;
  minQty: number;
  minNotional: number;
  pricePrecision: number;
  qtyPrecision: number;
  maxLeverage?: number;
  missing_fields?: string[];
  downgrade?: string;
}

/**
 * Round price to tick size (toward less aggressive price - more conservative)
 * For BUY: round down (pay less)
 * For SELL: round up (get more)
 * 
 * 将价格取整到tick size（向更保守的方向取整）
 * 买入：向下取整（支付更少）
 * 卖出：向上取整（获得更多）
 * 
 * @param price Price to round
 * @param tickSize Tick size from exchange info
 * @param side Order side (BUY or SELL)
 * @returns Rounded price
 */
export function roundPriceToTick(
  price: number,
  tickSize: number,
  side: 'BUY' | 'SELL'
): number {
  if (tickSize <= 0) {
    throw new Error('tickSize must be positive');
  }
  
  const precision = getDecimalPlaces(tickSize);
  const multiplier = Math.pow(10, precision);
  
  // Calculate ticks
  const ticks = price / tickSize;
  
  // Round toward conservative direction based on side
  // BUY limit order: lower price is more conservative (may not fill)
  // SELL limit order: higher price is more conservative (may not fill)
  const roundedTicks = side === 'BUY' 
    ? Math.floor(ticks) 
    : Math.ceil(ticks);
  
  const result = roundedTicks * tickSize;
  
  // Fix floating point precision issues
  return Math.round(result * multiplier) / multiplier;
}

/**
 * Round quantity to step size (toward smaller quantity - more conservative)
 * Always rounds down to avoid exceeding limits or balance
 * 
 * 将数量取整到step size（向更小的数量取整 - 更保守）
 * 始终向下取整以避免超过限制或余额
 * 
 * @param qty Quantity to round
 * @param stepSize Step size from exchange info
 * @returns Rounded quantity
 */
export function roundQtyToStep(qty: number, stepSize: number): number {
  if (stepSize <= 0) {
    throw new Error('stepSize must be positive');
  }
  
  const precision = getDecimalPlaces(stepSize);
  const multiplier = Math.pow(10, precision);
  
  // Always round down for quantity (conservative)
  const steps = Math.floor(qty / stepSize);
  const result = steps * stepSize;
  
  // Fix floating point precision issues
  return Math.round(result * multiplier) / multiplier;
}

/**
 * Get the number of decimal places in a number
 * 获取数字的小数位数
 */
export function getDecimalPlaces(num: number): number {
  if (Math.floor(num) === num) return 0;
  const str = num.toString();
  if (str.includes('e-')) {
    // Handle scientific notation
    const [, exp] = str.split('e-');
    return parseInt(exp, 10);
  }
  return str.split('.')[1]?.length || 0;
}

/**
 * Validate order parameters against exchange rules
 * 根据交易所规则验证订单参数
 */
export interface OrderValidationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
  adjusted: {
    price?: number;
    qty?: number;
  };
}

export function validateOrderParams(
  price: number,
  qty: number,
  side: 'BUY' | 'SELL',
  exchangeInfo: FuturesExchangeInfo
): OrderValidationResult {
  const errors: string[] = [];
  const warnings: string[] = [];
  const adjusted: { price?: number; qty?: number } = {};
  
  // Validate and adjust price
  const roundedPrice = roundPriceToTick(price, exchangeInfo.tickSize, side);
  if (roundedPrice !== price) {
    warnings.push(
      `Price ${price} adjusted to ${roundedPrice} to match tick size ${exchangeInfo.tickSize}`
    );
    adjusted.price = roundedPrice;
  }
  
  // Validate and adjust quantity
  const roundedQty = roundQtyToStep(qty, exchangeInfo.stepSize);
  if (roundedQty !== qty) {
    warnings.push(
      `Quantity ${qty} adjusted to ${roundedQty} to match step size ${exchangeInfo.stepSize}`
    );
    adjusted.qty = roundedQty;
  }
  
  // Check minimum quantity
  if (roundedQty < exchangeInfo.minQty) {
    errors.push(
      `Quantity ${roundedQty} is below minimum ${exchangeInfo.minQty}`
    );
  }
  
  // Check minimum notional value
  const notional = roundedPrice * roundedQty;
  if (notional < exchangeInfo.minNotional) {
    errors.push(
      `Notional value ${notional.toFixed(2)} USDT is below minimum ${exchangeInfo.minNotional} USDT`
    );
  }
  
  return {
    valid: errors.length === 0,
    errors,
    warnings,
    adjusted: Object.keys(adjusted).length > 0 ? adjusted : {}
  };
}

/**
 * Parse exchange info from CCXT market data
 * 从CCXT市场数据解析交易所信息
 */
export function parseExchangeInfoFromMarket(market: any): FuturesExchangeInfo {
  const missing_fields: string[] = [];
  let downgrade: string | undefined;
  
  // Extract tick size (price precision)
  let tickSize = market.precision?.price;
  if (typeof tickSize === 'number' && tickSize > 1) {
    // CCXT sometimes returns precision as number of decimal places
    tickSize = Math.pow(10, -tickSize);
  }
  if (!tickSize && market.info?.filters) {
    const priceFilter = market.info.filters.find((f: any) => f.filterType === 'PRICE_FILTER');
    tickSize = parseFloat(priceFilter?.tickSize || '0');
  }
  if (!tickSize || tickSize <= 0) {
    missing_fields.push('tickSize');
    tickSize = 0.01; // Default fallback
    downgrade = 'Using default tickSize=0.01';
  }
  
  // Extract step size (quantity precision)
  let stepSize = market.precision?.amount;
  if (typeof stepSize === 'number' && stepSize > 1) {
    stepSize = Math.pow(10, -stepSize);
  }
  if (!stepSize && market.info?.filters) {
    const lotFilter = market.info.filters.find((f: any) => f.filterType === 'LOT_SIZE');
    stepSize = parseFloat(lotFilter?.stepSize || '0');
  }
  if (!stepSize || stepSize <= 0) {
    missing_fields.push('stepSize');
    stepSize = 0.001; // Default fallback
    downgrade = (downgrade || '') + '; Using default stepSize=0.001';
  }
  
  // Extract min quantity
  let minQty = market.limits?.amount?.min;
  if (!minQty && market.info?.filters) {
    const lotFilter = market.info.filters.find((f: any) => f.filterType === 'LOT_SIZE');
    minQty = parseFloat(lotFilter?.minQty || '0');
  }
  if (!minQty || minQty <= 0) {
    missing_fields.push('minQty');
    minQty = 0.001;
    downgrade = (downgrade || '') + '; Using default minQty=0.001';
  }
  
  // Extract min notional
  let minNotional = market.limits?.cost?.min;
  if (!minNotional && market.info?.filters) {
    const notionalFilter = market.info.filters.find((f: any) => f.filterType === 'MIN_NOTIONAL');
    minNotional = parseFloat(notionalFilter?.notional || notionalFilter?.minNotional || '0');
  }
  if (!minNotional || minNotional <= 0) {
    missing_fields.push('minNotional');
    minNotional = 5; // Default 5 USDT
    downgrade = (downgrade || '') + '; Using default minNotional=5';
  }
  
  // Calculate precision values
  const pricePrecision = getDecimalPlaces(tickSize);
  const qtyPrecision = getDecimalPlaces(stepSize);
  
  // Max leverage (if available)
  let maxLeverage: number | undefined;
  if (market.info?.maxLeverage) {
    maxLeverage = parseInt(market.info.maxLeverage, 10);
  }
  
  const result: FuturesExchangeInfo = {
    symbol: toBinanceSymbol(market.symbol || ''),
    tickSize,
    stepSize,
    minQty,
    minNotional,
    pricePrecision,
    qtyPrecision,
    maxLeverage
  };
  
  if (missing_fields.length > 0) {
    result.missing_fields = missing_fields;
    result.downgrade = downgrade?.replace(/^; /, '');
  }
  
  return result;
}

/**
 * Generate a unique client order ID
 * 生成唯一的客户端订单ID
 */
export function generateClientOrderId(prefix: string = 'mcp'): string {
  const timestamp = Date.now().toString(36);
  const random = Math.random().toString(36).substring(2, 8);
  return `${prefix}_${timestamp}_${random}`;
}

/**
 * Calculate liquidation price estimate
 * This is a simplified calculation - actual liquidation price depends on many factors
 * 
 * 计算爆仓价格估算（简化计算）
 */
export function estimateLiquidationPrice(
  entryPrice: number,
  leverage: number,
  side: 'LONG' | 'SHORT',
  maintenanceMarginRate: number = 0.004 // Default 0.4% for BTC/ETH
): number {
  // Simplified formula:
  // For LONG: Liq Price = Entry Price * (1 - 1/Leverage + MMR)
  // For SHORT: Liq Price = Entry Price * (1 + 1/Leverage - MMR)
  
  if (side === 'LONG') {
    return entryPrice * (1 - 1 / leverage + maintenanceMarginRate);
  } else {
    return entryPrice * (1 + 1 / leverage - maintenanceMarginRate);
  }
}

/**
 * Validate leverage against allowed range
 * 验证杠杆是否在允许范围内
 */
export function validateLeverage(leverage: number, maxLeverage: number = 125): boolean {
  return leverage >= 1 && leverage <= maxLeverage && Number.isInteger(leverage);
}

/**
 * Parse stop price for stop orders
 * 解析止损止盈订单的触发价格
 */
export function validateStopPrice(
  stopPrice: number,
  currentPrice: number,
  side: 'BUY' | 'SELL',
  orderType: 'STOP_LOSS' | 'TAKE_PROFIT'
): { valid: boolean; error?: string } {
  // For STOP_LOSS:
  // - SELL (long position): stopPrice must be < currentPrice
  // - BUY (short position): stopPrice must be > currentPrice
  
  // For TAKE_PROFIT:
  // - SELL (long position): stopPrice must be > currentPrice
  // - BUY (short position): stopPrice must be < currentPrice
  
  if (orderType === 'STOP_LOSS') {
    if (side === 'SELL' && stopPrice >= currentPrice) {
      return { valid: false, error: 'Stop loss sell price must be below current price' };
    }
    if (side === 'BUY' && stopPrice <= currentPrice) {
      return { valid: false, error: 'Stop loss buy price must be above current price' };
    }
  } else if (orderType === 'TAKE_PROFIT') {
    if (side === 'SELL' && stopPrice <= currentPrice) {
      return { valid: false, error: 'Take profit sell price must be above current price' };
    }
    if (side === 'BUY' && stopPrice >= currentPrice) {
      return { valid: false, error: 'Take profit buy price must be below current price' };
    }
  }
  
  return { valid: true };
}

/**
 * Calculate position value and required margin
 * 计算仓位价值和所需保证金
 */
export function calculatePositionMetrics(
  qty: number,
  entryPrice: number,
  leverage: number,
  markPrice: number
): {
  positionValue: number;
  margin: number;
  unrealizedPnl: number;
  unrealizedPnlPercent: number;
} {
  const positionValue = qty * markPrice;
  const margin = positionValue / leverage;
  const entryValue = qty * entryPrice;
  const unrealizedPnl = positionValue - entryValue;
  const unrealizedPnlPercent = (unrealizedPnl / margin) * 100;
  
  return {
    positionValue,
    margin,
    unrealizedPnl,
    unrealizedPnlPercent
  };
}

/**
 * Rate limit status for Binance API
 * 币安API的频率限制状态
 */
export interface RateLimitStatus {
  requestWeight: number;
  orderCount: number;
  timestamp: number;
}

const rateLimitState: Record<string, RateLimitStatus> = {};

export function updateRateLimitStatus(
  apiKey: string,
  headers: Record<string, string>
): void {
  const weight = parseInt(headers['x-mbx-used-weight-1m'] || '0', 10);
  const orderCount = parseInt(headers['x-mbx-order-count-1m'] || '0', 10);
  
  rateLimitState[apiKey] = {
    requestWeight: weight,
    orderCount,
    timestamp: Date.now()
  };
  
  // Log warning if approaching limits
  if (weight > 1000) {
    log(LogLevel.WARNING, `Rate limit warning: weight ${weight}/1200`);
  }
  if (orderCount > 250) {
    log(LogLevel.WARNING, `Order rate limit warning: ${orderCount}/300`);
  }
}

export function getRateLimitStatus(apiKey: string): RateLimitStatus | null {
  return rateLimitState[apiKey] || null;
}
