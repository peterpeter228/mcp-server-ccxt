# MCP Server CCXT v1.3.2 修复说明

## 问题诊断与修复

基于日志和测试报告，本版本修复以下问题：

---

## 1. `get-markets` 工具优化

### 问题
- 返回 4155+ 个市场数据，容易撑爆上下文
- 无法按条件筛选
- 输出字段过多

### 修复
新增过滤参数和精简输出：

```typescript
// 新参数
{
  exchange: string,
  marketType: "spot" | "future" | "swap" | "option" | "margin" | "all",  // 市场类型过滤
  quote: string,        // 报价币种过滤 (如 USDT, USD, BTC)
  base: string,         // 基础币种过滤 (如 ETH, BTC)
  search: string,       // 符号搜索 (如 'ETH' 匹配 ETH/USDT, ETH/BTC)
  active: boolean,      // 只返回活跃市场 (默认 true)
  page: number,         // 页码 (默认 1)
  pageSize: number      // 每页数量 (默认 20, 最大 50)
}
```

### 示例调用

```json
// 获取 Binance 上所有 USDT 报价的现货 ETH 市场
{
  "exchange": "binance",
  "marketType": "spot",
  "quote": "USDT",
  "search": "ETH"
}
```

### 输出格式（精简版）

```json
{
  "exchange": "binance",
  "filters": { "marketType": "spot", "quote": "USDT", "search": "ETH" },
  "total": 4155,      // 总市场数
  "filtered": 3,      // 过滤后数量
  "page": 1,
  "pageSize": 20,
  "totalPages": 1,
  "data": [
    {
      "symbol": "ETH/USDT",
      "base": "ETH",
      "quote": "USDT",
      "type": "spot",
      "active": true,
      "pricePrecision": 2,
      "amountPrecision": 5,
      "minAmount": 0.0001,
      "minCost": 10
    }
  ]
}
```

---

## 2. `get-leverage-tiers` 符号格式修复

### 问题
- 调用 `get-leverage-tiers` 时使用 `ETH/USDT` (现货格式) 报错：
  ```
  BadSymbol: binance fetchMarketLeverageTiers() supports contract markets only
  ```
- Binance swap 市场需要 `ETH/USDT:USDT` 格式

### 修复
- 自动将 `ETH/USDT` 转换为 `ETH/USDT:USDT`（仅限 Binance swap 市场）
- 默认 `marketType` 改为 `swap`（更常用于永续合约）

### 示例调用

```json
// 现在可以直接使用简化格式
{
  "exchange": "binance",
  "symbol": "ETH/USDT",     // 自动转换为 ETH/USDT:USDT
  "marketType": "swap"
}
```

---

## 3. `get-funding-rates` 符号格式修复

### 问题
同上，符号格式不匹配导致错误

### 修复
- 自动转换符号格式
- 输出显示原始符号和转换后符号

```json
// 示例输出
{
  "symbols": ["ETH/USDT:USDT"],    // 转换后
  "originalSymbols": ["ETH/USDT"], // 原始输入
  "marketType": "swap",
  "rates": { ... }
}
```

---

## 4. SSE 连接循环（正常行为）

### 观察
日志显示 SSE 连接每 5 分钟重新建立：
```
SSE connection closed: session_xxx
New SSE connection: session_yyy
MCP connected to SSE transport: session_yyy
```

### 说明
这是 **正常的 keep-alive 行为**，不需要修复：
- MCP SDK 的 SSE 传输有内置的连接超时
- 客户端会自动重连
- 服务器正确处理了连接关闭和重建

---

## 部署命令

```bash
# 1. 停止服务
sudo systemctl stop mcp-server-ccxt

# 2. 重新构建
cd /root/mcp-server-ccxt
npm run build

# 3. 重启服务
sudo systemctl start mcp-server-ccxt

# 4. 验证
curl http://localhost:8055/health
```

---

## 测试验证

### 1. 测试 get-markets 过滤
```json
// 只获取 Binance swap 市场的 USDT 交易对
{
  "exchange": "binance",
  "marketType": "swap",
  "quote": "USDT",
  "pageSize": 10
}
```

### 2. 测试 get-leverage-tiers
```json
// 使用简化符号格式
{
  "exchange": "binance",
  "symbol": "ETH/USDT"
}
```

### 3. 测试 get-funding-rates
```json
{
  "exchange": "binance",
  "symbols": ["ETH/USDT", "BTC/USDT"]
}
```

---

## 版本历史

- **v1.3.2**: get-markets 优化、符号格式自动转换
- **v1.3.1**: 速率限制优化、缓存问题修复
- **v1.3.0**: 数据源工具、SSE 传输修复
