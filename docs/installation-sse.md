# SSE模式安装与Systemd服务配置指南

本指南介绍如何以SSE模式（端口8055）部署MCP Server，并配置systemd实现后台自动重启。

## 1. 安装依赖

```bash
# 确保Node.js >= 18
node --version

# 克隆或进入项目目录
cd /path/to/mcp-server-ccxt

# 安装依赖
npm install

# 构建项目
npm run build
```

## 2. 配置环境变量

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑.env文件
nano .env
```

编辑 `.env` 文件，设置以下内容：

```env
# Transport配置 - SSE模式，端口8055
MCP_TRANSPORT=sse
MCP_HTTP_PORT=8055
MCP_HTTP_HOST=0.0.0.0

# CORS（根据需要设置）
CORS_ORIGIN=*

# 默认交易所
DEFAULT_EXCHANGE=binance
DEFAULT_MARKET_TYPE=spot

# Binance API（如需要期货工具）
BINANCE_API_KEY=your_api_key
BINANCE_SECRET=your_secret

# 数据源工具API密钥（可选）
# FRED_API_KEY=your_fred_key
# ETHERSCAN_API_KEY=your_etherscan_key

# 日志级别
LOG_LEVEL=info
```

## 3. 创建Systemd服务

### 3.1 创建服务文件

```bash
sudo nano /etc/systemd/system/mcp-server-ccxt.service
```

写入以下内容：

```ini
[Unit]
Description=CCXT MCP Server (SSE Mode)
Documentation=https://github.com/doggybee/mcp-server-ccxt
After=network.target

[Service]
Type=simple
User=ubuntu
Group=ubuntu
WorkingDirectory=/path/to/mcp-server-ccxt
Environment=NODE_ENV=production
Environment=MCP_TRANSPORT=sse
Environment=MCP_HTTP_PORT=8055
Environment=MCP_HTTP_HOST=0.0.0.0
EnvironmentFile=/path/to/mcp-server-ccxt/.env
ExecStart=/usr/bin/node /path/to/mcp-server-ccxt/build/index.js
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=mcp-server-ccxt

# 安全设置
NoNewPrivileges=true
PrivateTmp=true

# 资源限制
LimitNOFILE=65536
MemoryMax=512M

[Install]
WantedBy=multi-user.target
```

**注意：** 请将 `/path/to/mcp-server-ccxt` 替换为实际的项目路径，`User` 和 `Group` 替换为实际运行用户。

### 3.2 重新加载Systemd配置

```bash
sudo systemctl daemon-reload
```

## 4. 服务管理命令

### 启动服务
```bash
sudo systemctl start mcp-server-ccxt
```

### 停止服务
```bash
sudo systemctl stop mcp-server-ccxt
```

### 重启服务
```bash
sudo systemctl restart mcp-server-ccxt
```

### 查看服务状态
```bash
sudo systemctl status mcp-server-ccxt
```

### 设置开机自启
```bash
sudo systemctl enable mcp-server-ccxt
```

### 取消开机自启
```bash
sudo systemctl disable mcp-server-ccxt
```

## 5. 日志查看

### 实时查看日志
```bash
sudo journalctl -u mcp-server-ccxt -f
```

### 查看最近100行日志
```bash
sudo journalctl -u mcp-server-ccxt -n 100
```

### 查看今天的日志
```bash
sudo journalctl -u mcp-server-ccxt --since today
```

### 查看错误日志
```bash
sudo journalctl -u mcp-server-ccxt -p err
```

## 6. 验证服务

### 检查端口监听
```bash
ss -tlnp | grep 8055
# 或
netstat -tlnp | grep 8055
```

### 测试健康检查端点
```bash
curl http://localhost:8055/health
```

预期输出：
```json
{"status":"ok","transport":"sse"}
```

### 测试SSE端点
```bash
curl -N http://localhost:8055/sse
```

### 测试API信息
```bash
curl http://localhost:8055/
```

预期输出：
```json
{
  "name": "CCXT MCP Server",
  "version": "1.2.0",
  "transport": "sse",
  "endpoints": {
    "sse": "/sse",
    "messages": "/messages",
    "httpStream": "/mcp",
    "health": "/health"
  }
}
```

## 7. 客户端连接配置

### CherryStudio配置
```json
{
  "name": "ccxt-mcp",
  "type": "sse",
  "url": "http://your-server-ip:8055/sse"
}
```

### 其他MCP客户端
SSE端点: `http://your-server-ip:8055/sse`

