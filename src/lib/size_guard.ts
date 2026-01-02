/**
 * Size Guard Module
 * Ensures tool outputs stay within size limits (<=2KB)
 * 
 * 输出大小守卫模块
 * 确保工具输出保持在大小限制内（<=2KB）
 */

import { QUALITY_FLAGS } from './quality.js';

// Maximum output size in bytes
export const MAX_OUTPUT_SIZE = 2048;
export const MAX_ARRAY_ITEMS = 8;

/**
 * Trim array to max items
 */
export function trimArray<T>(arr: T[], maxItems: number = MAX_ARRAY_ITEMS): T[] {
  return arr.slice(0, maxItems);
}

/**
 * Priority levels for optional fields (lower = more important)
 */
const FIELD_PRIORITY: Record<string, number> = {
  // Required fields - never drop
  'success': 0,
  'ts_ms': 0,
  'schema_version': 0,
  'source': 0,
  'quality_flags': 0,
  
  // High priority
  'consensus': 1,
  'spot_mid': 1,
  'perp_mark': 1,
  'median_px': 1,
  'trade_count': 1,
  'vol_quote': 1,
  'vwap': 1,
  'fees': 1,
  'overall': 1,
  
  // Medium priority
  'quotes': 2,
  'venues': 2,
  'bins': 2,
  'events': 2,
  'hosts': 2,
  
  // Lower priority - can be trimmed first
  'inputs': 3,
  'rest': 3,
  'ws': 3,
  'basis': 3,
  'funding': 3,
  'next_event': 3,
};

/**
 * Get priority for a field
 */
function getFieldPriority(field: string): number {
  return FIELD_PRIORITY[field] ?? 5; // Default to low priority
}

/**
 * Drop optional fields by priority to reduce size
 */
export function dropOptionalFieldsByPriority(
  obj: Record<string, any>,
  currentSize: number,
  targetSize: number = MAX_OUTPUT_SIZE
): Record<string, any> {
  if (currentSize <= targetSize) {
    return obj;
  }
  
  const result = { ...obj };
  
  // Get fields sorted by priority (highest priority number = drop first)
  const fields = Object.keys(result)
    .filter(k => getFieldPriority(k) > 0) // Never drop priority 0 fields
    .sort((a, b) => getFieldPriority(b) - getFieldPriority(a));
  
  for (const field of fields) {
    if (JSON.stringify(result).length <= targetSize) {
      break;
    }
    
    const value = result[field];
    
    // First try trimming arrays
    if (Array.isArray(value) && value.length > 4) {
      result[field] = value.slice(0, 4);
      continue;
    }
    
    // Then drop entire fields if still too big
    if (JSON.stringify(result).length > targetSize) {
      delete result[field];
    }
  }
  
  return result;
}

/**
 * Apply size guard to output object
 * Returns the guarded object and whether trimming occurred
 */
export function applySizeGuard(
  obj: Record<string, any>
): { output: Record<string, any>; trimmed: boolean } {
  let result = { ...obj };
  let trimmed = false;
  
  // First pass: trim all arrays to MAX_ARRAY_ITEMS
  for (const key of Object.keys(result)) {
    if (Array.isArray(result[key]) && result[key].length > MAX_ARRAY_ITEMS) {
      result[key] = trimArray(result[key]);
      trimmed = true;
    }
    
    // Handle nested objects with arrays
    if (typeof result[key] === 'object' && result[key] !== null && !Array.isArray(result[key])) {
      for (const nestedKey of Object.keys(result[key])) {
        if (Array.isArray(result[key][nestedKey]) && result[key][nestedKey].length > MAX_ARRAY_ITEMS) {
          result[key][nestedKey] = trimArray(result[key][nestedKey]);
          trimmed = true;
        }
      }
    }
  }
  
  // Check size and drop optional fields if needed
  let jsonSize = JSON.stringify(result).length;
  
  if (jsonSize > MAX_OUTPUT_SIZE) {
    result = dropOptionalFieldsByPriority(result, jsonSize);
    trimmed = true;
  }
  
  // Final size check - if still too big, aggressively trim
  jsonSize = JSON.stringify(result).length;
  if (jsonSize > MAX_OUTPUT_SIZE) {
    // Truncate string values
    for (const key of Object.keys(result)) {
      if (typeof result[key] === 'string' && result[key].length > 100) {
        result[key] = result[key].substring(0, 97) + '...';
        trimmed = true;
      }
    }
  }
  
  return { output: result, trimmed };
}

/**
 * Create size-guarded response with quality flags update
 */
export function createGuardedResponse<T extends { quality_flags: string[] }>(
  data: T
): T {
  const { output, trimmed } = applySizeGuard(data as Record<string, any>);
  
  if (trimmed && !output.quality_flags?.includes(QUALITY_FLAGS.TRIMMED_OUTPUT)) {
    const flags = output.quality_flags || [];
    if (flags.length < 6) {
      flags.push(QUALITY_FLAGS.TRIMMED_OUTPUT);
      output.quality_flags = flags;
    }
  }
  
  return output as T;
}

/**
 * Get byte size of JSON stringified object
 */
export function getJsonByteSize(obj: any): number {
  return new TextEncoder().encode(JSON.stringify(obj)).length;
}

/**
 * Check if output is within size limit
 */
export function isWithinSizeLimit(obj: any, limit: number = MAX_OUTPUT_SIZE): boolean {
  return getJsonByteSize(obj) <= limit;
}
