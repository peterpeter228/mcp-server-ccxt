# Crypto Orderflow MCP Server

**Market Data & Orderflow Indicators for Binance USD-M Futures**

一个基于 Model Context Protocol (MCP) 的加密货币行情与 Orderflow 指标服务器，专为 Cherry Studio 等 AI 助手设计，提供实时的 BTC/ETH 永续合约数据和专业的量化交易指标。

## 功能特性

### 数据源
- **交易所**: Binance USD-M Futures（币安U本位永续合约）
- **连接方式**: REST API + WebSocket 实时数据
- **支持交易对**: BTCUSDT, ETHUSDT（可配置扩展）

### Key Levels 指标
- **VWAP**: 当日成交量加权均价 (dVWAP) 和前日 VWAP (pdVWAP)
- **Volume Profile**: 
  - POC (Point of Control) - 最高成交量价位
  - VAH (Value Area High) - 价值区域上沿
  - VAL (Value Area Low) - 价值区域下沿
  - 支持当日开发中 (developing) 和前日 (previous day) 数据
- **Session High/Low**:
  - 东京时段 (00:00-09:00 UTC)
  - 伦敦时段 (07:00-16:00 UTC)
  - 纽约时段 (13:00-22:00 UTC)
  - 时间窗口可配置

### Orderflow 指标
- **Footprint Charts**: 
  - 按价格等级聚合买卖量
  - 支持 1m/5m/15m/30m/1h 时间周期
  - 包含 Delta、POC、最大/最小 Delta 价位
- **Delta & CVD**:
  - Delta bars（买卖差）
  - Cumulative Volume Delta（累积成交量差）
- **Stacked Imbalance**:
  - 可配置阈值（默认 ratio>=3，连续>=3 价位）
  - 买卖方向识别

### 衍生品数据
- **Funding Rate**: 当前资金费率、下次结算时间、历史费率
- **Open Interest**: 当前持仓量、持仓金额、历史数据、OI Delta
- **Liquidations**: 实时清算事件流（缓存最近 1000 条）
- **Orderbook Depth Delta**: ±N% 范围内买卖盘深度变化

## 快速开始

### 方式一：Docker 部署（推荐）

```bash
# 克隆项目
git clone https://github.com/your-repo/crypto-orderflow-mcp.git
cd crypto-orderflow-mcp

# 创建环境变量文件
cp .env.example .env

# 启动服务
cd docker
docker-compose up -d

# 查看日志
docker-compose logs -f
```

服务将在 `http://localhost:8022` 启动。

### 方式二：本地运行

```bash
# 创建虚拟环境
python3.12 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 文件根据需要调整配置

# 运行服务
python run.py
```

### 方式三：Systemd 服务

```bash
# 创建用户
sudo useradd -r -s /bin/false mcp

# 复制项目
sudo mkdir -p /opt/crypto-orderflow-mcp
sudo cp -r . /opt/crypto-orderflow-mcp/
sudo chown -R mcp:mcp /opt/crypto-orderflow-mcp

# 设置虚拟环境
sudo -u mcp python3.12 -m venv /opt/crypto-orderflow-mcp/venv
sudo -u mcp /opt/crypto-orderflow-mcp/venv/bin/pip install -r requirements.txt

# 配置环境
sudo cp .env.example /opt/crypto-orderflow-mcp/.env
sudo nano /opt/crypto-orderflow-mcp/.env

# 安装服务
sudo cp crypto-orderflow-mcp.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable crypto-orderflow-mcp
sudo systemctl start crypto-orderflow-mcp

# 查看状态
sudo systemctl status crypto-orderflow-mcp
```

## Cherry Studio 配置

### SSE 连接方式

在 Cherry Studio 的 MCP 设置中添加：

```
URL: http://your-server-ip:8022/sse
Transport: SSE
```

### Streamable HTTP 方式

```
URL: http://your-server-ip:8022/mcp
Transport: HTTP
```

### 配置示例截图

1. 打开 Cherry Studio 设置
2. 进入 "MCP Servers" 配置
3. 添加新服务器：
   - 名称: `Crypto Orderflow`
   - URL: `http://localhost:8022/sse`
   - 类型: `SSE`
4. 保存并启用

## MCP Tools

### get_market_snapshot
获取市场快照，包括最新价、标记价、24h 统计、资金费率、持仓量。

```json
{
  "symbol": "BTCUSDT"
}
```

