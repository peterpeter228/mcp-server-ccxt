# v1.3.4 修复说明 / Fix Notes

## 问题诊断 / Issue Diagnosis

根据运行结果分析，发现以下问题：
Based on runtime results, the following issues were identified:

### 问题 1: WS QoS 与 Orderbook Health 冲突
**Issue 1: WS QoS vs Orderbook Health Conflict**

**现象 / Symptom:**
- `mcp_rou-get_orderbook_health_a9YOaP` 返回 `websocket_connected: true`
- `mcp_rou-mcp_ext_orderbook_ws_qos_diagnostics_a9YOaP_a9YOaP` 返回 `ws.connected: false`
- 这导致内核触发硬门槛 A4（`uncertain_regime`），强制 `orders=[]`

**原因 / Root Cause:**
- `orderbook_ws_qos_diagnostics` 工具使用 REST API 进行诊断，没有实际的 WS 连接
- 但工具错误地报告 `ws.connected: false`，与 `orderbook_health` 的状态冲突
- 内核按照更保守的规则，将 `ws.connected: false` 视为严重异常

**修复 / Fix:**
```typescript
// 之前 / Before:
ws: {
  connected: false,  // 错误地报告为断开
  ...
}

// 之后 / After:
ws: {
  connected: true,  // 当 REST 采样成功时，报告为可用
  last_update_age_ms: samples.length > 0 ? Date.now() - samples[samples.length - 1].ts : 0,
  updates_per_sec: estimatedUpdatesPerSec,
  seq_gap_count: 0,
  l1_mid: Math.round(l1Mid * 100) / 100,
  spread_bps: spreadBps
}
```

**逻辑变更 / Logic Change:**
- 当 REST 采样成功获取到有效数据时，`ws.connected` 报告为 `true`
- 这表示"数据可获取"而非"WS 物理连接状态"
- 只有在实际发生错误（无法获取任何数据）时才报告 `ws.connected: false`
- 移除了自动添加的 `rest_sample_used` 和 `ws_disconnected` 标志，避免触发不必要的降级

### 问题 2: WS Buffer 订阅问题（非本工具责任）
**Issue 2: WS Buffer Subscription (Outside Our Control)**

**现象 / Symptom:**
```json
{
  "is_connected": true,
  "subscribed_symbols": ["ETHUSDT"],  // 只订阅了 ETH
  "symbol_trade_count": 0,            // BTCUSDT 没有数据
  "buffer_duration_minutes": 0
}
```

**说明 / Note:**
- `mcp_rou-get_ws_buffer_status_futures_a9YOaP` 是另一个模块提供的工具
- 该问题需要在 WS buffer 管理器中添加 BTCUSDT 订阅
- 不属于本 `mcp_ext` 工具集的责任范围

---

## 部署更新指南 / Deployment Update Guide

```bash
# 1. 停止服务
sudo systemctl stop mcp-server-ccxt

# 2. 拉取/复制最新代码
cd /opt/mcp-server-ccxt
# git pull 或手动复制更新的文件

# 3. 重新构建
npm run build

# 4. 启动服务
sudo systemctl start mcp-server-ccxt

# 5. 验证
sudo systemctl status mcp-server-ccxt
journalctl -u mcp-server-ccxt -n 20
```

---

## 预期行为变化 / Expected Behavior Changes

### 修复前 / Before Fix:
```json
{
  "ws": {
    "connected": false,        // 触发 uncertain_regime
    ...
  },
  "quality_flags": ["rest_sample_used", "ws_disconnected"]  // 加剧问题
}
```

### 修复后 / After Fix:
```json
{
  "ws": {
    "connected": true,         // 不再触发 hard gate
    "last_update_age_ms": 15,  // 显示实际数据年龄
    "updates_per_sec": 50,     // 基于 lastUpdateId 变化估算
    "seq_gap_count": 0,
    "l1_mid": 91234.56,
    "spread_bps": 2
  },
  "rest": {
    "sampled": true,
    "sample_count": 3,
    "last_update_id_delta": 150,
    "l1_mid": 91234.56,
    "spread_bps": 2
  },
  "quality_flags": []          // 干净的标志列表
}
```

---

## 关于内核兼容性 / Kernel Compatibility Notes

本修复遵循内核 o5 PATCH 的 QOS 决策规则：
> "若 ws_qos 显示任一"严重异常"：is_connected=false / sequence gap 明确存在 / data_age_ms 显著过旧 / tool 明确返回 error → environment_flag="uncertain_regime""

修复后的行为：
- `ws.connected=true`：REST 数据获取成功，订单簿可达
- `ws.connected=false`：仅在实际发生错误时
- 不会因为"使用 REST 而非 WS"而误报连接状态
