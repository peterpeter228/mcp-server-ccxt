/**
 * Binance Futures Risk & Order Tools
 * Complete risk management and order execution tools for Binance USDT-M Futures
 * 
 * 币安期货风控与下单工具
 * 完整的币安USDT永续合约风险管理和订单执行工具
 */

import { z } from 'zod';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import * as ccxt from 'ccxt';
import { getExchangeWithCredentials, MarketType } from '../exchange/manager.js';
import { log, LogLevel } from '../utils/logging.js';
import { rateLimiter } from '../utils/rate-limiter.js';
import { getCachedData, clearCache } from '../utils/cache.js';
import {
  validateFuturesSymbol,
  toCcxtSymbol,
  toBinanceSymbol,
  parseExchangeInfoFromMarket,
  roundPriceToTick,
  roundQtyToStep,
  validateOrderParams,
  generateClientOrderId,
  validateLeverage,
  FuturesExchangeInfo,
  ALLOWED_FUTURES_SYMBOLS
} from '../utils/futures-helpers.js';
import {
  logTradePlanSnapshot,
  getTemplateStats as getTemplateStatsFromStorage,
  TradePlanSnapshot,
  OrderSubmitted,
  OrderFill,
  TradeOutcome,
  TemplateStats
} from '../utils/trade-stats.js';

// Common Zod schemas
// 通用Zod验证模式
const futuresSymbolSchema = z.enum(['BTCUSDT', 'ETHUSDT', 'BTC/USDT', 'ETH/USDT'])
  .describe('Trading pair symbol (BTCUSDT or ETHUSDT)');

const credentialsSchema = {
  apiKey: z.string().describe('Binance API key'),
  secret: z.string().describe('Binance API secret')
};

const positionSideSchema = z.enum(['BOTH', 'LONG', 'SHORT']).default('BOTH')
  .describe('Position side for hedge mode');

/**
 * Get Binance USDT-M Futures exchange instance
 * 获取币安USDT永续合约交易所实例
 */
function getBinanceFutures(apiKey: string, secret: string): ccxt.Exchange {
  return getExchangeWithCredentials('binanceusdm', apiKey, secret, MarketType.SWAP);
}

/**
 * Register all Binance Futures tools with the MCP server
 * 向MCP服务器注册所有币安期货工具
 */
