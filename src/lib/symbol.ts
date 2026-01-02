/**
 * Symbol Normalization Module
 * Handles symbol format conversion between different exchanges
 * 
 * 交易对标准化模块
 * 处理不同交易所之间的交易对格式转换
 */

// Allowed symbols for Trading-COG-OS kernel compatibility
export const ALLOWED_SYMBOLS = ['BTCUSDT', 'ETHUSDT'] as const;
export type AllowedSymbol = typeof ALLOWED_SYMBOLS[number];

// Base asset mapping for cross-exchange queries
export const BASE_ASSET_MAP: Record<AllowedSymbol, string> = {
  'BTCUSDT': 'BTC',
  'ETHUSDT': 'ETH'
};

/**
 * Normalize any symbol input to BTCUSDT or ETHUSDT format
 * Accepts: BTC/USDT, BTC-USDT, btcusdt, BTC_USDT, etc.
 */
export function normalizeSymbol(input: string): AllowedSymbol {
  const cleaned = input
    .toUpperCase()
    .replace(/[\/\-_:\s]/g, '')
    .replace(':USDT', '')
    .replace(':USD', '');
  
  // Check for direct match
  if (ALLOWED_SYMBOLS.includes(cleaned as AllowedSymbol)) {
    return cleaned as AllowedSymbol;
  }
  
  // Try to extract base and check
  if (cleaned.includes('BTC') && (cleaned.includes('USDT') || cleaned.includes('USD'))) {
    return 'BTCUSDT';
  }
  if (cleaned.includes('ETH') && (cleaned.includes('USDT') || cleaned.includes('USD'))) {
    return 'ETHUSDT';
  }
  
  throw new Error(
    `Symbol '${input}' is not allowed. Only BTCUSDT and ETHUSDT are supported.`
  );
}

/**
 * Get base asset from normalized symbol
 */
export function getBaseAsset(symbol: AllowedSymbol): string {
  return BASE_ASSET_MAP[symbol];
}

/**
 * Symbol format mappings for different exchanges/venues
 */
export interface VenueSymbolFormat {
  venue: string;
  symbolFormat: (base: AllowedSymbol) => string;
  quoteCurrency: 'USD' | 'USDT';
}

export const VENUE_FORMATS: VenueSymbolFormat[] = [
  {
    venue: 'binance_futures',
    symbolFormat: (s) => s, // BTCUSDT
    quoteCurrency: 'USDT'
  },
  {
    venue: 'binance_spot',
    symbolFormat: (s) => s, // BTCUSDT
    quoteCurrency: 'USDT'
  },
  {
    venue: 'coinbase_spot',
    symbolFormat: (s) => getBaseAsset(s) + '-USD', // BTC-USD
    quoteCurrency: 'USD'
  },
  {
    venue: 'kraken_spot',
    symbolFormat: (s) => s === 'BTCUSDT' ? 'XBTUSD' : 'ETHUSD',
    quoteCurrency: 'USD'
  },
  {
    venue: 'okx_swap',
    symbolFormat: (s) => getBaseAsset(s) + '-USDT-SWAP', // BTC-USDT-SWAP
    quoteCurrency: 'USDT'
  },
  {
    venue: 'deribit_index',
    symbolFormat: (s) => getBaseAsset(s).toLowerCase() + '_usd', // btc_usd
    quoteCurrency: 'USD'
  }
];

/**
 * Get venue-specific symbol format
 */
export function getVenueSymbol(symbol: AllowedSymbol, venue: string): string {
  const format = VENUE_FORMATS.find(f => f.venue === venue);
  if (!format) {
    throw new Error(`Unknown venue: ${venue}`);
  }
  return format.symbolFormat(symbol);
}

/**
 * Get quote currency for a venue
 */
export function getVenueQuoteCurrency(venue: string): 'USD' | 'USDT' {
  const format = VENUE_FORMATS.find(f => f.venue === venue);
  return format?.quoteCurrency || 'USDT';
}

/**
 * Check if two venues have same quote currency
 */
export function hasSameQuoteCurrency(venue1: string, venue2: string): boolean {
  return getVenueQuoteCurrency(venue1) === getVenueQuoteCurrency(venue2);
}
