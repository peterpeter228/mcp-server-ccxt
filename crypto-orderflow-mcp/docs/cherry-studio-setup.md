# Cherry Studio 配置指南

本文档说明如何在 Cherry Studio 中配置 Crypto Orderflow MCP Server。

## 前提条件

1. 确保 MCP Server 已经运行
2. 确保 Cherry Studio 可以访问服务器地址

## 配置步骤

### 方法一：SSE 连接

SSE (Server-Sent Events) 适合需要实时数据推送的场景。

1. 打开 Cherry Studio
2. 进入设置 -> MCP Servers
3. 点击 "添加服务器"
4. 填写配置：
   - **名称**: `Crypto Orderflow`
   - **类型**: `SSE`
   - **URL**: `http://localhost:8022/sse`

### 方法二：Streamable HTTP

Streamable HTTP 适合按需查询的场景，是推荐的连接方式。

1. 打开 Cherry Studio
2. 进入设置 -> MCP Servers
3. 点击 "添加服务器"
4. 填写配置：
   - **名称**: `Crypto Orderflow`
   - **类型**: `Streamable HTTP`
   - **URL**: `http://localhost:8022/mcp`

## JSON 配置示例

如果 Cherry Studio 支持 JSON 配置文件，可以使用以下格式：

```json
{
  "mcpServers": {
    "crypto-orderflow": {
      "type": "streamableHttp",
      "url": "http://localhost:8022/mcp",
      "name": "Crypto Orderflow",
      "description": "加密货币行情和订单流指标服务"
    }
  }
}
```

## 远程服务器配置

如果 MCP Server 部署在远程服务器：

```json
{
  "mcpServers": {
    "crypto-orderflow": {
      "type": "streamableHttp",
      "url": "http://your-server-ip:8022/mcp"
    }
  }
}
```

## 使用 HTTPS

如果配置了 HTTPS 反向代理：

```json
{
  "mcpServers": {
    "crypto-orderflow": {
      "type": "streamableHttp",
      "url": "https://your-domain.com/mcp"
    }
  }
}
```

## 验证连接

配置完成后，在 Cherry Studio 中：

1. 选择已配置的 MCP Server
2. 尝试调用工具，例如询问 AI：
   > "请获取 BTCUSDT 的市场快照"
3. AI 应该能够调用 `get_market_snapshot` 工具并返回结果

## 可用工具列表

配置成功后，以下工具将可用：

| 工具名称 | 功能 |
|---------|------|
| `get_market_snapshot` | 获取市场快照 |
| `get_key_levels` | 获取关键价位 (VWAP/POC/Session) |
| `get_footprint` | 获取 Footprint 数据 |
| `get_orderflow_metrics` | 获取订单流指标 |
| `get_orderbook_depth_delta` | 获取深度变化 |
| `stream_liquidations` | 获取清算事件 |

## 示例对话

配置完成后，可以与 AI 进行以下对话：

**获取市场概况：**
> 用户: 请获取 BTCUSDT 和 ETHUSDT 的当前市场状态
> 
> AI: [调用 get_market_snapshot] BTCUSDT 当前价格 43,250 USDT，24h 涨幅 2.5%...

**分析关键价位：**
> 用户: BTCUSDT 今天的重要支撑和阻力在哪里？
> 
> AI: [调用 get_key_levels] 根据今日 Volume Profile，POC 在 43,300，VAH 在 43,500...

**查看订单流：**
> 用户: 最近的买卖压力如何？
> 
> AI: [调用 get_orderflow_metrics] 过去 1 小时 CVD 为 +1,250 BTC，买方占优...

**监控清算：**
> 用户: 最近有大额清算吗？
> 
> AI: [调用 stream_liquidations] 最近 100 笔清算中，卖出清算占 55%...

## 故障排除

### 连接失败
1. 检查服务器是否运行：`curl http://localhost:8022/healthz`
2. 检查防火墙设置
3. 检查网络连接

### 工具调用超时
1. 检查服务器日志
2. 确认 Binance API 可以访问
3. 适当增加超时时间

### 数据不更新
1. 检查 WebSocket 连接状态
2. 查看 `/healthz` 端点的 websocket 状态
3. 重启服务器

## Nginx 反向代理配置

如果需要通过 Nginx 代理：

```nginx
server {
    listen 443 ssl;
    server_name your-domain.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location /mcp {
        proxy_pass http://127.0.0.1:8022/mcp;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 300s;
    }
    
    location /sse {
        proxy_pass http://127.0.0.1:8022/sse;
        proxy_http_version 1.1;
        proxy_set_header Connection '';
        proxy_buffering off;
        proxy_cache off;
        chunked_transfer_encoding off;
    }
}
```
