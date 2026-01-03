/**
 * HTTP Client Module
 * Robust HTTP wrapper with timeout, retry, exponential backoff, and rate limiting
 * 
 * HTTP客户端模块
 * 带有超时、重试、指数退避和限流的健壮HTTP封装
 */

import { log, LogLevel } from '../utils/logging.js';

// Default configuration
const DEFAULT_TIMEOUT_MS = 5000;  // Increased from 1200ms to 5000ms
const DEFAULT_MAX_RETRIES = 2;
const DEFAULT_BASE_DELAY_MS = 300;
const MAX_DELAY_MS = 2000;
const CIRCUIT_BREAKER_COOLDOWN_MS = 5000; // 5-15s jitter
const MAX_CONCURRENT_PER_HOST = 2;

/**
 * HTTP request options
 */
export interface HttpRequestOptions {
  timeout?: number;
  retries?: number;
  headers?: Record<string, string>;
  skipRetryOn429?: boolean; // Don't retry on 429 (trigger circuit breaker instead)
}

/**
 * HTTP response wrapper
 */
export interface HttpResponse<T = any> {
  success: boolean;
  data?: T;
  error?: string;
  status?: number;
  headers?: Record<string, string>;
  cached?: boolean;
  cachedAt?: number;
  latencyMs?: number;
}

/**
 * Host statistics for rate limiting and circuit breaking
 */
interface HostStats {
  requestCount: number;
  error429Count: number;
  error5xxCount: number;
  cooldownUntil: number;
  activeRequests: number;
  lastRequestTime: number;
  cacheHits: number;
  cacheMisses: number;
}

/**
 * Global host statistics
 */
const hostStats: Map<string, HostStats> = new Map();

/**
 * Request semaphore for per-host concurrency control
 */
const hostSemaphores: Map<string, Promise<void>[]> = new Map();

/**
 * Get or create host stats
 */
function getHostStats(host: string): HostStats {
  let stats = hostStats.get(host);
  if (!stats) {
    stats = {
      requestCount: 0,
      error429Count: 0,
      error5xxCount: 0,
      cooldownUntil: 0,
      activeRequests: 0,
      lastRequestTime: 0,
      cacheHits: 0,
      cacheMisses: 0
    };
    hostStats.set(host, stats);
  }
  return stats;
}

/**
 * Extract host from URL
 */
function extractHost(url: string): string {
  try {
    const parsed = new URL(url);
    return parsed.host;
  } catch {
    return url;
  }
}

/**
 * Calculate exponential backoff delay with jitter
 */
function calculateBackoffDelay(attempt: number, baseDelay: number = DEFAULT_BASE_DELAY_MS): number {
  const exponentialDelay = Math.min(baseDelay * Math.pow(2, attempt), MAX_DELAY_MS);
  const jitter = Math.random() * exponentialDelay * 0.3; // 30% jitter
  return exponentialDelay + jitter;
}

/**
 * Wait for semaphore slot (per-host concurrency control)
 */
async function acquireSemaphore(host: string): Promise<void> {
  const semaphores = hostSemaphores.get(host) || [];
  
  while (semaphores.length >= MAX_CONCURRENT_PER_HOST) {
    // Wait for any request to complete
    await Promise.race(semaphores);
    // Remove completed promises
    const current = hostSemaphores.get(host) || [];
    hostSemaphores.set(host, current.filter(p => semaphores.includes(p)));
  }
}

/**
 * Register a pending request in semaphore
 */
function registerRequest(host: string, promise: Promise<void>): void {
  const semaphores = hostSemaphores.get(host) || [];
  semaphores.push(promise);
  hostSemaphores.set(host, semaphores);
}

/**
 * Remove request from semaphore
 */
function releaseRequest(host: string, promise: Promise<void>): void {
  const semaphores = hostSemaphores.get(host) || [];
  hostSemaphores.set(host, semaphores.filter(p => p !== promise));
}

/**
 * Check if host is in circuit breaker cooldown
 */
function isInCooldown(host: string): boolean {
  const stats = getHostStats(host);
  return Date.now() < stats.cooldownUntil;
}

/**
 * Trigger circuit breaker for a host
 */
function triggerCircuitBreaker(host: string): void {
  const stats = getHostStats(host);
  const jitter = Math.random() * 10000; // 0-10s jitter
  stats.cooldownUntil = Date.now() + CIRCUIT_BREAKER_COOLDOWN_MS + jitter;
  log(LogLevel.WARNING, `Circuit breaker triggered for ${host}, cooldown until ${new Date(stats.cooldownUntil).toISOString()}`);
}

/**
 * Make HTTP GET request with retry and circuit breaker
 */
