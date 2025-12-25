# Crypto Orderflow MCP Server

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

一个专业的加密货币行情和订单流指标 MCP (Model Context Protocol) Server，支持 Binance USD-M 永续合约。通过 SSE 和 Streamable HTTP 提供实时数据，可与 Cherry Studio 等 AI 应用直接集成。

## ✨ 核心功能

### 📊 Key Levels (关键价位)
- **VWAP**: 今日 dVWAP + 昨日 pdVWAP
- **Volume Profile**: dPOC/dVAH/dVAL + pdPOC/pdVAH/pdVAL (70% Value Area)
- **Session Levels**: Tokyo/London/NY 会话高低点

### 📈 Orderflow (订单流)
- **Footprint Bars**: 按价位聚合的成交量 (支持 1m/5m/15m/30m/1h)
- **Delta & CVD**: 买卖差值和累计差值
- **Stacked Imbalance**: 连续失衡检测 (可配置阈值)
- **Depth Delta**: 订单簿深度变化监控

### 📉 衍生品数据
- **Funding Rate**: 当前资金费率和下次结算时间
- **Open Interest**: 当前 OI + 历史 OI
- **Liquidations**: 实时清算事件 (缓存最近 1000 条)

## 🚀 快速开始

### 环境要求
- Python 3.12+
- Ubuntu 20.04+ (推荐)

### 安装

```bash
# 克隆项目
git clone https://github.com/your-repo/crypto-orderflow-mcp.git
cd crypto-orderflow-mcp

# 创建虚拟环境
python3.12 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 复制配置文件
cp .env.example .env
```

### 配置

编辑 `.env` 文件：

```bash
# 交易对 (支持多个，逗号分隔)
SYMBOLS=BTCUSDT,ETHUSDT

# 服务器配置
HOST=0.0.0.0
PORT=8022

# 数据库路径
CACHE_DB_PATH=./data/orderflow_cache.db

# 日志级别
LOG_LEVEL=INFO
```

### 运行

```bash
# 方法 1: 使用启动脚本 (推荐)
python run.py

# 方法 2: 设置 PYTHONPATH
PYTHONPATH=. python -m src.main

# 方法 3: 使用 Docker
docker-compose -f docker/docker-compose.yml up -d
```

## 📡 API 端点

### 健康检查
```
GET /healthz
```

### MCP 端点 (Streamable HTTP)
```
POST /mcp
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "get_market_snapshot",
    "arguments": {"symbol": "BTCUSDT"}
  }
}
```

### SSE 端点
```
GET /sse
```

### REST API
```
GET /api/market/{symbol}          # 市场快照
GET /api/key-levels/{symbol}      # 关键价位
GET /api/footprint/{symbol}       # Footprint 数据
GET /api/orderflow/{symbol}       # Orderflow 指标
GET /api/depth-delta/{symbol}     # 深度变化
GET /api/liquidations/{symbol}    # 清算事件
```

## 🔧 MCP Tools

### 1. get_market_snapshot
获取市场快照，包含价格、成交量、资金费率和持仓量。

```json
{
  "name": "get_market_snapshot",
  "arguments": {"symbol": "BTCUSDT"}
}
```

**返回示例：**
```json
{
  "timestamp": 1703001234567,
  "symbol": "BTCUSDT",
  "exchange": "binance",
  "marketType": "linear perpetual",
  "price": "43250.50",
  "markPrice": "43251.23",
  "high24h": "44000.00",
  "low24h": "42500.00",
  "volume24h": "125000.50",
  "fundingRate": "0.0001",
  "openInterest": "85000.25"
}
```

### 2. get_key_levels
获取关键价位：VWAP、Volume Profile、Session 高低点。

```json
{
  "name": "get_key_levels",
  "arguments": {
    "symbol": "BTCUSDT",
    "date": "2024-01-15",
    "sessionTZ": "UTC"
  }
}
```

### 3. get_footprint
获取 Footprint 柱状图数据。

```json
{
  "name": "get_footprint",
  "arguments": {
    "symbol": "BTCUSDT",
    "timeframe": "5m",
    "startTime": 1703001234567,
    "endTime": 1703004834567
  }
}
```

### 4. get_orderflow_metrics
获取订单流指标：Delta、CVD、Imbalance。

```json
{
  "name": "get_orderflow_metrics",
  "arguments": {
    "symbol": "BTCUSDT",
    "timeframe": "1m"
  }
}
```

### 5. get_orderbook_depth_delta
获取订单簿深度变化。

```json
{
  "name": "get_orderbook_depth_delta",
  "arguments": {
    "symbol": "BTCUSDT",
    "percent": 1.0,
    "windowSec": 5,
    "lookback": 100
  }
}
```

### 6. stream_liquidations
获取最近清算事件。

```json
{
  "name": "stream_liquidations",
  "arguments": {
    "symbol": "BTCUSDT",
    "limit": 100
  }
}
```

