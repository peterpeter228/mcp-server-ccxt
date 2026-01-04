# v1.3.5 修复说明 / Fix Notes

## 问题诊断 / Issue Diagnosis

### 问题 1: `get_exchange_info_futures` 返回 "no structured content" 错误
**Issue 1: `get_exchange_info_futures` returns "no structured content" error**

**错误信息 / Error Message:**
```json
{
  "isError": true,
  "content": [{
    "type": "text",
    "text": "Error calling tool get_exchange_info_futures: ... MCP error -32600: Tool get_exchange_info_futures has an output schema but did not return structured content"
  }]
}
```

**原因 / Root Cause:**
- MCP router 期望工具返回 `structuredContent` 字段（当工具有输出 schema 时）
- 我们的工具只返回了 `content` 数组（文本格式）
- MCP 协议要求在有 output schema 的情况下，必须同时返回 `structuredContent`

**修复 / Fix:**
为以下关键工具添加了 `structuredContent` 字段：
- `get_exchange_info_futures`
- `round_price_to_tick`
- `round_qty_to_step`
- `validate_order_params`

```typescript
// 修复前 / Before:
return {
  content: [{
    type: 'text',
    text: JSON.stringify(info, null, 2)
  }]
};

// 修复后 / After:
return {
  content: [{
    type: 'text',
    text: JSON.stringify(info, null, 2)
  }],
  structuredContent: info  // 新增：结构化内容
};
```

### 问题 2: WS QoS 诊断工具误报 `ws.connected=false`（v1.3.4 已修复）
**Issue 2: WS QoS diagnostics tool incorrectly reports `ws.connected=false` (Fixed in v1.3.4)**

此问题已在 v1.3.4 中修复。详见 `docs/fixes-v1.3.4.md`。

---

## 部署更新指南 / Deployment Update Guide

```bash
# 1. 停止服务
sudo systemctl stop mcp-server-ccxt

# 2. 更新代码
cd /opt/mcp-server-ccxt
git pull  # 或手动复制更新的文件

# 3. 重新构建
npm run build

# 4. 启动服务
sudo systemctl start mcp-server-ccxt

# 5. 验证
sudo systemctl status mcp-server-ccxt
journalctl -u mcp-server-ccxt -n 20
```

---

## 变更的文件 / Changed Files

1. **`src/tools/binance-futures.ts`**
   - `get_exchange_info_futures`: 添加 `structuredContent`
   - `round_price_to_tick`: 添加 `structuredContent`
   - `round_qty_to_step`: 添加 `structuredContent`
   - `validate_order_params`: 添加 `structuredContent`

2. **`package.json`**
   - 版本更新至 `1.3.5`

---

## 预期行为变化 / Expected Behavior Changes

### 修复后 / After Fix:

`get_exchange_info_futures` 将返回:

```json
{
  "content": [{
    "type": "text",
    "text": "{\n  \"symbol\": \"BTCUSDT\",\n  \"tickSize\": 0.1,\n  ...}"
  }],
  "structuredContent": {
    "symbol": "BTCUSDT",
    "tickSize": 0.1,
    "stepSize": 0.001,
    "minQty": 0.001,
    "maxQty": 1000,
    "minNotional": 100,
    "pricePrecision": 1,
    "qtyPrecision": 3,
    "maxLeverage": 125
  }
}
```

这样 MCP router 可以正确识别和使用结构化数据。

---

## 关于其他工具 / About Other Tools

用户运行结果显示以下工具正常工作：
- `mcp_rou-get_orderbook_health_a9YOaP` ✓
- `mcp_rou-get_ws_buffer_status_futures_a9YOaP` ✓
- `mcp_rou-get_server_time_a9YOaP` ✓
- `mcp_rou-mcp_ext_orderbook_ws_qos_diagnostics_a9YOaP_a9YOaP` ✓
- `mcp_rou-mcp_ext_exchange_status_aggregator_a9YOaP_a9YOaP` ✓
- `mcp_rou-mcp_ext_stablecoin_depeg_monitor_a9YOaP_a9YOaP` ✓
- `mcp_rou-validate_order_params_a9YOaP` ✓
- `mcp_rou-round_price_to_tick_a9YOaP` ✓
- 等等...

如果其他工具出现类似问题，请报告，我们将添加相同的修复。