export async function httpGet<T = any>(
  url: string,
  options: HttpRequestOptions = {}
): Promise<HttpResponse<T>> {
  const {
    timeout = DEFAULT_TIMEOUT_MS,
    retries = DEFAULT_MAX_RETRIES,
    headers = {},
    skipRetryOn429 = true
  } = options;
  
  const host = extractHost(url);
  const stats = getHostStats(host);
  const startTime = Date.now();
  
  // Check circuit breaker
  if (isInCooldown(host)) {
    const cooldownRemaining = stats.cooldownUntil - Date.now();
    return {
      success: false,
      error: `Host ${host} is in circuit breaker cooldown (${Math.ceil(cooldownRemaining / 1000)}s remaining)`,
      status: 429
    };
  }
  
  // Wait for semaphore
  await acquireSemaphore(host);
  
  let lastError: string | undefined;
  let lastStatus: number | undefined;
  
  // Create a promise for tracking this request
  let resolveRequest: () => void;
  const requestPromise = new Promise<void>(resolve => {
    resolveRequest = resolve;
  });
  registerRequest(host, requestPromise);
  
  try {
    for (let attempt = 0; attempt <= retries; attempt++) {
      // Apply backoff delay for retries
      if (attempt > 0) {
        const delay = calculateBackoffDelay(attempt);
        log(LogLevel.DEBUG, `Retry ${attempt} for ${url}, waiting ${delay.toFixed(0)}ms`);
        await new Promise(r => setTimeout(r, delay));
      }
      
      stats.requestCount++;
      stats.activeRequests++;
      stats.lastRequestTime = Date.now();
      
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), timeout);
        
        const response = await fetch(url, {
          method: 'GET',
          headers: {
            'Accept': 'application/json',
            'User-Agent': 'MCP-Data-Source-Tool/1.0',
            ...headers
          },
          signal: controller.signal
        });
        
        clearTimeout(timeoutId);
        stats.activeRequests--;
        
        // Extract response headers
        const responseHeaders: Record<string, string> = {};
        response.headers.forEach((value, key) => {
          responseHeaders[key.toLowerCase()] = value;
        });
        
        // Handle rate limiting (429)
        if (response.status === 429 || response.status === 418) {
          stats.error429Count++;
          lastStatus = response.status;
          lastError = `Rate limited (${response.status})`;
          
          if (skipRetryOn429) {
            triggerCircuitBreaker(host);
            return {
              success: false,
              error: lastError,
              status: response.status,
              headers: responseHeaders,
              latencyMs: Date.now() - startTime
            };
          }
          continue;
        }
        
        // Handle server errors (5xx) - retry
        if (response.status >= 500) {
          stats.error5xxCount++;
          lastStatus = response.status;
          lastError = `Server error (${response.status})`;
          continue;
        }
        
        // Handle client errors (4xx except 429) - don't retry
        if (response.status >= 400) {
          lastStatus = response.status;
          const text = await response.text();
          return {
            success: false,
            error: `HTTP ${response.status}: ${text.substring(0, 200)}`,
            status: response.status,
            headers: responseHeaders,
            latencyMs: Date.now() - startTime
          };
        }
        
        // Success
        const data = await response.json() as T;
        stats.cacheMisses++;
        
        return {
          success: true,
          data,
          status: response.status,
          headers: responseHeaders,
          latencyMs: Date.now() - startTime
        };
        
      } catch (error: any) {
        stats.activeRequests = Math.max(0, stats.activeRequests - 1);
        
        if (error.name === 'AbortError') {
          lastError = `Request timeout after ${timeout}ms`;
        } else if (error.code === 'ENOTFOUND' || error.code === 'EAI_AGAIN') {
          lastError = `DNS resolution failed for ${host}`;
        } else if (error.code === 'ECONNREFUSED') {
          lastError = `Connection refused by ${host}`;
        } else if (error.code === 'ETIMEDOUT' || error.code === 'ESOCKETTIMEDOUT') {
          lastError = `Connection timeout to ${host}`;
        } else if (error.cause) {
          // Node.js fetch wraps errors in cause
          lastError = `Network error: ${error.cause.message || error.cause.code || 'Unknown'}`;
        } else {
          lastError = error.message || String(error);
        }
        lastStatus = 0;
        
        log(LogLevel.DEBUG, `HTTP request failed: ${url} - ${lastError}`);
        
        // Don't retry on abort or DNS errors
        if (error.name === 'AbortError' && attempt === retries) {
          break;
        }
        if (error.code === 'ENOTFOUND' || error.code === 'EAI_AGAIN') {
          break; // DNS errors won't resolve with retry
        }
      }
    }
    
    // All retries exhausted
    return {
      success: false,
      error: lastError || 'Request failed after retries',
      status: lastStatus,
      latencyMs: Date.now() - startTime
    };
    
  } finally {
    resolveRequest!();
    releaseRequest(host, requestPromise);
  }
}

/**
 * Make multiple parallel HTTP GET requests
 */
export async function httpGetMultiple<T = any>(
  requests: Array<{ url: string; options?: HttpRequestOptions }>
): Promise<Map<string, HttpResponse<T>>> {
  const results = new Map<string, HttpResponse<T>>();
  
  const promises = requests.map(async ({ url, options }) => {
    const response = await httpGet<T>(url, options);
    results.set(url, response);
  });
  
  await Promise.all(promises);
  return results;
}

/**
 * Get host statistics for QoS monitoring
 */
export function getHostStatistics(): Map<string, HostStats> {
  return new Map(hostStats);
}

/**
 * Get statistics for a specific host
 */
export function getHostStat(host: string): HostStats | undefined {
  return hostStats.get(host);
}

/**
 * Reset host statistics (for testing)
 */
export function resetHostStats(): void {
  hostStats.clear();
  hostSemaphores.clear();
}

/**
 * Get cooldown remaining for host
 */
export function getCooldownRemaining(host: string): number {
  const stats = hostStats.get(host);
  if (!stats) return 0;
  return Math.max(0, stats.cooldownUntil - Date.now());
}

/**
 * Check if any host is experiencing issues
 */
export function hasHostIssues(host: string): boolean {
  const stats = hostStats.get(host);
  if (!stats) return false;
  return stats.error429Count > 0 || stats.error5xxCount > 0 || isInCooldown(host);
}
