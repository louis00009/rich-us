# QuantDesk for IBKR

> 面向 Interactive Brokers 的本地化 AI 量化交易平台 —— 策略研究 · 回测验证 · 风险控制 · 模拟演练 · 实盘执行，完整闭环。

|  |  |
|---|---|
| **后端** | Python 3.11+ / FastAPI / SQLAlchemy / pandas / NumPy / ib_async |
| **前端** | React 18 + TypeScript + Vite + Tailwind CSS + Recharts + 自绘 SVG 蜡烛图 |
| **数据库** | SQLite（WAL 模式，单文件，零运维） |
| **部署形态** | 单机本地服务，仅监听 `127.0.0.1`，单端口同时提供 API 与前端 |
| **实盘安全** | 三道锁：环境变量 → 运行时解锁 → 逐笔风控护栏 |

---

## 一、快速开始

```bash
# Windows
start.bat

# macOS / Linux / Git Bash
chmod +x start.sh && ./start.sh
```

脚本自动完成：创建虚拟环境 → 安装依赖 → 构建前端 → 启动服务 → 打开浏览器。

首次打开会要求**创建管理员账户**（口令 ≥10 位，含大小写/数字/符号中至少三类）。
之后访问 <http://127.0.0.1:8787>。API 文档在 <http://127.0.0.1:8787/api/docs>。

### 手动启动

```bash
# 后端
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt     # Windows
# .venv/bin/pip install -r requirements.txt       # macOS/Linux
python run.py

# 前端（开发模式，带热更新；API 自动代理到 8787）
cd frontend
npm install
npm run dev            # http://localhost:5173
```

### 自检

```bash
cd backend
.venv/Scripts/python.exe ../tests/run_checks.py             # 后端 147 项
.venv/Scripts/python.exe ../tests/run_checks.py data        # 只跑数据层
.venv/Scripts/python.exe ../tests/run_checks.py strategies  # 只跑策略与风控
.venv/Scripts/python.exe ../tests/run_checks.py optimize    # 只跑组合优化
.venv/Scripts/python.exe ../tests/run_checks.py api         # 只跑 API

# 前端渲染 + 交互检查（jsdom 挂载生产产物并连真实后端；需后端已启动）
cd frontend && npm run build && npm run smoke
```

想看组合优化的**真实行情结果**（而非回归断言）时，可在服务启动后单独跑：

```bash
cd backend && .venv/Scripts/python.exe ../tests/optimize_e2e.py
```

---

## 二、目录结构

