/**
 * Adaptive Rate Limiter
 * Manages API request rate with adaptive backoff and throttling
 * 
 * 自适应速率限制器
 * 使用自适应退避和节流管理API请求速率
 */
import { log, LogLevel } from './logging.js';
import PQueue from 'p-queue';

/**
 * Adaptive rate limiter that adjusts based on API responses
 * 
 * 根据API响应进行调整的自适应速率限制器
 */
export class AdaptiveRateLimiter {
  private defaultMinInterval: number;
  private defaultConcurrency: number;
  private lastResponse: Record<string, number> = {};
  private successiveErrors: Record<string, number> = {};
  private minInterval: Record<string, number> = {};
  private queues: Record<string, PQueue> = {};
  
  /**
   * Create a new rate limiter
   * @param defaultMinInterval Default minimum interval between requests (ms)
   * @param defaultConcurrency Default maximum concurrent requests
   * 
   * 创建新的速率限制器
   * @param defaultMinInterval 请求之间的默认最小间隔（毫秒）
   * @param defaultConcurrency 默认最大并发请求数
   */
  constructor(defaultMinInterval = 300, defaultConcurrency = 2) {
    this.defaultMinInterval = defaultMinInterval;
    this.defaultConcurrency = defaultConcurrency;
  }
  
  /**
   * Get or create a queue for an exchange
   * @param exchange Exchange ID
   * @returns Queue instance
   * 
   * 获取或创建交易所队列
   * @param exchange 交易所ID
   * @returns 队列实例
   */
  private getQueue(exchange: string): PQueue {
    if (!this.queues[exchange]) {
      // Create a new queue with concurrency limit
      this.queues[exchange] = new PQueue({ concurrency: this.defaultConcurrency });
      log(LogLevel.DEBUG, `Created new queue for ${exchange} with concurrency ${this.defaultConcurrency}`);
    }
    return this.queues[exchange];
  }
  
  /**
   * Execute a function with rate limiting
   * @param exchange Exchange ID
   * @param fn Function to execute
   * @returns Result of the function
   * 
   * 执行带速率限制的函数
   * @param exchange 交易所ID
   * @param fn 要执行的函数
   * @returns 函数的结果
   */
  async execute<T>(exchange: string, fn: () => Promise<T>): Promise<any> {
    const queue = this.getQueue(exchange);
    
    return queue.add(async () => {
      await this.acquirePermission(exchange);
      try {
        const result = await fn();
        this.recordSuccess(exchange);
        return result;
      } catch (error) {
        this.recordError(exchange);
        throw error;
      }
    });
  }
  
  /**
   * Wait for permission to make a request
   * @param exchange Exchange ID
   * 
   * 等待获得请求许可
   * @param exchange 交易所ID
   */
  private async acquirePermission(exchange: string): Promise<void> {
    // Apply exponential backoff for successive errors (max 5 seconds, not 30)
    const errors = this.successiveErrors[exchange] || 0;
    if (errors > 3) {
      const backoff = Math.min(5000, 500 * Math.pow(2, errors - 3));
      log(LogLevel.DEBUG, `Applying backoff for ${exchange}: ${backoff}ms (errors: ${errors})`);
      await new Promise(r => setTimeout(r, backoff));
    }
    
    // Enforce minimum interval between requests
    const lastTime = this.lastResponse[exchange] || 0;
    const elapsed = Date.now() - lastTime;
    const interval = this.minInterval[exchange] || this.defaultMinInterval;
    
    if (elapsed < interval) {
      const delay = interval - elapsed;
      log(LogLevel.DEBUG, `Rate limiting ${exchange}: waiting ${delay}ms`);
      await new Promise(r => setTimeout(r, delay));
    }
  }
  
  /**
   * Reset error count for an exchange
   * @param exchange Exchange ID
   * 
   * 重置交易所的错误计数
   */
  resetErrors(exchange: string): void {
    this.successiveErrors[exchange] = 0;
    this.minInterval[exchange] = this.defaultMinInterval;
    log(LogLevel.INFO, `Reset error count for ${exchange}`);
  }
  
