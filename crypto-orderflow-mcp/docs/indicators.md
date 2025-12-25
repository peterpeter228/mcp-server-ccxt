# 指标计算说明

本文档详细说明各项指标的计算方法。

## VWAP (Volume Weighted Average Price)

### 定义
成交量加权平均价格，反映市场的公允价值。

### 计算公式
```
VWAP = Σ(Price × Volume) / Σ(Volume)
```

### 实现细节
- 使用每笔成交的价格和数量计算
- 每日 UTC 00:00 重置
- 支持查询当日 dVWAP 和前日 pdVWAP

### 交易意义
- 价格 > VWAP: 多头趋势
- 价格 < VWAP: 空头趋势
- VWAP 常作为机构交易的基准价格

---

## Volume Profile

### 定义
按价格水平分布的成交量直方图。

### 关键概念

#### POC (Point of Control)
成交量最高的价格水平。

```python
POC = argmax(Volume[price])
```

#### Value Area (VA)
包含总成交量 70% 的价格区间。

#### VAH (Value Area High)
Value Area 的上边界。

#### VAL (Value Area Low)
Value Area 的下边界。

### 计算步骤
1. 将价格按 tick_size 分组
2. 统计每个价格水平的成交量
3. 找到 POC（最高成交量水平）
4. 从 POC 向两侧扩展，直到包含 70% 成交量

### 配置
```env
VALUE_AREA_PERCENT=70
TICK_SIZE_BTCUSDT=0.1
TICK_SIZE_ETHUSDT=0.01
```

### 交易意义
- POC: 公允价值，常作为支撑/阻力
- VAH: 上方阻力
- VAL: 下方支撑
- 价格在 VA 外时可能回归

---

## Session Levels

### 定义
各交易时段的最高价和最低价。

### 默认时段 (UTC)
| 时段 | 开始 | 结束 |
|------|------|------|
| Tokyo | 00:00 | 09:00 |
| London | 07:00 | 16:00 |
| NY | 13:00 | 22:00 |

### 配置
```env
SESSION_TOKYO_START=00:00
SESSION_TOKYO_END=09:00
SESSION_LONDON_START=07:00
SESSION_LONDON_END=16:00
SESSION_NY_START=13:00
SESSION_NY_END=22:00
```

### 交易意义
- 各时段高低点常作为日内支撑/阻力
- 突破前一时段高点通常意味着动能增强
- 时段交叉期间（如 London-NY overlap）通常波动较大

---

## Footprint

### 定义
按价格水平细分的 K 线图，显示每个价位的买卖成交量。

### 数据结构
每个 Footprint Bar 包含：
- OHLC 价格
- 按 tick 分组的成交量
- 每个价位的买入/卖出分别统计
- Delta (买入量 - 卖出量)

### 关键指标

#### Bar Delta
```
Bar Delta = Total Buy Volume - Total Sell Volume
```

#### Level Delta
```
Level Delta = Buy Volume[price] - Sell Volume[price]
```

#### Max/Min Delta Price
Delta 最大/最小的价格水平。

### 交易意义
- 正 Delta: 买方积极
- 负 Delta: 卖方积极
- High Volume Nodes: 潜在支撑/阻力
- Low Volume Nodes: 快速穿越区域

---

## CVD (Cumulative Volume Delta)

### 定义
累计成交量差值，追踪买卖力量的累积变化。

### 计算公式
```
CVD(t) = CVD(t-1) + Delta(t)
```

### 交易意义
- CVD 上升 + 价格上升: 健康上涨
- CVD 下降 + 价格下降: 健康下跌
- CVD 下降 + 价格上升: 潜在顶部（看跌背离）
- CVD 上升 + 价格下降: 潜在底部（看涨背离）

---

## Stacked Imbalance

### 定义
连续多个价格水平出现买卖失衡的情况。

### 识别条件
1. 单个价位失衡：买/卖比例 ≥ 阈值（默认 3:1）
2. 堆叠失衡：连续 N 个价位（默认 3 个）都出现失衡

### 配置
```env
IMBALANCE_RATIO_THRESHOLD=3.0
IMBALANCE_CONSECUTIVE_COUNT=3
```

### 类型
- **Buy Imbalance**: 买入量远超卖出量
- **Sell Imbalance**: 卖出量远超买入量

### 交易意义
- Stacked Buy Imbalance: 强势买入，可能形成支撑
- Stacked Sell Imbalance: 强势卖出，可能形成阻力
- 常用于识别供需失衡区域

---

## Orderbook Depth Delta

### 定义
订单簿深度的变化，监控买卖挂单的增减。

### 计算方法
1. 计算中间价附近 ±X% 范围内的总挂单量
2. 定期采样（默认 5 秒）
3. 计算相邻采样之间的变化量

### 配置
```env
DEPTH_DELTA_PERCENT=1.0
DEPTH_DELTA_INTERVAL_SEC=5
```

### 指标

#### Bid Volume
买单总量（价格范围内）

#### Ask Volume
卖单总量（价格范围内）

#### Net Depth
```
Net Depth = Bid Volume - Ask Volume
```

#### Depth Delta
```
Depth Delta(t) = Net Depth(t) - Net Depth(t-1)
```

### 交易意义
- 正 Net Depth: 买单多于卖单，支撑较强
- 负 Net Depth: 卖单多于买单，压力较大
- Depth 突然减少: 大单成交或撤单
- 适合与价格走势结合分析

---

## 衍生品指标

### Funding Rate (资金费率)

每 8 小时结算一次的费用，用于平衡永续合约与现货价格。

- 正费率: 多头付给空头（多头居多）
- 负费率: 空头付给多头（空头居多）

### Open Interest (持仓量)

未平仓合约的总数量。

- OI 上升 + 价格上升: 新多头进场
- OI 上升 + 价格下降: 新空头进场
- OI 下降 + 价格上升: 空头平仓
- OI 下降 + 价格下降: 多头平仓

### Liquidations (清算)

强制平仓事件，通常发生在：
- 多头爆仓: 价格大幅下跌
- 空头爆仓: 价格大幅上涨

大规模清算可能导致级联效应，加剧价格波动。

---

## 数据精度说明

### 时间精度
- 所有时间戳使用毫秒
- 时区统一使用 UTC

### 价格精度
- BTCUSDT: 0.1 USDT
- ETHUSDT: 0.01 USDT
- 可通过配置调整

### 数量精度
- 使用 Decimal 类型避免浮点误差
- 计算结果可复现

---

## 计算可复现性保证

1. **相同输入，相同输出**: 给定相同的原始 trades 数据，所有指标计算结果一致
2. **确定性算法**: 不使用随机数或非确定性操作
3. **精确数值**: 使用 Decimal 而非 float
4. **时间对齐**: 所有 bar 按固定时间窗口对齐