```
IBKR/
├── backend/
│   ├── app/
│   │   ├── config.py            配置、密钥材料、实盘环境开关
│   │   ├── security.py          bcrypt 口令、JWT、Fernet 凭据加密、登录限速
│   │   ├── database.py          SQLite 引擎与会话
│   │   ├── models.py            ORM 模型（用户/策略/回测/订单/风控/审计…）
│   │   ├── schemas.py           Pydantic 请求响应模型（全部外部输入强校验）
│   │   ├── state.py             审计日志、设置中心、模式与实盘解锁状态
│   │   ├── data_provider.py     多级行情源 + 外部提供者注册 + 本地缓存
│   │   ├── ai_analyst.py        本地量化分析引擎 + LLM 解读（可选）
│   │   ├── strategies/
│   │   │   ├── base.py          策略基类、ParamSpec、信号上下文
│   │   │   ├── registry.py      策略注册表
│   │   │   ├── indicators.py    35+ 技术指标（纯 pandas/numpy）
│   │   │   ├── frames.py        DataFrame 级指标助手
│   │   │   ├── builtin_trend.py      趋势动量族（9 个）
│   │   │   ├── builtin_reversion.py  均值回归族（7 个）
│   │   │   ├── builtin_intraday.py   日内微观族（4 个）
│   │   │   ├── builtin_advanced.py   进阶前沿族（8 个）
│   │   │   └── custom.py        规则 DSL + AST 沙箱代码策略
│   │   ├── risk/
│   │   │   ├── stops.py         9 种止损状态机（回测/实盘共用）
│   │   │   ├── sizing.py        6 种仓位算法
│   │   │   └── guardrails.py    交易护栏（单笔/集中度/日亏/回撤/时段/白黑名单/熔断）
│   │   ├── engine/
│   │   │   ├── backtest.py      事件驱动回测（FIFO 配对、滑点佣金、无未来函数）
│   │   │   ├── metrics.py       30+ 绩效与风险指标
│   │   │   ├── optimizer.py     组合优化（纯 numpy：Ledoit-Wolf + 贝叶斯收缩 + 投影梯度）
│   │   │   └── live.py          实时策略引擎（信号→差分→护栏→下单→保护性委托）
│   │   ├── brokers/
│   │   │   ├── base.py          券商抽象（含历史数据/挂单/成交回报能力位）
│   │   │   ├── simulated.py     内置模拟券商（持久化虚拟账户）
│   │   │   └── ibkr.py          IBKR 适配（真实行情 + 持仓盈亏 + OCO 括号单）
│   │   └── api/                 认证 / 系统 / 行情 / 策略 / 回测 / 组合优化 / 交易 / 风控 / AI / WebSocket
│   ├── runtime/                 ← 运行时数据（数据库、密钥、缓存、日志）
│   └── requirements.txt
├── frontend/
│   ├── render-smoke.mjs         jsdom 渲染 + 交互自检（npm run smoke）
│   ├── scripts/prebuild.mjs     构建前归档旧产物（规避 safe-delete 拦截）
│   └── src/
│       ├── pages/               10 个页面
│       ├── components/          UI 组件库 + 图表组件 + 自绘蜡烛图
│       ├── lib/                 API 客户端、格式化、类型
│       └── store/               认证状态
├── tests/
│   └── run_checks.py            后端 147 项自检
├── .env.example
└── start.bat / start.sh
```

---

## 三、内置策略库（28 个）

### 趋势动量（9）
| Key | 名称 | 说明 |
|---|---|---|
| `dual_ma_trend` | 双均线趋势跟踪 | 经典趋势骨架，可开做空 |
| `tsmom_vol_target` | 时序动量 · 波动率目标 | 仓位 = 目标波动率 / 已实现波动率 |
| `dual_momentum` | 双动量轮动 | 相对动量排序 + 绝对动量过滤（Antonacci） |
| `xs_momentum` | 横截面动量轮动 | 风险调整动量打分，多空双向 |
| `donchian_breakout` | 唐奇安通道突破 | 海龟法则内核 |
| `supertrend` | Supertrend 超级趋势 | ATR 动态跟踪通道 |
| `ma_ribbon` | 均线带多头排列 | 10/20/50/100/200 排列连续打分 |
| `adx_trend_rider` | ADX 趋势骑手 | 趋势强度过滤，只在高 ADX 持仓 |
| `trend_composite` | 趋势综合评分 | 均线位置 + 斜率 + 动量三证据融合 |

### 均值回归（7）
| Key | 名称 | 说明 |
|---|---|---|
| `rsi_meanrev` | RSI 超卖反转 | 超卖买入、中轴离场 |
| `bollinger_meanrev` | 布林带均值回归 | 触轨反转 + 带宽分位过滤 |
| `zscore_reversion` | Z 分数回归 | 统计套利思路 |
| `connors_rsi2` | Connors RSI2 反转 | 短周期极端反转，高胜率 |
| `ibs_reversion` | IBS 日内强度反转 | 收盘位置极低时买入 |
| `pairs_trading` | 协整配对交易 | 滚动 OLS 对冲比率，市场中性 |
| `keltner_reversion` | 肯特纳通道回归 | ATR 口径通道，抗跳空 |

