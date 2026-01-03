# MCP Server CCXT v1.3.1 修复说明

## 问题诊断与修复

基于您提供的日志和测试报告，已修复以下问题：

### 1. 速率限制过于激进

**问题**: Circuit breaker 触发过快，导致工具在短时间内频繁被阻塞。

**修复**:
- 减少 circuit breaker 基础冷却时间从 5s 到 3s
- 减少最大 jitter 从 10s 到 5s（总冷却时间 3-8s）
- 增加每主机并发数从 2 到 3
- 增加默认超时从 5s 到 8s
- 增加基础重试延迟从 300ms 到 500ms

### 2. 缓存失败结果导致持续失败

**问题**: 当 API 返回 429 时，空结果被缓存，导致后续调用返回缓存的空数据。

**受影响的工具**:
- `trade_activity_proxy_binance` 
- `orderbook_ws_qos_diagnostics`
- `volatility_regime_fallback_binance`

**修复**: 这些工具现在不再缓存失败的结果，每次调用都直接请求 API。

### 3. 新增速率限制重置工具

新增 `mcp_ext-reset_rate_limiter_a9YOaP` 工具，用于手动重置速率限制冷却：

```json
{
  "host": "fapi.binance.com"  // 可选，不提供则重置所有
}
```

### 4. depth_levels=20 导致 "40 is not valid depth limit" 错误

**说明**: 这个错误来自 `mcp_rou-microstructure_snapshot_a9YOaP` 工具，这是另一个 MCP 服务（mcp_rou）的工具，不在本项目代码中。

Binance API 的有效 depth 值为: 5, 10, 20, 50, 100, 500, 1000

建议使用 `depth_levels=50` 代替 `depth_levels=20`。

## 更新后的配置参数

| 参数 | 旧值 | 新值 |
|------|------|------|
| DEFAULT_TIMEOUT_MS | 5000 | 8000 |
| DEFAULT_BASE_DELAY_MS | 300 | 500 |
| MAX_DELAY_MS | 2000 | 3000 |
| CIRCUIT_BREAKER_COOLDOWN_MS | 5000 | 3000 |
| CIRCUIT_BREAKER_MAX_JITTER_MS | 10000 | 5000 |
| MAX_CONCURRENT_PER_HOST | 2 | 3 |

## 部署命令

```bash
# 1. 停止服务
sudo systemctl stop mcp-server-ccxt

# 2. 重新构建
cd /root/mcp-server-ccxt
npm run build

# 3. 重启服务
sudo systemctl start mcp-server-ccxt

# 4. 查看状态
sudo systemctl status mcp-server-ccxt

# 5. 查看日志
sudo journalctl -u mcp-server-ccxt -f
```

## 验证修复

1. **测试速率限制重置**:
   调用 `mcp_ext-reset_rate_limiter_a9YOaP` 工具重置冷却

2. **测试 trade_activity_proxy**:
   ```json
   {
     "symbol": "ETHUSDT",
     "lookback_sec": 120
   }
   ```

3. **测试 volatility_regime_fallback**:
   ```json
   {
     "symbol": "ETHUSDT",
     "interval": "1m",
     "limit": 80
   }
   ```

4. **检查速率限制状态**:
   ```json
   // mcp_ext-rate_limit_qos_state_a9YOaP
   {
     "window_sec": 120
   }
   ```

## 注意事项

1. 如果遇到持续的 429 错误，可以调用 `mcp_ext-reset_rate_limiter_a9YOaP` 手动重置
2. 建议在调用多个数据源工具时，保持适当间隔（500ms+）
3. 对于 `microstructure_snapshot` 工具，使用 `depth_levels=50` 而非 20