### get_key_levels
获取关键价位，包括 VWAP、Volume Profile、Session H/L。

```json
{
  "symbol": "BTCUSDT",
  "date": "2024-01-15",  // 可选，默认今天
  "sessionTZ": "UTC"      // 可选
}
```

### get_footprint
获取 Footprint 数据。

```json
{
  "symbol": "BTCUSDT",
  "timeframe": "5m",
  "startTime": 1705276800000,
  "endTime": 1705280400000
}
```

### get_orderflow_metrics
获取 Orderflow 指标（Delta、CVD、Imbalance）。

```json
{
  "symbol": "BTCUSDT",
  "timeframe": "15m",
  "startTime": 1705276800000,
  "endTime": 1705280400000
}
```

### get_orderbook_depth_delta
获取订单簿深度变化。

```json
{
  "symbol": "BTCUSDT",
  "percent": 1.0,      // 价格范围百分比
  "windowSec": 5,      // 快照间隔
  "lookback": 3600     // 回溯秒数
}
```

### stream_liquidations
获取近期清算事件。

```json
{
  "symbol": "BTCUSDT",
  "limit": 100
}
```

### get_open_interest
获取持仓量数据。

```json
{
  "symbol": "BTCUSDT",
  "period": "5m",
  "limit": 100
}
```

### get_funding_rate
获取资金费率。

```json
{
  "symbol": "BTCUSDT"
}
```

## 环境变量配置

| 变量 | 默认值 | 说明 |
|-----|--------|------|
| MCP_HOST | 0.0.0.0 | 服务监听地址 |
| MCP_PORT | 8022 | 服务监听端口 |
| LOG_LEVEL | INFO | 日志级别 (DEBUG/INFO/WARNING/ERROR) |
| BINANCE_REST_URL | https://fapi.binance.com | Binance REST API 地址 |
| BINANCE_WS_URL | wss://fstream.binance.com | Binance WebSocket 地址 |
| SYMBOLS | BTCUSDT,ETHUSDT | 追踪的交易对（逗号分隔） |
| CACHE_DB_PATH | ./data/orderflow_cache.db | SQLite 数据库路径 |
| DATA_RETENTION_DAYS | 7 | 数据保留天数 |
| TOKYO_SESSION | 00:00-09:00 | 东京时段（UTC） |
| LONDON_SESSION | 07:00-16:00 | 伦敦时段（UTC） |
| NY_SESSION | 13:00-22:00 | 纽约时段（UTC） |
| FOOTPRINT_TICK_SIZE_BTC | 0.1 | BTC Footprint tick 大小 |
| FOOTPRINT_TICK_SIZE_ETH | 0.01 | ETH Footprint tick 大小 |
| IMBALANCE_RATIO_THRESHOLD | 3.0 | Imbalance 比率阈值 |
| IMBALANCE_CONSECUTIVE_LEVELS | 3 | 连续 Imbalance 价位数 |
| ORDERBOOK_DEPTH_PERCENT | 1.0 | 订单簿深度计算范围（%） |

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| / | GET | 服务信息 |
| /healthz | GET | 健康检查 |
| /sse | GET/POST | SSE MCP 传输 |
| /mcp | POST | Streamable HTTP MCP 传输 |

## 开发

### 运行测试

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest tests/ -v

# 运行测试并生成覆盖率报告
pytest tests/ --cov=src --cov-report=html
```

### 代码结构

```
crypto-orderflow-mcp/
├── src/
│   ├── binance/        # Binance API 客户端
│   ├── data/           # 数据存储层
│   ├── indicators/     # 指标计算
│   ├── mcp/           # MCP Server
│   └── utils/         # 工具函数
├── tests/             # 单元测试
├── docker/            # Docker 配置
└── docs/              # 文档
```

## 常见问题

### Q: 数据延迟大吗？
A: 使用 Binance 官方 WebSocket 实时数据，延迟通常在 50-200ms。

### Q: 支持其他交易所吗？
A: 当前仅支持 Binance USD-M Futures，架构设计支持扩展其他交易所。

### Q: 需要 Binance API Key 吗？
A: 不需要。所有数据都是公开市场数据，无需认证。

### Q: 数据准确性如何保证？
A: 
- Trades 来自官方 aggTrade WebSocket 流
- Orderbook 使用 snapshot + diff 机制，带有一致性校验
- 所有计算可复现

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！
