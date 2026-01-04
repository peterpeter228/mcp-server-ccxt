#!/bin/bash
# CCXT MCP Server 部署脚本
# 用法: bash deploy.sh

set -e

echo "=========================================="
echo "CCXT MCP Server 部署脚本"
echo "=========================================="

PROJECT_DIR="/root/mcp-server-ccxt"
SERVICE_NAME="mcp-server-ccxt"

# 检查目录
if [ ! -d "$PROJECT_DIR" ]; then
    echo "错误: 项目目录 $PROJECT_DIR 不存在"
    exit 1
fi

cd "$PROJECT_DIR"

echo ""
echo "[1/5] 停止服务..."
systemctl stop $SERVICE_NAME 2>/dev/null || true

echo ""
echo "[2/5] 安装依赖..."
npm install --silent

echo ""
echo "[3/5] 构建项目..."
npm run build

echo ""
echo "[4/5] 创建/更新环境配置..."
cat > .env << 'EOF'
# MCP Server 配置
MCP_TRANSPORT=sse
MCP_HTTP_PORT=8055
MCP_HTTP_HOST=0.0.0.0
CORS_ORIGIN=*

# 默认交易所
DEFAULT_EXCHANGE=binance
DEFAULT_MARKET_TYPE=spot

# 日志级别
LOG_LEVEL=info

# Binance API（可选）
# BINANCE_API_KEY=your_key
# BINANCE_SECRET=your_secret

# 数据源工具 API（可选）
# FRED_API_KEY=your_fred_key
# ETHERSCAN_API_KEY=your_etherscan_key
EOF

echo ""
echo "[5/5] 创建/更新 systemd 服务..."
cat > /etc/systemd/system/$SERVICE_NAME.service << EOF
[Unit]
Description=CCXT MCP Server (SSE Mode - Port 8055)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$PROJECT_DIR
EnvironmentFile=$PROJECT_DIR/.env
ExecStart=/usr/bin/node $PROJECT_DIR/build/index.js
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=$SERVICE_NAME

[Install]
WantedBy=multi-user.target
EOF

echo ""
echo "重载 systemd..."
systemctl daemon-reload

echo ""
echo "启动服务..."
systemctl enable $SERVICE_NAME
systemctl start $SERVICE_NAME

echo ""
echo "等待服务启动..."
sleep 3

echo ""
echo "=========================================="
echo "部署完成!"
echo "=========================================="
echo ""
systemctl status $SERVICE_NAME --no-pager -l
echo ""
echo "验证命令:"
echo "  curl http://localhost:8055/health"
echo "  curl http://localhost:8055/"
echo ""
echo "查看日志:"
echo "  journalctl -u $SERVICE_NAME -f"
echo ""
echo "SSE端点: http://YOUR_IP:8055/sse"
echo "=========================================="