### 进阶前沿（8）
| Key | 名称 | 说明 |
|---|---|---|
| `ml_alpha_ridge` | 机器学习多因子 Alpha | 25+ 因子，walk-forward 滚动重训（自动升级 LightGBM） |
| `vol_managed_momentum` | 波动率管理动量 | Moreira & Muir：按上一期方差缩放仓位 |
| `regime_adaptive` | 状态自适应切换 | 按波动率分位与效率比在趋势/回归间切换 |
| `dual_thrust` | Dual Thrust 区间突破 | CTA 经典，参数不敏感 |
| `vcp_breakout` | VCP 波动收缩突破 | Minervini 形态量化 |
| `grid_trading` | ATR 自适应网格 | 锚点随长期均线漂移 |
| `risk_parity_alloc` | 风险平价配置 | 波动率倒数加权 + 动量过滤 |
| `ensemble_vote` | 多策略集成投票 | 多腿集成，降低单策略失效风险 |

### 日内微观（4）
`orb_breakout`（开盘区间突破）、`vwap_reversion`（VWAP 回归）、
`intraday_momentum`（日内动量延续）、`gap_fade`（跳空回补）

> 日内族需选择 5m/15m/30m/1h 周期回测。日线数据下 `orb_breakout` 会自动退化为
> 「前一日区间突破」、`intraday_momentum` 退化为「隔夜动量」，并在界面明确提示。

---

## 四、自定义策略

### 1. 参数化（最低门槛）
在策略库中打开任意内置策略，调整参数后直接回测。

### 2. 可视化规则 DSL（推荐）
用「指标 + 比较符 + 数值/指标」拼装进出场条件，支持 AND/OR 与「上穿/下穿」。
**不执行任何用户代码，零注入风险。**

```json
{
  "direction": "long",
  "entry": { "all": [
    { "left": {"indicator": "rsi", "period": 14}, "op": "<", "right": {"const": 35} },
    { "left": {"indicator": "close"}, "op": ">", "right": {"indicator": "sma", "period": 200} }
  ]},
  "exit": { "any": [
    { "left": {"indicator": "rsi", "period": 14}, "op": ">", "right": {"const": 65} }
  ]},
  "entry_size": 1.0,
  "max_hold_bars": 0
}
```
可用指标 38 个（RSI/MACD/ATR/ADX/布林/唐奇安/VWAP/Z分数/CMF 等）。

### 3. Python 代码策略（高级）
```python
import pandas as pd
import numpy as np

def generate(ctx):
    c = ctx.closes                       # DataFrame(日期 × 标的)
    fast = c.ewm(span=20, adjust=False).mean()
    slow = c.ewm(span=100, adjust=False).mean()
    w = pd.DataFrame(0.0, index=c.index, columns=c.columns)
    w[fast > slow] = 1.0                 # 目标权重 ∈ [-1, 1]
    return w
```

**沙箱防护（AST 白名单 + 受限 builtins）**

| 层级 | 拦截内容 |
|---|---|
| 模块导入 | 仅允许 `pandas` / `numpy` / `math` / `statistics` / `datetime` |
| 名称 | `eval` `exec` `open` `__import__` `compile` `os` `sys` `subprocess` `ctypes`… |
| 属性 | 所有 `_` 开头属性；`read_csv/read_pickle/to_csv/to_pickle/numpy.load/memmap` 等文件与序列化接口 |
| 字符串 | 以字符串形式引用受限接口同样拦截 |
| 结构 | `lambda` / `class` / `async` / `global` / `nonlocal` / `while True` |
| 规模 | 代码 ≤8000 字符，AST 节点 ≤1200 |
| 运行时 | 自定义 `__import__`（二次白名单）、受限 `getattr`（拦截私有属性） |

---

## 五、回测引擎

**核心保证**

1. **无未来函数** —— 第 t 根 bar 收盘生成的信号，只在第 t+1 根 bar 开盘成交。
2. **真实成本** —— 双边佣金 + 滑点，滑点方向永远对己不利。
3. **止损一致** —— 回测与实盘共用同一套 `StopTracker`。
4. **逐 bar 撮合** —— 止损以 bar 内 high/low 判定，而非仅看收盘价。
5. **FIFO 配对** —— 加仓/减仓按先进先出配对，盈亏归属清晰可审计。