  /**
   * Reset all error counts
   * 重置所有错误计数
   */
  resetAllErrors(): void {
    Object.keys(this.successiveErrors).forEach(exchange => {
      this.successiveErrors[exchange] = 0;
    });
    Object.keys(this.minInterval).forEach(exchange => {
      this.minInterval[exchange] = this.defaultMinInterval;
    });
    log(LogLevel.INFO, 'Reset all error counts');
  }
  
  /**
   * Record a successful request
   * @param exchange Exchange ID
   * 
   * 记录成功请求
   * @param exchange 交易所ID
   */
  private recordSuccess(exchange: string): void {
    this.lastResponse[exchange] = Date.now();
    // Decrease successive errors (but not below 0)
    this.successiveErrors[exchange] = Math.max(0, (this.successiveErrors[exchange] || 0) - 1);
    
    // If no errors, gradually decrease minimum interval
    if (this.successiveErrors[exchange] === 0) {
      const currentInterval = this.minInterval[exchange] || this.defaultMinInterval;
      const newInterval = Math.max(this.defaultMinInterval, currentInterval * 0.95);
      
      if (newInterval !== currentInterval) {
        this.minInterval[exchange] = newInterval;
        log(LogLevel.DEBUG, `Decreased min interval for ${exchange} to ${newInterval.toFixed(0)}ms`);
      }
    }
  }
  
  /**
   * Record a failed request and increase backoff
   * @param exchange Exchange ID
   * 
   * 记录失败请求并增加退避
   * @param exchange 交易所ID
   */
  private recordError(exchange: string): void {
    this.lastResponse[exchange] = Date.now();
    this.successiveErrors[exchange] = (this.successiveErrors[exchange] || 0) + 1;
    
    // Increase minimum interval for this exchange (max 2 seconds)
    const currentInterval = this.minInterval[exchange] || this.defaultMinInterval;
    this.minInterval[exchange] = Math.min(2000, currentInterval * 1.3);
    
    log(LogLevel.DEBUG, 
      `Recorded error for ${exchange}, successive errors: ${this.successiveErrors[exchange]}, ` +
      `new min interval: ${this.minInterval[exchange].toFixed(0)}ms`);
    
    // Lower concurrency if too many errors
    if (this.successiveErrors[exchange] > 10) {
      const queue = this.getQueue(exchange);
      if (queue.concurrency > 1) {
        queue.concurrency = queue.concurrency - 1;
        log(LogLevel.WARNING, `Reduced concurrency for ${exchange} to ${queue.concurrency}`);
      }
    }
  }
  
  /**
   * Set the minimum interval for an exchange
   * @param exchange Exchange ID
   * @param interval New minimum interval in ms
   * 
   * 设置交易所的最小间隔
   * @param exchange 交易所ID
   * @param interval 新的最小间隔（毫秒）
   */
  setMinInterval(exchange: string, interval: number): void {
    this.minInterval[exchange] = interval;
    log(LogLevel.INFO, `Set min interval for ${exchange} to ${interval}ms`);
  }
  
  /**
   * Set concurrency for a specific exchange
   * @param exchange Exchange ID
   * @param concurrency Number of concurrent requests
   * 
   * 设置特定交易所的并发度
   * @param exchange 交易所ID
   * @param concurrency 并发请求数
   */
  setConcurrency(exchange: string, concurrency: number): void {
    const queue = this.getQueue(exchange);
    queue.concurrency = concurrency;
    log(LogLevel.INFO, `Set concurrency for ${exchange} to ${concurrency}`);
  }
  
  /**
   * Get statistics for all exchange queues
   * @returns Statistics object
   * 
   * 获取所有交易所队列的统计信息
   * @returns 统计对象
   */
  getStats(): Record<string, any> {
    const stats: Record<string, any> = {};
    
    for (const exchange in this.queues) {
      const queue = this.queues[exchange];
      stats[exchange] = {
        pendingCount: queue.pending,
        concurrency: queue.concurrency,
        minInterval: this.minInterval[exchange] || this.defaultMinInterval,
        successiveErrors: this.successiveErrors[exchange] || 0
      };
    }
    
    return stats;
  }
}

// Singleton instance with faster defaults
// 单例实例，使用更快的默认值
export const rateLimiter = new AdaptiveRateLimiter(100, 5); // 100ms interval, 5 concurrent