export function registerBinanceFuturesTools(server: McpServer) {
  
  // ============================================================================
  // A. Exchange Rules & Precision Tools
  // A. 交易所规则与精度工具
  // ============================================================================

  /**
   * Tool 1: get_exchange_info_futures
   * Get exchange info with tick size, step size, min qty, min notional
   * 
   * 工具1：获取期货交易所信息
   * 获取tick size、step size、最小数量、最小名义价值等信息
   */
  server.tool(
    'get_exchange_info_futures',
    'Get Binance USDT-M Futures exchange info for a symbol including tickSize, stepSize, minQty, minNotional, pricePrecision, qtyPrecision, and maxLeverage',
    {
      symbol: futuresSymbolSchema
    },
    async ({ symbol }) => {
      try {
        const validSymbol = validateFuturesSymbol(symbol);
        const ccxtSymbol = toCcxtSymbol(validSymbol);
        
        return await rateLimiter.execute('binanceusdm', async () => {
          const cacheKey = `futures_exchange_info:binanceusdm:${validSymbol}`;
          
          const info = await getCachedData(cacheKey, async () => {
            log(LogLevel.INFO, `Fetching exchange info for ${validSymbol}`);
            
            // Create exchange without auth for public data
            const exchange = new (ccxt as any).binanceusdm({
              enableRateLimit: true,
              options: { defaultType: 'swap' }
            });
            
            await exchange.loadMarkets();
            const market = exchange.market(ccxtSymbol);
            
            return parseExchangeInfoFromMarket(market);
          }, 5 * 60 * 1000); // Cache for 5 minutes
          
          return {
            content: [{
              type: 'text',
              text: JSON.stringify(info, null, 2)
            }]
          };
        });
      } catch (error) {
        log(LogLevel.ERROR, `Error fetching exchange info: ${error}`);
        return {
          content: [{
            type: 'text',
            text: `Error: ${error instanceof Error ? error.message : String(error)}`
          }],
          isError: true
        };
      }
    }
  );

  // ============================================================================
  // B. Real Fee Rates & Risk Geometry Tools
  // B. 真实费率与风险几何工具
  // ============================================================================

  /**
   * Tool 2: get_commission_rate_futures
   * Get account-level maker/taker commission rates
   * 
   * 工具2：获取期货手续费率
   * 获取账户级别的maker/taker手续费率
   */
  server.tool(
    'get_commission_rate_futures',
    'Get your actual maker/taker commission rates for Binance USDT-M Futures',
    {
      symbol: futuresSymbolSchema,
      ...credentialsSchema
    },
    async ({ symbol, apiKey, secret }) => {
      try {
        const validSymbol = validateFuturesSymbol(symbol);
        
        return await rateLimiter.execute('binanceusdm', async () => {
          const exchange = getBinanceFutures(apiKey, secret);
          await exchange.loadMarkets();
          
          log(LogLevel.INFO, `Fetching commission rates for ${validSymbol}`);
          
          // Try CCXT fetchTradingFee first
          let commissionData: any;
          try {
            commissionData = await exchange.fetchTradingFee(toCcxtSymbol(validSymbol));
          } catch {
            // Fallback to direct API call
            try {
              const response = await (exchange as any).fapiPrivateGetCommissionRate({
                symbol: validSymbol
              });
              commissionData = {
                symbol: validSymbol,
                maker: parseFloat(response.makerCommissionRate),
                taker: parseFloat(response.takerCommissionRate)
              };
            } catch (err) {
              // Final fallback: use default rates
              commissionData = {
                symbol: validSymbol,
                maker: 0.0002, // 0.02%
                taker: 0.0004, // 0.04%
                note: 'Using default rates - could not fetch actual rates'
              };
            }
          }
          
          return {
            content: [{
              type: 'text',
              text: JSON.stringify({
                symbol: validSymbol,
                maker: commissionData.maker,
                taker: commissionData.taker,
                makerPercent: `${(commissionData.maker * 100).toFixed(4)}%`,
                takerPercent: `${(commissionData.taker * 100).toFixed(4)}%`,
                note: commissionData.note
              }, null, 2)
            }]
          };
        });
      } catch (error) {
        log(LogLevel.ERROR, `Error fetching commission rates: ${error}`);
        return {
          content: [{
            type: 'text',
            text: `Error: ${error instanceof Error ? error.message : String(error)}`
          }],
          isError: true
        };
      }
    }
  );

  /**
   * Tool 3: get_position_risk
   * Get real position risk including liquidation price, margin, etc.
   * 
   * 工具3：获取仓位风险
   * 获取真实仓位风险，包括爆仓价、保证金等
   */
  server.tool(
    'get_position_risk',
    'Get position risk info including markPrice, liquidationPrice, maintenanceMarginRate, isolatedMargin, leverage, positionAmt, entryPrice, marginType',
    {
      symbol: futuresSymbolSchema,
      ...credentialsSchema
    },
    async ({ symbol, apiKey, secret }) => {
      try {
        const validSymbol = validateFuturesSymbol(symbol);
        
        return await rateLimiter.execute('binanceusdm', async () => {
          const exchange = getBinanceFutures(apiKey, secret);
          await exchange.loadMarkets();
          
          log(LogLevel.INFO, `Fetching position risk for ${validSymbol}`);
          
          // Try CCXT fetchPositions first
          let positionData: any;
          try {
            const positions = await exchange.fetchPositions([toCcxtSymbol(validSymbol)]);
            const position = positions.find((p: any) => 
              toBinanceSymbol(p.symbol) === validSymbol
            );
            
            if (position) {
              positionData = {
                symbol: validSymbol,
                markPrice: position.markPrice,
                liquidationPrice: position.liquidationPrice,
                maintenanceMarginRate: position.maintenanceMarginPercentage,
                isolatedMargin: position.collateral,
                leverage: position.leverage,
                positionAmt: position.contracts,
                entryPrice: position.entryPrice,
                marginType: position.marginMode?.toUpperCase() || 'UNKNOWN',
                unrealizedPnl: position.unrealizedPnl,
                side: position.side
              };
            }
          } catch {
            // Fallback to direct API call
            try {
              const response = await (exchange as any).fapiPrivateV2GetPositionRisk({
                symbol: validSymbol
              });
              
              const pos = Array.isArray(response) ? response[0] : response;
              positionData = {
                symbol: validSymbol,
                markPrice: parseFloat(pos.markPrice),
                liquidationPrice: parseFloat(pos.liquidationPrice),
                maintenanceMarginRate: parseFloat(pos.maintMarginRatio || '0'),
                isolatedMargin: parseFloat(pos.isolatedMargin || '0'),
                leverage: parseInt(pos.leverage, 10),
                positionAmt: parseFloat(pos.positionAmt),
                entryPrice: parseFloat(pos.entryPrice),
                marginType: pos.marginType,
                unrealizedPnl: parseFloat(pos.unRealizedProfit)
              };
            } catch (err) {
              throw new Error(`Could not fetch position risk: ${err}`);
            }
          }
          
          if (!positionData) {
            positionData = {
              symbol: validSymbol,
              markPrice: null,
              liquidationPrice: null,
              maintenanceMarginRate: null,
              isolatedMargin: 0,
              leverage: null,
              positionAmt: 0,
              entryPrice: null,
              marginType: null,
              unrealizedPnl: 0,
              note: 'No open position found'
            };
          }
          
          return {
            content: [{
              type: 'text',
              text: JSON.stringify(positionData, null, 2)
            }]
          };
        });
      } catch (error) {
        log(LogLevel.ERROR, `Error fetching position risk: ${error}`);
        return {
          content: [{
            type: 'text',
            text: `Error: ${error instanceof Error ? error.message : String(error)}`
          }],
          isError: true
        };
      }
    }
  );

  /**
   * Tool 4: get_leverage_brackets
   * Get leverage brackets with notional tiers
   * 
   * 工具4：获取杠杆档位
   * 获取带名义价值分层的杠杆档位
   */
  server.tool(
    'get_leverage_brackets',
    'Get leverage brackets showing notional tiers with maintMarginRatio, initialLeverage, notionalCap, notionalFloor',
    {
      symbol: futuresSymbolSchema,
      ...credentialsSchema
    },
    async ({ symbol, apiKey, secret }) => {
      try {
        const validSymbol = validateFuturesSymbol(symbol);
        
        return await rateLimiter.execute('binanceusdm', async () => {
          const cacheKey = `leverage_brackets:binanceusdm:${validSymbol}`;
          
          const brackets = await getCachedData(cacheKey, async () => {
            const exchange = getBinanceFutures(apiKey, secret);
            await exchange.loadMarkets();
            
            log(LogLevel.INFO, `Fetching leverage brackets for ${validSymbol}`);
            
            // Try CCXT fetchMarketLeverageTiers first
            try {
              const tiers = await exchange.fetchMarketLeverageTiers(toCcxtSymbol(validSymbol));
              return tiers.map((tier: any) => ({
                bracket: tier.tier,
                initialLeverage: tier.maxLeverage,
                notionalCap: tier.maxNotional,
                notionalFloor: tier.minNotional,
                maintMarginRatio: tier.maintenanceMarginRate,
                cum: tier.info?.cum
              }));
            } catch {
              // Fallback to direct API call
              const response = await (exchange as any).fapiPrivateGetLeverageBracket({
                symbol: validSymbol
              });
              
              const data = Array.isArray(response) ? response[0] : response;
              return (data.brackets || []).map((b: any) => ({
                bracket: b.bracket,
                initialLeverage: b.initialLeverage,
                notionalCap: b.notionalCap,
                notionalFloor: b.notionalFloor,
                maintMarginRatio: parseFloat(b.maintMarginRatio),
                cum: b.cum
              }));
            }
          }, 60 * 60 * 1000); // Cache for 1 hour
          
          return {
            content: [{
              type: 'text',
              text: JSON.stringify({
                symbol: validSymbol,
                brackets
              }, null, 2)
            }]
          };
        });
      } catch (error) {
        log(LogLevel.ERROR, `Error fetching leverage brackets: ${error}`);
        return {
          content: [{
            type: 'text',
            text: `Error: ${error instanceof Error ? error.message : String(error)}`
          }],
          isError: true
        };
      }
    }
  );

  // ============================================================================
  // C. Account Settings Tools
  // C. 账户设置工具
  // ============================================================================

  /**
   * Tool 5: set_leverage_futures
   * Set leverage for a symbol
   * 
   * 工具5：设置杠杆
   * 设置交易对的杠杆
   */
  server.tool(
    'set_leverage_futures',
    'Set leverage for Binance USDT-M Futures trading',
    {
      symbol: futuresSymbolSchema,
      leverage: z.number().int().min(1).max(125).describe('Leverage value (1-125)'),
      ...credentialsSchema
    },
    async ({ symbol, leverage, apiKey, secret }) => {
      try {
        const validSymbol = validateFuturesSymbol(symbol);
        
        if (!validateLeverage(leverage)) {
          return {
            content: [{
              type: 'text',
              text: JSON.stringify({
                success: false,
                error: 'Invalid leverage value. Must be integer between 1 and 125.'
              }, null, 2)
            }],
            isError: true
          };
        }
        
        return await rateLimiter.execute('binanceusdm', async () => {
          const exchange = getBinanceFutures(apiKey, secret);
          await exchange.loadMarkets();
          
          log(LogLevel.INFO, `Setting leverage to ${leverage}x for ${validSymbol}`);
          
          try {
            const result = await exchange.setLeverage(leverage, toCcxtSymbol(validSymbol));
            
            // Clear cache for position risk
            clearCache(`position_risk:binanceusdm:${validSymbol}`);
            
            return {
              content: [{
                type: 'text',
                text: JSON.stringify({
                  success: true,
                  symbol: validSymbol,
                  leverage: leverage,
                  response: result
                }, null, 2)
              }]
            };
          } catch (error: any) {
            // Handle "leverage not changed" as success
            if (error.message?.includes('No need to change leverage')) {
              return {
                content: [{
                  type: 'text',
                  text: JSON.stringify({
                    success: true,
                    symbol: validSymbol,
                    leverage: leverage,
                    note: 'Leverage already set to this value'
                  }, null, 2)
                }]
              };
            }
            throw error;
          }
        });
      } catch (error) {
        log(LogLevel.ERROR, `Error setting leverage: ${error}`);
        return {
          content: [{
            type: 'text',
            text: `Error: ${error instanceof Error ? error.message : String(error)}`
          }],
          isError: true
        };
      }
    }
  );

  /**
   * Tool 6: set_margin_type_futures
   * Set margin type (ISOLATED or CROSSED)
   * 
   * 工具6：设置保证金类型
   * 设置保证金类型（逐仓或全仓）
   */
  server.tool(
    'set_margin_type_futures',
    'Set margin type (ISOLATED or CROSSED) for Binance USDT-M Futures',
    {
      symbol: futuresSymbolSchema,
      marginType: z.enum(['ISOLATED', 'CROSSED']).describe('Margin type'),
      ...credentialsSchema
    },
    async ({ symbol, marginType, apiKey, secret }) => {
      try {
        const validSymbol = validateFuturesSymbol(symbol);
        
        return await rateLimiter.execute('binanceusdm', async () => {
          const exchange = getBinanceFutures(apiKey, secret);
          await exchange.loadMarkets();
          
          log(LogLevel.INFO, `Setting margin type to ${marginType} for ${validSymbol}`);
          
          // Map to CCXT margin mode
          const ccxtMarginMode = marginType === 'ISOLATED' ? 'isolated' : 'cross';
          
          try {
            const result = await exchange.setMarginMode(ccxtMarginMode, toCcxtSymbol(validSymbol));
            
            // Clear cache for position risk
            clearCache(`position_risk:binanceusdm:${validSymbol}`);
            
            return {
              content: [{
                type: 'text',
                text: JSON.stringify({
                  success: true,
                  symbol: validSymbol,
                  marginType: marginType,
                  response: result
                }, null, 2)
              }]
            };
          } catch (error: any) {
            // Handle "already set" as success
            if (error.message?.includes('No need to change margin type') ||
                error.message?.includes('already')) {
              return {
                content: [{
                  type: 'text',
                  text: JSON.stringify({
                    success: true,
                    symbol: validSymbol,
                    marginType: marginType,
                    note: 'Margin type already set to this value'
                  }, null, 2)
                }]
              };
            }
            throw error;
          }
        });
      } catch (error) {
        log(LogLevel.ERROR, `Error setting margin type: ${error}`);
        return {
          content: [{
            type: 'text',
            text: `Error: ${error instanceof Error ? error.message : String(error)}`
          }],
          isError: true
        };
      }
    }
  );

  // ============================================================================
  // D. Order Engineering Tools
  // D. 下单工程工具
  // ============================================================================

  /**
   * Tool 7: place_bracket_orders
   * Place entry + SL + TPs as bracket orders
   * 
   * 工具7：下挂单组合
   * 一次性下入场单+止损单+止盈单
   */
  server.tool(
    'place_bracket_orders',
    'Place bracket orders (entry + stop loss + take profits) for Binance USDT-M Futures with automatic validation and rounding',
    {
      symbol: futuresSymbolSchema,
      side: z.enum(['BUY', 'SELL']).describe('Entry order side'),
      entry: z.object({
        price: z.number().positive().describe('Entry limit price'),
        qty: z.number().positive().describe('Entry quantity'),
        postOnly: z.boolean().default(true).describe('Post only order'),
        timeInForce: z.enum(['GTC', 'IOC', 'FOK']).default('GTC'),
        clientOrderId: z.string().optional().describe('Custom client order ID')
      }),
      sl: z.object({
        type: z.enum(['STOP_MARKET', 'STOP', 'STOP_LIMIT']).default('STOP_MARKET'),
        stopPrice: z.number().positive().describe('Stop trigger price'),
        price: z.number().positive().optional().describe('Limit price for STOP_LIMIT'),
        reduceOnly: z.boolean().default(true)
      }),
      tps: z.array(z.object({
        price: z.number().positive().describe('Take profit price'),
        qtyPct: z.number().min(0).max(100).optional().describe('Percentage of position'),
        qty: z.number().positive().optional().describe('Absolute quantity'),
        reduceOnly: z.boolean().default(true),
        postOnly: z.boolean().default(true)
      })).min(1).describe('Take profit orders'),
      entry_ttl_sec: z.number().int().positive().optional()
        .describe('Time to live for entry order in seconds'),
      positionSide: positionSideSchema,
      ...credentialsSchema
    },
    async ({ symbol, side, entry, sl, tps, entry_ttl_sec, positionSide, apiKey, secret }) => {
      const submittedOrders: OrderSubmitted[] = [];
      const errors: string[] = [];
      let entryOrderId: string | undefined;
      
      try {
        const validSymbol = validateFuturesSymbol(symbol);
        const ccxtSymbol = toCcxtSymbol(validSymbol);
        
        return await rateLimiter.execute('binanceusdm', async () => {
          const exchange = getBinanceFutures(apiKey, secret);
          await exchange.loadMarkets();
          
          // Get exchange info for validation
          const market = exchange.market(ccxtSymbol);
          const exchangeInfo = parseExchangeInfoFromMarket(market);
          
          log(LogLevel.INFO, `Placing bracket orders for ${validSymbol}`);
          
          // Validate and round entry order
          const entryValidation = validateOrderParams(
            entry.price,
            entry.qty,
            side,
            exchangeInfo
          );
          
          if (!entryValidation.valid) {
            return {
              content: [{
                type: 'text',
                text: JSON.stringify({
                  success: false,
                  errors: entryValidation.errors,
                  warnings: entryValidation.warnings,
                  validation: 'FAILED_ENTRY_VALIDATION'
                }, null, 2)
              }],
              isError: true
            };
          }
          
          const adjustedEntryPrice = entryValidation.adjusted.price || entry.price;
          const adjustedEntryQty = entryValidation.adjusted.qty || entry.qty;
          
          // Validate SL
          const slSide = side === 'BUY' ? 'SELL' : 'BUY';
          const slStopValidation = validateOrderParams(
            sl.stopPrice,
            adjustedEntryQty,
            slSide,
            exchangeInfo
          );
          
          if (!slStopValidation.valid) {
            return {
              content: [{
                type: 'text',
                text: JSON.stringify({
                  success: false,
                  errors: slStopValidation.errors,
                  warnings: slStopValidation.warnings,
                  validation: 'FAILED_SL_VALIDATION'
                }, null, 2)
              }],
              isError: true
            };
          }
          
          // Validate TPs and calculate quantities
          let totalTpQty = 0;
          const validatedTps: Array<{ price: number; qty: number }> = [];
          
          for (const tp of tps) {
            let tpQty: number;
            if (tp.qtyPct !== undefined) {
              tpQty = roundQtyToStep(adjustedEntryQty * (tp.qtyPct / 100), exchangeInfo.stepSize);
            } else if (tp.qty !== undefined) {
              tpQty = roundQtyToStep(tp.qty, exchangeInfo.stepSize);
            } else {
              errors.push('Each TP must have either qtyPct or qty');
              continue;
            }
            
            const tpValidation = validateOrderParams(
              tp.price,
              tpQty,
              slSide,
              exchangeInfo
            );
            
            if (!tpValidation.valid) {
              errors.push(...tpValidation.errors);
              continue;
            }
            
            const adjustedTpPrice = tpValidation.adjusted.price || tp.price;
            const adjustedTpQty = tpValidation.adjusted.qty || tpQty;
            
            totalTpQty += adjustedTpQty;
            validatedTps.push({ price: adjustedTpPrice, qty: adjustedTpQty });
          }
          
          // Ensure total TP qty doesn't exceed entry qty
          if (totalTpQty > adjustedEntryQty) {
            return {
              content: [{
                type: 'text',
                text: JSON.stringify({
                  success: false,
                  errors: [`Total TP quantity (${totalTpQty}) exceeds entry quantity (${adjustedEntryQty})`],
                  validation: 'FAILED_TP_QTY_VALIDATION'
                }, null, 2)
              }],
              isError: true
            };
          }
          
          // Place entry order
          const entryClientOrderId = entry.clientOrderId || generateClientOrderId('entry');
          const entryParams: any = {
            postOnly: entry.postOnly,
            clientOrderId: entryClientOrderId
          };
          
          if (positionSide !== 'BOTH') {
            entryParams.positionSide = positionSide;
          }
          
          try {
            const entryOrder = await exchange.createOrder(
              ccxtSymbol,
              'limit',
              side.toLowerCase(),
              adjustedEntryQty,
              adjustedEntryPrice,
              entryParams
            );
            
            entryOrderId = entryOrder.id;
            submittedOrders.push({
              order_id: entryOrder.id,
              client_order_id: entryClientOrderId,
              type: 'ENTRY',
              order_type: 'LIMIT',
              price: adjustedEntryPrice,
              qty: adjustedEntryQty,
              status: entryOrder.status || 'NEW',
              submitted_at: new Date().toISOString()
            });
            
            log(LogLevel.INFO, `Entry order placed: ${entryOrder.id}`);
          } catch (error: any) {
            errors.push(`Entry order failed: ${error.message}`);
            return {
              content: [{
                type: 'text',
                text: JSON.stringify({
                  success: false,
                  errors,
                  orders_submitted: submittedOrders
                }, null, 2)
              }],
              isError: true
            };
          }
          
          // Place SL order
          const slClientOrderId = generateClientOrderId('sl');
          const slParams: any = {
            stopPrice: roundPriceToTick(sl.stopPrice, exchangeInfo.tickSize, slSide),
            reduceOnly: sl.reduceOnly,
            clientOrderId: slClientOrderId
          };
          
          if (positionSide !== 'BOTH') {
            slParams.positionSide = positionSide;
          }
          
          if (sl.price && sl.type === 'STOP_LIMIT') {
            slParams.price = roundPriceToTick(sl.price, exchangeInfo.tickSize, slSide);
          }
          
          try {
            const slOrderType = sl.type === 'STOP_MARKET' ? 'stop_market' : 
                               sl.type === 'STOP_LIMIT' ? 'stop' : 'stop';
            
            const slOrder = await exchange.createOrder(
              ccxtSymbol,
              slOrderType,
              slSide.toLowerCase(),
              adjustedEntryQty,
              sl.price ? slParams.price : undefined,
              slParams
            );
            
            submittedOrders.push({
              order_id: slOrder.id,
              client_order_id: slClientOrderId,
              type: 'SL',
              order_type: sl.type,
              stop_price: slParams.stopPrice,
              price: slParams.price,
              qty: adjustedEntryQty,
              status: slOrder.status || 'NEW',
              submitted_at: new Date().toISOString()
            });
            
            log(LogLevel.INFO, `SL order placed: ${slOrder.id}`);
          } catch (error: any) {
            errors.push(`SL order failed: ${error.message}`);
            // Rollback: cancel entry order
            if (entryOrderId) {
              try {
                await exchange.cancelOrder(entryOrderId, ccxtSymbol);
                errors.push('Rolled back entry order due to SL failure');
              } catch (cancelError: any) {
                errors.push(`Failed to rollback entry order: ${cancelError.message}`);
              }
            }
            return {
              content: [{
                type: 'text',
                text: JSON.stringify({
                  success: false,
                  errors,
                  orders_submitted: submittedOrders
                }, null, 2)
              }],
              isError: true
            };
          }
          
          // Place TP orders
          for (let i = 0; i < validatedTps.length; i++) {
            const tp = validatedTps[i];
            const tpClientOrderId = generateClientOrderId(`tp${i + 1}`);
            const tpParams: any = {
              reduceOnly: true,
              postOnly: tps[i].postOnly,
              clientOrderId: tpClientOrderId
            };
            
            if (positionSide !== 'BOTH') {
              tpParams.positionSide = positionSide;
            }
            
            try {
              const tpOrder = await exchange.createOrder(
                ccxtSymbol,
                'limit',
                slSide.toLowerCase(),
                tp.qty,
                tp.price,
                tpParams
              );
              
              submittedOrders.push({
                order_id: tpOrder.id,
                client_order_id: tpClientOrderId,
                type: 'TP',
                order_type: 'LIMIT',
                price: tp.price,
                qty: tp.qty,
                status: tpOrder.status || 'NEW',
                submitted_at: new Date().toISOString()
              });
              
              log(LogLevel.INFO, `TP order ${i + 1} placed: ${tpOrder.id}`);
            } catch (error: any) {
              errors.push(`TP order ${i + 1} failed: ${error.message}`);
            }
          }
          
          // Set up entry TTL if specified
          if (entry_ttl_sec && entryOrderId) {
            setTimeout(async () => {
              try {
                const order = await exchange.fetchOrder(entryOrderId!, ccxtSymbol);
                if (order.status === 'open') {
                  await exchange.cancelOrder(entryOrderId!, ccxtSymbol);
                  log(LogLevel.INFO, `Entry order ${entryOrderId} cancelled after TTL`);
                }
              } catch (error) {
                log(LogLevel.WARNING, `Failed to cancel entry order after TTL: ${error}`);
              }
            }, entry_ttl_sec * 1000);
          }
          
          const result = {
            success: errors.length === 0,
            symbol: validSymbol,
            orders_submitted: submittedOrders,
            errors: errors.length > 0 ? errors : undefined,
            warnings: entryValidation.warnings.length > 0 ? entryValidation.warnings : undefined,
            entry_ttl_active: entry_ttl_sec ? `Will auto-cancel in ${entry_ttl_sec}s if unfilled` : undefined
          };
          
          return {
            content: [{
              type: 'text',
              text: JSON.stringify(result, null, 2)
            }]
          };
        });
      } catch (error) {
        log(LogLevel.ERROR, `Error placing bracket orders: ${error}`);
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              success: false,
              errors: [...errors, error instanceof Error ? error.message : String(error)],
              orders_submitted: submittedOrders
            }, null, 2)
          }],
          isError: true
        };
      }
    }
  );

  /**
   * Tool 8: amend_order
   * Amend an existing order (price and/or quantity)
   * 
   * 工具8：修改订单
   * 修改现有订单的价格和/或数量
   */
  server.tool(
    'amend_order',
    'Amend an existing order by changing price and/or quantity. Uses editOrder if available, otherwise cancel+recreate',
    {
      symbol: futuresSymbolSchema,
      orderId: z.string().optional().describe('Order ID to amend'),
      origClientOrderId: z.string().optional().describe('Original client order ID'),
      newPrice: z.number().positive().describe('New order price'),
      newQty: z.number().positive().describe('New order quantity'),
      allow_requote: z.boolean().default(false)
        .describe('If false, only allows cancel+recreate with new clientOrderId (prevents chasing)'),
      newClientOrderId: z.string().optional()
        .describe('Required if allow_requote=false for cancel+recreate'),
      ...credentialsSchema
    },
    async ({ symbol, orderId, origClientOrderId, newPrice, newQty, allow_requote, newClientOrderId, apiKey, secret }) => {
      try {
        const validSymbol = validateFuturesSymbol(symbol);
        const ccxtSymbol = toCcxtSymbol(validSymbol);
        
        if (!orderId && !origClientOrderId) {
          return {
            content: [{
              type: 'text',
              text: JSON.stringify({
                success: false,
                error: 'Either orderId or origClientOrderId is required'
              }, null, 2)
            }],
            isError: true
          };
        }
        
        if (!allow_requote && !newClientOrderId) {
          return {
            content: [{
              type: 'text',
              text: JSON.stringify({
                success: false,
                error: 'newClientOrderId is required when allow_requote=false'
              }, null, 2)
            }],
            isError: true
          };
        }
        
        return await rateLimiter.execute('binanceusdm', async () => {
          const exchange = getBinanceFutures(apiKey, secret);
          await exchange.loadMarkets();
          
          // Get exchange info for validation
          const market = exchange.market(ccxtSymbol);
          const exchangeInfo = parseExchangeInfoFromMarket(market);
          
          // Fetch the original order
          let originalOrder: ccxt.Order;
          try {
            if (orderId) {
              originalOrder = await exchange.fetchOrder(orderId, ccxtSymbol);
            } else {
              // Fetch by client order id
              const openOrders = await exchange.fetchOpenOrders(ccxtSymbol);
              const found = openOrders.find((o: any) => o.clientOrderId === origClientOrderId);
              if (!found) {
                throw new Error(`Order with clientOrderId ${origClientOrderId} not found`);
              }
              originalOrder = found;
            }
          } catch (error: any) {
            return {
              content: [{
                type: 'text',
                text: JSON.stringify({
                  success: false,
                  error: `Failed to fetch original order: ${error.message}`
                }, null, 2)
              }],
              isError: true
            };
          }
          
          // Validate new parameters
          const side = originalOrder.side?.toUpperCase() as 'BUY' | 'SELL';
          const validation = validateOrderParams(newPrice, newQty, side, exchangeInfo);
          
          if (!validation.valid) {
            return {
              content: [{
                type: 'text',
                text: JSON.stringify({
                  success: false,
                  errors: validation.errors,
                  warnings: validation.warnings
                }, null, 2)
              }],
              isError: true
            };
          }
          
          const adjustedPrice = validation.adjusted.price || newPrice;
          const adjustedQty = validation.adjusted.qty || newQty;
          
          log(LogLevel.INFO, `Amending order ${originalOrder.id} to price=${adjustedPrice}, qty=${adjustedQty}`);
          
          // Try editOrder first
          let result: any;
          let method = 'editOrder';
          
          try {
            if (typeof exchange.editOrder === 'function') {
              result = await exchange.editOrder(
                originalOrder.id,
                ccxtSymbol,
                originalOrder.type,
                side.toLowerCase(),
                adjustedQty,
                adjustedPrice
              );
            } else {
              throw new Error('editOrder not supported');
            }
          } catch (editError: any) {
            log(LogLevel.INFO, `editOrder failed, falling back to cancel+recreate: ${editError.message}`);
            method = 'cancel_recreate';
            
            // Cancel the original order
            try {
              await exchange.cancelOrder(originalOrder.id, ccxtSymbol);
            } catch (cancelError: any) {
              return {
                content: [{
                  type: 'text',
                  text: JSON.stringify({
                    success: false,
                    error: `Failed to cancel original order: ${cancelError.message}`
                  }, null, 2)
                }],
                isError: true
              };
            }
            
            // Create new order
            const newOrderParams: any = {};
            if (newClientOrderId) {
              newOrderParams.clientOrderId = newClientOrderId;
            } else if (allow_requote) {
              newOrderParams.clientOrderId = generateClientOrderId('amend');
            }
            
            // Copy original order parameters
            if ((originalOrder as any).reduceOnly) {
              newOrderParams.reduceOnly = true;
            }
            if ((originalOrder as any).positionSide) {
              newOrderParams.positionSide = (originalOrder as any).positionSide;
            }
            if ((originalOrder as any).stopPrice) {
              newOrderParams.stopPrice = (originalOrder as any).stopPrice;
            }
            
            try {
              result = await exchange.createOrder(
                ccxtSymbol,
                originalOrder.type || 'limit',
                side.toLowerCase(),
                adjustedQty,
                adjustedPrice,
                newOrderParams
              );
            } catch (createError: any) {
              return {
                content: [{
                  type: 'text',
                  text: JSON.stringify({
                    success: false,
                    error: `Order cancelled but failed to create new order: ${createError.message}`,
                    cancelled_order_id: originalOrder.id
                  }, null, 2)
                }],
                isError: true
              };
            }
          }
          
          return {
            content: [{
              type: 'text',
              text: JSON.stringify({
                success: true,
                symbol: validSymbol,
                method,
                original_order_id: originalOrder.id,
                new_order: {
                  id: result.id,
                  clientOrderId: result.clientOrderId,
                  price: adjustedPrice,
                  qty: adjustedQty,
                  status: result.status
                },
                warnings: validation.warnings.length > 0 ? validation.warnings : undefined
              }, null, 2)
            }]
          };
        });
      } catch (error) {
        log(LogLevel.ERROR, `Error amending order: ${error}`);
        return {
          content: [{
            type: 'text',
            text: `Error: ${error instanceof Error ? error.message : String(error)}`
          }],
          isError: true
        };
      }
    }
  );

  // ============================================================================
  // E. Backtesting & Self-Calibration Tools
  // E. 复盘与自校准工具
  // ============================================================================

  /**
   * Tool 9: log_trade_plan_snapshot
   * Log a trade plan and its outcome for backtesting
   * 
   * 工具9：记录交易计划快照
   * 记录交易计划及其结果用于复盘
   */
  server.tool(
    'log_trade_plan_snapshot',
    'Log a trade plan snapshot with inputs, orders, fills, and outcome for later analysis',
    {
      plan_id: z.string().describe('Unique trade plan ID'),
      template_id: z.string().describe('Template/strategy ID used'),
      session: z.string().describe('Trading session (e.g., "ASIA", "LONDON", "NY")'),
      v_regime: z.string().describe('Volatility regime (e.g., "LOW", "MEDIUM", "HIGH")'),
      symbol: futuresSymbolSchema,
      side: z.enum(['LONG', 'SHORT']).describe('Position side'),
      inputs_summary: z.object({
        entry_price: z.number(),
        sl_price: z.number(),
        tp_prices: z.array(z.number()),
        qty: z.number(),
        leverage: z.number(),
        risk_amount: z.number().optional()
      }),
      orders_submitted: z.array(z.object({
        order_id: z.string(),
        client_order_id: z.string().optional(),
        type: z.enum(['ENTRY', 'SL', 'TP']),
        order_type: z.string(),
        price: z.number().optional(),
        stop_price: z.number().optional(),
        qty: z.number(),
        status: z.string(),
        submitted_at: z.string()
      })),
      fills: z.array(z.object({
        order_id: z.string(),
        type: z.enum(['ENTRY', 'SL', 'TP']),
        filled_price: z.number(),
        filled_qty: z.number(),
        commission: z.number(),
        commission_asset: z.string(),
        filled_at: z.string(),
        slippage: z.number().optional()
      })),
      outcome: z.object({
        status: z.enum(['PENDING', 'FILLED', 'PARTIAL', 'CANCELLED', 'STOPPED_OUT', 'TP_HIT', 'MANUAL_CLOSE']),
        pnl: z.number().optional(),
        pnl_percent: z.number().optional(),
        rr_realized: z.number().optional(),
        mae: z.number().optional(),
        mfe: z.number().optional(),
        hold_time_seconds: z.number().optional(),
        exit_reason: z.string().optional()
      })
    },
    async ({ plan_id, template_id, session, v_regime, symbol, side, inputs_summary, orders_submitted, fills, outcome }) => {
      try {
        const validSymbol = validateFuturesSymbol(symbol);
        
        const snapshot = logTradePlanSnapshot(
          plan_id,
          template_id,
          session,
          v_regime,
          validSymbol,
          side,
          inputs_summary as TradePlanSnapshot['inputs_summary'],
          orders_submitted as OrderSubmitted[],
          fills as OrderFill[],
          outcome as TradeOutcome
        );
        
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              success: true,
              message: 'Trade plan snapshot logged successfully',
              plan_id: snapshot.plan_id,
              created_at: snapshot.created_at
            }, null, 2)
          }]
        };
      } catch (error) {
        log(LogLevel.ERROR, `Error logging trade plan: ${error}`);
        return {
          content: [{
            type: 'text',
            text: `Error: ${error instanceof Error ? error.message : String(error)}`
          }],
          isError: true
        };
      }
    }
  );

  /**
   * Tool 10: get_template_stats
   * Get statistics for a template to help calibrate P_base and RR_min
   * 
   * 工具10：获取模板统计
   * 获取模板的统计数据以帮助校准P_base和RR_min
   */
  server.tool(
    'get_template_stats',
    'Get performance statistics for a trading template including winrate, avg_rr, p50/p90_rr, avg_MAE/MFE, fill_rate, avg_time_to_fill, stop_slippage_p95, and suggested P_base/RR_min ranges',
    {
      template_id: z.string().describe('Template/strategy ID'),
      session: z.string().optional().describe('Filter by trading session'),
      v_regime: z.string().optional().describe('Filter by volatility regime'),
      symbol: futuresSymbolSchema.optional()
    },
    async ({ template_id, session, v_regime, symbol }) => {
      try {
        let validSymbol: string | undefined;
        if (symbol) {
          validSymbol = validateFuturesSymbol(symbol);
        }
        
        const stats = getTemplateStatsFromStorage(template_id, session, v_regime, validSymbol);
        
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              ...stats,
              interpretation: {
                winrate_quality: stats.winrate >= 0.5 ? 'GOOD' : 'NEEDS_IMPROVEMENT',
                sample_size_quality: stats.sample_size >= 30 ? 'SUFFICIENT' : 
                                     stats.sample_size >= 10 ? 'LIMITED' : 'INSUFFICIENT',
                fill_rate_quality: stats.fill_rate >= 0.7 ? 'GOOD' : 'CHECK_ENTRY_LEVELS',
                slippage_quality: stats.stop_slippage_p95 <= 0.1 ? 'GOOD' : 
                                  stats.stop_slippage_p95 <= 0.3 ? 'ACCEPTABLE' : 'HIGH'
              }
            }, null, 2)
          }]
        };
      } catch (error) {
        log(LogLevel.ERROR, `Error getting template stats: ${error}`);
        return {
          content: [{
            type: 'text',
            text: `Error: ${error instanceof Error ? error.message : String(error)}`
          }],
          isError: true
        };
      }
    }
  );

  // ============================================================================
  // Bonus: Helper tools
  // 额外：辅助工具
  // ============================================================================

  /**
   * round_price_to_tick helper tool
   * 价格取整辅助工具
   */
  server.tool(
    'round_price_to_tick',
    'Round a price to the nearest tick size for a symbol (conservative direction based on order side)',
    {
      symbol: futuresSymbolSchema,
      price: z.number().positive().describe('Price to round'),
      side: z.enum(['BUY', 'SELL']).describe('Order side for conservative rounding direction')
    },
    async ({ symbol, price, side }) => {
      try {
        const validSymbol = validateFuturesSymbol(symbol);
        const ccxtSymbol = toCcxtSymbol(validSymbol);
        
        // Get exchange info
        const exchange = new (ccxt as any).binanceusdm({
          enableRateLimit: true,
          options: { defaultType: 'swap' }
        });
        await exchange.loadMarkets();
        const market = exchange.market(ccxtSymbol);
        const exchangeInfo = parseExchangeInfoFromMarket(market);
        
        const roundedPrice = roundPriceToTick(price, exchangeInfo.tickSize, side);
        
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              symbol: validSymbol,
              original_price: price,
              rounded_price: roundedPrice,
              tick_size: exchangeInfo.tickSize,
              side,
              direction: side === 'BUY' ? 'rounded_down' : 'rounded_up'
            }, null, 2)
          }]
        };
      } catch (error) {
        return {
          content: [{
            type: 'text',
            text: `Error: ${error instanceof Error ? error.message : String(error)}`
          }],
          isError: true
        };
      }
    }
  );

  /**
   * round_qty_to_step helper tool
   * 数量取整辅助工具
   */
  server.tool(
    'round_qty_to_step',
    'Round a quantity to the nearest step size for a symbol (always rounds down for safety)',
    {
      symbol: futuresSymbolSchema,
      qty: z.number().positive().describe('Quantity to round')
    },
    async ({ symbol, qty }) => {
      try {
        const validSymbol = validateFuturesSymbol(symbol);
        const ccxtSymbol = toCcxtSymbol(validSymbol);
        
        // Get exchange info
        const exchange = new (ccxt as any).binanceusdm({
          enableRateLimit: true,
          options: { defaultType: 'swap' }
        });
        await exchange.loadMarkets();
        const market = exchange.market(ccxtSymbol);
        const exchangeInfo = parseExchangeInfoFromMarket(market);
        
        const roundedQty = roundQtyToStep(qty, exchangeInfo.stepSize);
        
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              symbol: validSymbol,
              original_qty: qty,
              rounded_qty: roundedQty,
              step_size: exchangeInfo.stepSize,
              direction: 'rounded_down'
            }, null, 2)
          }]
        };
      } catch (error) {
        return {
          content: [{
            type: 'text',
            text: `Error: ${error instanceof Error ? error.message : String(error)}`
          }],
          isError: true
        };
      }
    }
  );

  /**
   * validate_order_params helper tool
   * 订单参数校验辅助工具
   */
  server.tool(
    'validate_order_params',
    'Validate order parameters against exchange rules and get adjusted values',
    {
      symbol: futuresSymbolSchema,
      price: z.number().positive().describe('Order price'),
      qty: z.number().positive().describe('Order quantity'),
      side: z.enum(['BUY', 'SELL']).describe('Order side')
    },
    async ({ symbol, price, qty, side }) => {
      try {
        const validSymbol = validateFuturesSymbol(symbol);
        const ccxtSymbol = toCcxtSymbol(validSymbol);
        
        // Get exchange info
        const exchange = new (ccxt as any).binanceusdm({
          enableRateLimit: true,
          options: { defaultType: 'swap' }
        });
        await exchange.loadMarkets();
        const market = exchange.market(ccxtSymbol);
        const exchangeInfo = parseExchangeInfoFromMarket(market);
        
        const validation = validateOrderParams(price, qty, side, exchangeInfo);
        
        return {
          content: [{
            type: 'text',
            text: JSON.stringify({
              symbol: validSymbol,
              input: { price, qty, side },
              validation,
              exchange_info: exchangeInfo
            }, null, 2)
          }]
        };
      } catch (error) {
        return {
          content: [{
            type: 'text',
            text: `Error: ${error instanceof Error ? error.message : String(error)}`
          }],
          isError: true
        };
      }
    }
  );

  log(LogLevel.INFO, 'Binance Futures risk and order tools registered');
}