**止损机制（9 种）**
`none` / `fixed_pct` / `pct_trailing` / `atr_fixed` / `atr_trailing` /
`chandelier` / `breakeven` / `time_stop` / `volatility`
可叠加 R 倍止盈与时间止损；移动止损只朝有利方向推进。

**仓位算法（6 种）**
`weight` / `fixed_fraction` / `risk_parity_vol` / `atr_risk`（固定风险，机构标准）/
`kelly_capped`（半凯利封顶）/ `equal_weight`

**绩效指标（30+）**
累计/年化收益、超额年化、波动率、夏普、索提诺、卡玛、最大回撤及水下期、
胜率、盈亏比、平均盈亏比、单笔期望、换手率、平均持仓比、日 VaR/CVaR、
偏度、峰度、Alpha、Beta、信息比率、月度热力图、基准对比。

**支持周期**：`1d` / `1wk` / `1h` / `30m` / `15m` / `5m`
（日线以下建议用 IBKR 数据源，免费源只有约 60 天）

---

## 六、IBKR 接入（真实的行情与交易通道）

### 6.1 准备工作

1. 安装并登录 TWS（或 IB Gateway），先用**纸面账户**跑通。
2. TWS → 文件 → 全局配置 → API → 设置：勾选「启用 ActiveX 和 Socket 客户端」。
3. 需要下单能力则取消勾选「只读 API」；仅监控则保持勾选（**推荐先只用只读**）。
4. 端口：TWS 纸面 `7497` / 实盘 `7496`；Gateway 纸面 `4002` / 实盘 `4001`。
5. 在「已信任的 IP 地址」中加入 `127.0.0.1`。
6. 若有多个客户端同时连接，为每个分配不同的 `client_id`。
7. 回到「系统设置 → 券商连接」保存并点击「测试连接」。

未配置 IBKR 时使用**内置模拟券商**：最新行情 + 2bp 滑点即时撮合，
佣金 `max(0.0035/股, $0.35, 名义×0.005%)`，状态持久化，同样穿过全部风控护栏。

### 6.2 行情接入（真实数据）

| 能力 | 实现 |
|---|---|
| 实时报价 | `reqTickersAsync` 批量快照（last/bid/ask/volume/high/low/open） |
| 历史 K 线 | `reqHistoricalDataAsync`，**自动分页**突破 IB 单次时长限制 |
| 行情类型 | `1` 实时 / `2` 冻结 / `3` 延迟（默认）/ `4` 延迟冻结；请求无价时自动切换重试 |
| 时段 | `use_rth` 可配，做日内策略建议保持「仅常规时段」 |
| 合约解析 | 指数 `^GSPC→SPX@CBOE`、`^VIX→VIX`；`BRK-B→BRK B`（IB 用空格） |

**分页拉取**是核心能力 —— IB 对「单次请求可覆盖的时长」有硬限制：

| 周期 | barSize | 单次最大时长 |
|---|---|---|
| 1m | `1 min` | 1 D |
| 5m | `5 mins` | 1 W |
| 15m / 30m | `15 mins` / `30 mins` | 1 M |
| 1h | `1 hour` | 1 Y |
| 1d / 1wk | `1 day` / `1 week` | 1 Y |

> 这是免费数据源无法替代的：yfinance 的 5 分钟数据只能回溯 60 天，
> 而 IBKR 可拉数年 —— 日内策略的回测才有统计意义。

在「行情分析」或「回测中心」把数据源切为 **IBKR 优先**；
若未连接会自动降级并在界面提示降级原因。

### 6.3 账户与持仓（真实盈亏）

- `account()` → `accountSummaryAsync`：NetLiquidation / TotalCashValue / BuyingPower /
  UnrealizedPnL / RealizedPnL / MaintMarginReq
- `positions()` → `portfolio()`：**真实市价、市值、浮盈**
  （不再把成本价当成现价，浮盈不再恒为 0）

### 6.4 下单与保护性委托