## 🎯 Cherry Studio 配置

### SSE 方式
1. 打开 Cherry Studio 设置
2. 添加新的 MCP Server
3. 类型选择：`SSE`
4. URL 填写：`http://your-server:8022/sse`

### Streamable HTTP 方式
1. 打开 Cherry Studio 设置
2. 添加新的 MCP Server
3. 类型选择：`Streamable HTTP`
4. URL 填写：`http://your-server:8022/mcp`

### 示例配置 JSON
```json
{
  "mcpServers": {
    "crypto-orderflow": {
      "type": "streamableHttp",
      "url": "http://localhost:8022/mcp"
    }
  }
}
```

## 🐳 Docker 部署

### 使用 Docker Compose

```bash
cd crypto-orderflow-mcp
docker-compose -f docker/docker-compose.yml up -d
```

### 自定义构建

```bash
docker build -t crypto-orderflow-mcp -f docker/Dockerfile .
docker run -d -p 8022:8022 --name crypto-mcp crypto-orderflow-mcp
```

## ⚙️ Systemd 服务 (生产环境)

```bash
# 复制服务文件
sudo cp systemd/crypto-mcp.service /etc/systemd/system/

# 创建用户
sudo useradd -r -s /bin/false crypto-mcp

# 安装到 /opt
sudo mkdir -p /opt/crypto-orderflow-mcp
sudo cp -r . /opt/crypto-orderflow-mcp/
sudo chown -R crypto-mcp:crypto-mcp /opt/crypto-orderflow-mcp

# 启动服务
sudo systemctl daemon-reload
sudo systemctl enable crypto-mcp
sudo systemctl start crypto-mcp

# 查看状态
sudo systemctl status crypto-mcp
sudo journalctl -u crypto-mcp -f
```

## 🧪 测试

```bash
# 运行所有测试
pytest tests/ -v

# 运行特定测试
pytest tests/test_vwap.py -v
pytest tests/test_volume_profile.py -v

# 覆盖率报告
pytest tests/ --cov=src --cov-report=html
```

## 📁 项目结构

```
crypto-orderflow-mcp/
├── src/
│   ├── __init__.py
│   ├── main.py                 # 入口点
│   ├── config.py               # 配置管理
│   ├── server/
│   │   └── mcp_server.py       # MCP Server
│   ├── data/
│   │   ├── binance_rest.py     # REST API 客户端
│   │   ├── binance_ws.py       # WebSocket 客户端
│   │   ├── orderbook.py        # 订单簿管理
│   │   └── trade_aggregator.py # 交易聚合
│   ├── indicators/
│   │   ├── vwap.py             # VWAP
│   │   ├── volume_profile.py   # Volume Profile
│   │   ├── session_levels.py   # Session H/L
│   │   ├── footprint.py        # Footprint
│   │   ├── delta_cvd.py        # Delta/CVD
│   │   ├── imbalance.py        # Imbalance
│   │   └── depth_delta.py      # Depth Delta
│   ├── storage/
│   │   ├── sqlite_store.py     # SQLite 存储
│   │   └── cache.py            # 内存缓存
│   ├── tools/                  # MCP Tools
│   └── utils/                  # 工具函数
├── tests/                      # 单元测试
├── docker/                     # Docker 配置
├── systemd/                    # Systemd 服务
├── docs/                       # 文档
├── requirements.txt
├── pyproject.toml
└── README.md
```

## ⚠️ 注意事项

1. **只读设计**: 本服务只读取市场数据，不实现下单功能，防止误交易
2. **数据一致性**: 使用 WebSocket + REST snapshot 确保订单簿数据一致性
3. **自动重连**: WebSocket 断线自动重连，并用 REST 补齐数据缺口
4. **Rate Limit**: 内置速率限制器，避免触发交易所限制

## 📝 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `BINANCE_REST_URL` | `https://fapi.binance.com` | Binance REST API |
| `BINANCE_WS_URL` | `wss://fstream.binance.com` | Binance WebSocket |
| `SYMBOLS` | `BTCUSDT,ETHUSDT` | 监控的交易对 |
| `HOST` | `0.0.0.0` | 服务器地址 |
| `PORT` | `8022` | 服务器端口 |
| `CACHE_DB_PATH` | `./data/orderflow_cache.db` | SQLite 路径 |
| `TRADE_CACHE_DAYS` | `7` | 数据保留天数 |
| `VALUE_AREA_PERCENT` | `70` | Value Area 百分比 |
| `IMBALANCE_RATIO_THRESHOLD` | `3.0` | Imbalance 比例阈值 |
| `IMBALANCE_CONSECUTIVE_COUNT` | `3` | 连续 Imbalance 数量 |
| `DEPTH_DELTA_PERCENT` | `1.0` | 深度计算价格范围 |
| `LOG_LEVEL` | `INFO` | 日志级别 |

## 📄 License

MIT License - 详见 [LICENSE](LICENSE)