## 8. 防火墙配置（如需要）

### UFW
```bash
sudo ufw allow 8055/tcp
sudo ufw reload
```

### firewalld
```bash
sudo firewall-cmd --permanent --add-port=8055/tcp
sudo firewall-cmd --reload
```

### iptables
```bash
sudo iptables -A INPUT -p tcp --dport 8055 -j ACCEPT
```

## 9. 故障排除

### 服务无法启动
```bash
# 检查服务状态
sudo systemctl status mcp-server-ccxt

# 查看详细错误
sudo journalctl -u mcp-server-ccxt -e
```

### 端口被占用
```bash
# 查看端口占用
sudo lsof -i :8055

# 杀死占用进程
sudo kill -9 <PID>
```

### 权限问题
```bash
# 确保项目目录权限正确
sudo chown -R ubuntu:ubuntu /path/to/mcp-server-ccxt

# 确保node可执行
which node
```

### 环境变量未生效
```bash
# 检查环境文件
cat /path/to/mcp-server-ccxt/.env

# 重启服务
sudo systemctl restart mcp-server-ccxt
```

## 10. 快速部署脚本

创建一键部署脚本 `deploy-sse.sh`:

```bash
#!/bin/bash
set -e

# 配置
PROJECT_DIR="/opt/mcp-server-ccxt"
SERVICE_USER="ubuntu"
SSE_PORT="8055"

echo "=== MCP Server CCXT SSE部署脚本 ==="

# 1. 安装依赖并构建
echo "[1/4] 安装依赖并构建..."
cd $PROJECT_DIR
npm install
npm run build

# 2. 创建.env文件（如不存在）
if [ ! -f .env ]; then
    echo "[2/4] 创建.env文件..."
    cp .env.example .env
    sed -i "s/MCP_TRANSPORT=stdio/MCP_TRANSPORT=sse/" .env
    sed -i "s/MCP_HTTP_PORT=3000/MCP_HTTP_PORT=$SSE_PORT/" .env
fi

# 3. 创建systemd服务
echo "[3/4] 配置systemd服务..."
sudo tee /etc/systemd/system/mcp-server-ccxt.service > /dev/null <<EOF
[Unit]
Description=CCXT MCP Server (SSE Mode)
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$PROJECT_DIR
EnvironmentFile=$PROJECT_DIR/.env
Environment=MCP_TRANSPORT=sse
Environment=MCP_HTTP_PORT=$SSE_PORT
Environment=MCP_HTTP_HOST=0.0.0.0
ExecStart=/usr/bin/node $PROJECT_DIR/build/index.js
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# 4. 启动服务
echo "[4/4] 启动服务..."
sudo systemctl daemon-reload
sudo systemctl enable mcp-server-ccxt
sudo systemctl restart mcp-server-ccxt

# 等待启动
sleep 2

# 验证
echo ""
echo "=== 部署完成 ==="
sudo systemctl status mcp-server-ccxt --no-pager
echo ""
echo "SSE端点: http://localhost:$SSE_PORT/sse"
echo "健康检查: curl http://localhost:$SSE_PORT/health"
echo "查看日志: sudo journalctl -u mcp-server-ccxt -f"
```

使用方法：
```bash
chmod +x deploy-sse.sh
sudo ./deploy-sse.sh
```

## 11. 数据源工具示例调用

服务启动后，可以通过MCP客户端调用以下工具：

```bash
# 获取跨交易所价格共识
curl -X POST http://localhost:8055/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "mcp_ext-cross_exchange_anchor_consensus_a9YOaP",
      "arguments": {"symbol": "BTCUSDT"}
    },
    "id": 1
  }'

# 获取交易所状态
curl -X POST http://localhost:8055/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "mcp_ext-exchange_status_aggregator_a9YOaP",
      "arguments": {}
    },
    "id": 2
  }'
```