| 能力 | 说明 |
|---|---|
| 订单类型 | MKT / LMT / STP / STP_LMT，TIF 支持 DAY / GTC |
| 括号单 | 传入止盈/止损价时，主单成交后自动挂出（同 OCA 组互斥） |
| 成交回报 | 订阅 `orderStatusEvent`，状态与成交量自动写回本地订单表 |
| 今日成交 | `fills()` 拉取券商侧成交回报，用于与本地记录对账 |
| 撤单 | 单笔撤单 + **一键撤销全部挂单** |
| 保护性委托 | 实盘引擎建仓后自动在 IBKR 侧挂 GTC 止损单（必要时含止盈），平仓时自动撤销。**即使引擎进程掉线，持仓依然有保护。** |

---

## 七、行情数据源（多级降级）

| 优先级 | 来源 | 说明 |
|---|---|---|
| 1 | **IBKR** | 与实盘完全一致；分钟级可回溯数年（需已连接） |
| 2 | **本地缓存** | 按周期差异化 TTL（日线 6h、5m 线 5min） |
| 3 | **yfinance** | 日线/周线/小时/30m/15m/5m |
| 4 | **Stooq CSV** | 纯 HTTP 免费日线，无需 API Key |
| 5 | **合成行情** | 按标的哈希生成的确定性行情，仅离线演示；界面会显示醒目的「合成数据」警告 |

数据源偏好可在「系统设置 → 数据与缓存」切换，回测页也可按次指定。

---

## 八、行情分析

- **真 K 线图**（自绘 SVG）：蜡烛实体 + 影线、成交量副图、均线与布林带叠加、
  支撑/阻力参考线、十字光标 + OHLC 悬浮提示、可视区间拖动缩放
- 技术指标副图：RSI / MACD / ADX / 已实现波动率
- 关键价位：52 周高低、SMA50/200、ATR、枢轴价、自动识别的支撑阻力
- 指标读数：RSI、MACD 柱、ADX、±DI、布林 %B、量比、CMF、Z 分数、效率比、Hurst
- 区间收益、重点关注池（一键切换标的）

---

## 九、多策略对比与数据导出

**多策略对比**：同一时间区间、同一初始资金、同一成本与止损设置下并行回测最多 6 个策略，
输出归一化叠加净值曲线与指标对照表（收益/年化/夏普/索提诺/卡玛/回撤/胜率/盈亏比/换手）。
界面会提示：优先看夏普/卡玛（风险调整后收益）、最大回撤（你能否扛住）、换手率（成本侵蚀）。

**CSV 导出**：任意回测结果可导出交易明细、净值曲线、全部指标三类 CSV
（UTF-8 BOM，Excel 直接打开不乱码）。

**参数寻优**：网格搜索，目标函数可选夏普/索提诺/卡玛/收益/盈亏比。

---

## 十、组合优化（权重求解）

「参数寻优」搜的是策略参数，「组合优化」解的是**资金权重**：给定一篮子标的，
输出每个标的配多少仓位。入口在侧栏 **组合优化**。

### 10.1 优化目标（6 种）

| Key | 名称 | 适用场景 |
|---|---|---|
| `max_sharpe` | 最大夏普 | 默认。在约束下最大化「超额收益 / 波动」 |
| `min_variance` | 最小方差 | 只压波动。权重会集中在低波动资产 |
| `max_return` | 最大收益 | 纯追期望收益，**外推风险最高**，慎用 |
| `risk_parity` | 风险平价 | 各标的贡献风险相等，可叠加风险预算做主动倾斜 |
| `inverse_vol` | 波动率倒数 | 按 1/σ 分配，无需迭代、最稳健的解析近似 |
| `equal_weight` | 等权 | 1/N 基准。**优化前先看它** —— 很多「优化」打不过等权 |

### 10.2 估计方法

| 维度 | 选项 | 说明 |
|---|---|---|
| 协方差 | `ledoit_wolf`（默认） / `sample` / `ewma` | Ledoit-Wolf 向对角阵收缩，样本量不足时显著更稳 |
| 期望收益 | `shrunk`（默认） / `mean` / `ewma` | Jorion Bayes-Stein 收缩，把极端均值拉向最小方差组合收益 |

历史均值是最不可靠的输入。默认对期望收益做贝叶斯收缩，就是为了避免把过去的赢家配成重仓。

### 10.3 约束

- **盒约束**：单标的上限 / 下限、总仓位（可设 80% 保留现金）。
- **相关簇上限**：相关系数 ≥ 阈值（默认 0.85）的标的自动并为一簇，每簇总权重受限（默认 50%）。
  这是**伪分散防护** —— 同时持有 6 只半导体不是分散，只是一个加了杠杆的半导体仓位。
  簇由并查集识别，前端会列出检测到的簇及其实际权重。
- **风险预算**：仅对 `risk_parity` 生效，格式 `SPY:3, TLT:2, GLD:1`。

若「单标的上限 × 标的数 < 总仓位」，约束本身无解。此时求解器**会放宽上限到等权，并在界面上显式标注**
（`constraints.max_weight_relaxed = true` + 备注 + 前端黄色告警条），不会静默改参数。

### 10.4 实现（无 scipy / cvxpy 依赖）

本机未安装 `scipy` / `cvxpy`，全部算法在 `engine/optimizer.py` 内以纯 NumPy 实现：

| 环节 | 方法 |
|---|---|
| 收缩协方差 | Ledoit-Wolf 向对角阵收缩；用 `(X∘X)ᵀ(X∘X)/T` 恒等改写，避免构造 T×N×N 张量 |
| 收缩期望 | Jorion Bayes-Stein：`w = (N+2) / ((N+2) + T·(μ−μ₀1)ᵀΣ⁻¹(μ−μ₀1))` |
| 凸投影 | Dykstra 交替投影，求 `{Σw=total, lo≤w≤hi} ∩ {Σ_{i∈C}w_i ≤ cap}` 上的欧氏投影 |
| 目标求解 | Barzilai-Borwein 步长投影梯度上升（把 1500 次迭代降到 <150 次，单目标实测 81s → 0.3s） |
| 有效前沿 | 按平均波动归一化后扫描 λ ∈ [1e-3, 1e4]，只算一次并复用给切点组合定位 |

### 10.5 结果解读

- **有效标的数 = 1/HHI**：与名义标的数的差距，就是权重集中的程度。
- **分散化比率 = Σwᵢσᵢ / σp**：< 1 才说明真的降低了波动；≈ 1 说明标的高度相关，组合只是加权平均。
- **风险贡献**：权重 50% 但风险贡献 80% 的标的，才是组合真正的风险来源。
- 界面会在优化结果**打不过等权**时直接给出警告——这是最常被忽略、也最有价值的一条提示。

### 10.6 把权重变成策略

点击「另存为策略」会生成一个**恒定目标权重**的代码策略（每根 bar 输出同一组权重，引擎按权重再平衡），
保存在策略实验室，可直接回测或挂到实时引擎。生成的代码会经过 AST 白名单校验，不含 `import` / `lambda` / 文件 I/O。

结果可导出 CSV（使用 UTF-8 BOM，Excel 直接打开不乱码），字段含权重、逐标的年化收益/波动/夏普/回撤/风险贡献，
以及组合与等权基准的对照行。

---

## 十一、实盘交易三重锁

```
 ┌─────────────────────────────────────────────────────────────┐
 │  ① 环境变量开关   QD_ALLOW_LIVE_TRADING=true                │
 │     默认 false。未开启时，任何解锁与实盘下单请求直接 403。   │
 ├─────────────────────────────────────────────────────────────┤
 │  ② 运行时解锁                                               │
 │     在「实盘交易」页逐字输入 I UNDERSTAND THE RISK          │
 │     + 账户口令，通过后才会写入 live_unlocked 标记。          │
 ├─────────────────────────────────────────────────────────────┤
 │  ③ 逐笔风控护栏                                             │
 │     单标的限额 · 总敞口 · 持仓数量 · 最小/最大下单金额 ·     │
 │     日亏上限 · 回撤熔断 · 交易时段 · 白/黑名单 · 熔断开关    │
 │     任何一项不通过 → 拒绝 + 写审计日志（含实时引擎订单）     │
 └─────────────────────────────────────────────────────────────┘
```

**实时引擎**：解锁实盘后可选择以「模拟盘」或「实盘」模式运行策略。
实盘模式下建仓会自动挂保护性止损单，并支持：
- **一键停止全部引擎**（紧急制动，无需口令）
- **撤销全部挂单**（紧急制动，无需口令）

**熔断开关（Kill Switch）**：启用无需口令（紧急制动），解除需口令（防误触）。
启用后所有新订单被拒，**已有持仓不会被自动平仓**（由你决定处理方式）。

---

## 十二、安全设计

| 层面 | 措施 |
|---|---|
| 网络 | 默认仅绑定 `127.0.0.1`；CORS 白名单 |
| 认证 | bcrypt(cost=12) 加盐哈希；JWT(HS256) 放在 Authorization 头 |
| CSRF | 不使用 Cookie，天然免疫 |
| 限速 | 登录失败 8 次 / 5 分钟锁定 |
| 凭据 | 券商敏感字段用 Fernet 加密落库；密钥文件 `runtime/.secret` 权限 0600 |
| 响应头 | `X-Content-Type-Options` / `X-Frame-Options: DENY` / `Referrer-Policy` / `Permissions-Policy` / `COOP` |
| 输入 | 全部经 Pydantic 强校验；请求体上限 4 MB |
| 审计 | 登录、下单、策略变更、风控变更、实盘解锁、保护性委托全部留痕 |
| 沙箱 | 代码策略 AST 白名单 + 受限 builtins + 受限 `__import__` / `getattr` |

---

## 十三、常见问题

**Q：为什么持仓页显示的是「合成数据」/「降级」？**
外部数据源都不可用时，平台会用确定性合成行情兜底，并在界面明确标注。
看到警告时请不要用它做任何交易判断。

**Q：没有 IBKR 实时行情订阅能用吗？**
可以。行情类型默认用「延迟行情（15 分钟）」，回测、看盘、策略研究都正常。
但**日内策略不宜基于延迟价实盘成交** —— 要么订阅实时行情后把类型改为「实时」，
要么只用日线级别的策略。

**Q：回测收益能代表未来吗？**
不能。回测只用于排除明显无效的策略。请重点关注：参数平原（而非单点最优）、
跨时段稳健性、以及扣除成本后是否仍有超额。

**Q：为什么有些内置策略回测是亏的？**
因为那是真实结果。平台刻意不美化：`vwap_reversion` 在日线上 −61%、
`orb_breakout` 在日线上 −85%（因为它本质需要日内数据）。这些数字本身就是
有价值的结论 —— 提醒你不要把任何策略当作必然盈利的黑箱。

**Q：能直接下实盘单吗？**
不能，默认情况下完全不可能。需要你主动完成三重锁的前两道，这个设计是刻意的。

**Q：可以换用 LightGBM 吗？**
可以。`pip install lightgbm` 后，`ml_alpha_ridge` 会自动从内置岭回归升级为梯度提升，
无需改代码。

**Q：如何配置 LLM 深度解读？**
在 `backend/runtime/.env` 写入 `QD_AI_BASE_URL` 与 `QD_AI_API_KEY`（任意 OpenAI 兼容接口）
后重启。未配置时使用内置本地量化引擎，结论完全由行情计算得出。

**Q：数据能重置吗？**
删除 `backend/runtime/quantdesk.db` 即可恢复出厂状态（会丢失账户与策略配置）。
或只清空数据表以保留运行环境。

---

## 十四、免责声明

本软件为**技术工具**，不构成投资建议。量化策略的历史表现不代表未来收益，
任何交易决策及其后果由使用者自行承担。请务必先在模拟盘充分验证，
并用你能够承受损失的资金进行实盘交易。
