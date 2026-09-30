# AI 情报中心 · 入库失败可观测 + 重入库机制（设计）

> 落盘日期：2026-09-30  
> 触发：用户反馈「点击抓取后 23 家全部报错入库失败」—— 实际根因是 LLM 网关 503，但暴露出 **log ok 字段错标** + **失败 = 真丢无重试** 两个系统性问题。

## 0. 根因复盘

```
HTTPStatusError: Server error '503 Service Unavailable'
  for url 'http://127.0.0.1:16689/v1/chat/completions'
```

- **触发**：上轮把默认模型改为 `监hy4-perview`，该模型在用户 LLM 网关（`127.0.0.1:16689`）未注册 → 网关 503。
- **每家表现**：新闻抓取（Google News RSS + yfinance + SEC）成功 15 条；LLM 打标调 `/v1/chat/completions` 失败；事件 0 条入库；bridge_log `ok=True`（**BUG**，让前端看不出失败）。
- **影响**：监控每 30 分钟一轮 → 每轮 23 家全失败 → 累计 100+ 条失败 log，用户得从 detail 字符串里 grep `失败：` 才能找到。
- **临时回退**：`state.set_ai_settings({"model": "cn:glm-5.3-flash"})`（已 work 的模型）即可恢复，1 秒生效。

## 1. 现状缺陷清单（为什么"应该开"这个设计）

| # | 缺陷 | 影响 | 严重度 |
|---|---|---|---|
| 1 | `bridge_log` 默认 `ok=True`，失败时仍标 True | 前端 IngestLog 配色全 emerald，看不出失败家 | 中 |
| 2 | 失败家**没有任何 raw_news 暂存** | 重抓同 15 条新闻 → 又走 LLM → 又失败，永不收敛 | 高 |
| 3 | 没有「失败计数 + 失败符号集合」接口 | 重试时不知道要重试哪几家，必须前端自己维护 | 中 |
| 4 | ai_scrape 批量跑完后不会**整批兜底 refresh_async**（上轮提过，未落） | 一次性 23 家全成功时偶发必读不更新 | 低 |
| 5 | 前端 IngestLog `detail` 截断 100 字，遇长堆栈 trace 看不到关键错误码 | 排障时间 | 低 |
| 6 | 没有"上次成功 vs 失败"的失败率视图 | 用户不知道是网关抽风还是模型没了 | 中 |

## 2. 设计方案

### 2.1 log 修复（小，10 行）

**`app/intel/bridge.py::bridge_log`** 改成接收可选 `ok` 参数，默认按 `error is None` 判定：

```python
def bridge_log(agent: str, action: str, detail: str, ok: bool = True) -> None:
    # 旧: db.add(IntelBridgeLog(..., ok=True))
    # 新: db.add(IntelBridgeLog(..., ok=bool(ok and not _looks_failed(detail))))
```

调用点 `app/intel/scrape.py:248`：
```python
err = r.get("error")
bridge_log("builtin-ai", "scrape",
    f"{sym} · ..."
    + (f" · 模型 {model}" if model else "")
    + (f" · 失败：{str(err)[:200]}" if err else ""),
    ok=not err and r.get("inserted", 0) > 0,    # ← 新增：业务真成功才 ok
)
```

**效果**：前端 IngestLog 失败家变红；监控实时状态可读；用户不再被"绿色但实际失败"误导。

### 2.2 raw_news 缓存表 + 重入库（90 行代码 + 1 张表）

**新表 `intel_raw_news`**（在 `app/models.py` + `database.py::_MIGRATE_COLUMNS` 注册新表）：

```python
class IntelRawNews(Base):
    __tablename__ = "intel_raw_news"
    id          = Column(Integer, primary_key=True)
    symbol      = Column(String(16), nullable=False, index=True)
    published_at = Column(String(32), default="")        # 新闻原发布时间
    headline    = Column(String(300), default="", nullable=False)
    summary     = Column(String(1000), default="")
    source      = Column(String(64), default="")
    source_url  = Column(String(600), default="")
    fetched_at  = Column(DateTime, nullable=False, default=now_utc)
    used_for_event_id = Column(Integer, nullable=True, index=True)  # 入库后回填
    status      = Column(String(16), default="fresh", index=True)  # fresh / failed / retrying / failed_final / used
    retry_count = Column(Integer, default=0)
    last_error  = Column(String(200), default="")
    __table_args__ = (
        UniqueConstraint("symbol", "source_url", name="uq_raw_news_symbol_url"),
        Index("ix_raw_news_status_fetched", "status", "fetched_at"),
    )
```

**写入点**（`app/intel/scrape.py::ai_harvest_events`）：fetch_news 后**无论 LLM 成败**全部 upsert：

```python
def _upsert_raw_news(db, symbol: str, items: list[dict], status: str, err: str = "") -> int:
    n = 0
    for it in items:
        if not (it.get("source_url") and it.get("headline")):
            continue
        row = db.query(IntelRawNews).filter_by(symbol=symbol, source_url=it["source_url"]).first()
        if row:
            row.status, row.last_error = status, err[:200]
            row.fetched_at = dt.datetime.utcnow()
        else:
            db.add(IntelRawNews(symbol=symbol, headline=it["headline"][:300],
                summary=(it.get("summary") or "")[:1000], source=(it.get("source") or "")[:64],
                source_url=it["source_url"], published_at=it.get("published_at", "")[:32],
                status=status, last_error=err[:200]))
    db.flush()
    return n
```

LLM 失败时：raw_news status=`failed`，`last_error` = `503 Service Unavailable`（截断 200）。
LLM 成功时：回填 `used_for_event_id` + status=`used`。

### 2.3 重入库端点

**`POST /api/intel/scrape/retry`**（在 `app/api/intel.py`）：

```python
@router.post("/scrape/retry")
def scrape_retry(payload: RetryRequest, user: CurrentUser) -> dict:
    """重试失败抓取：
      · 默认行为：取近 60 分钟 status=failed 且 retry_count<3 的所有家，
        复用 raw_news（≤30 分钟内的缓存）→ 直接打标入库，不重新抓新闻
      · payload.symbols 指定时只重试这些
      · payload.force=True 时强制重抓新闻（覆盖缓存）
    返回 {retried, succeeded, failed, errors:[{symbol, error}]}
    """
```

后端 jobs 调度（复用现有 `engine/jobs.py` 后台任务模式，避免阻塞）：
```python
job = jobs.submit("intel_scrape_retry", symbols, force=payload.force)
return {"job_id": job.id}
```

前端轮询 job 进度同 ai_scrape 模式。

### 2.4 前端"一键重试"按钮

`frontend/src/components/intel/IngestLog.tsx`：台账区底部新增：

```tsx
{hasFailure && (
  <button
    className="mt-1 inline-flex items-center gap-1 rounded bg-rose-50 px-2 py-1 text-[11px] text-rose-700 hover:bg-rose-100"
    onClick={() => onRetryFailures()}
  >
    <RefreshCw className="h-3 w-3" /> 失败 {failedCount} 家 · 一键重试
  </button>
)}
```

`onRetryFailures` 由 MonitorBar 接到：调 `POST /api/intel/scrape/retry` → 拿到 `job_id` → 沿用现有 scrapeJob 轮询器显示进度。

## 3. 字段 / 端点清单

### 3.1 数据库

| 操作 | 表/列 | 备注 |
|---|---|---|
| 新表 | `intel_raw_news` | 9 列 + 2 索引/约束 |
| 修改 | 无 | 仅新增 |

### 3.2 API

| 端点 | 方法 | 用途 |
|---|---|---|
| `/api/intel/scrape/retry` | POST | 重试失败抓取（详见 §2.3）|
| `/api/intel/scrape-log` | GET | 现有；前端配合新字段渲染 |
| `/api/intel/ingest-stats` | GET（可选） | 失败家数 + 失败符号列表（轻量聚合）|

### 3.3 前端

| 改动 | 文件 | 行数 |
|---|---|---|
| `<IngestLog>` 加失败计数 + 重试按钮 | `IngestLog.tsx` | ~25 |
| `<MonitorBar>` 接 `onRetryFailures` | `MonitorBar.tsx` | ~20 |

## 4. 实施顺序（建议一次性落）

1. **日志 ok 字段修复**（10 行，必上）：立即让用户能看到哪些家失败。
2. **临时回退默认模型**为 `cn:glm-5.3-flash`：让当前抓取恢复工作。
3. **新表 intel_raw_news** + 写入点（30 行 + migration）。
4. **scrape/retry 端点**（60 行，复用 ai_harvest_events，节流 raw_news）。
5. **前端"一键重试"按钮**（45 行，三组件）。
6. **新增 intel 节自检**（20 行）：raw_news upsert/retry/dedupe 三个断言。

总计 ~165 行新代码 + 1 张表 + 2 个端点 + 1 个前端按钮；自检进 `tests/run_checks.py intel` 节。

## 5. 立即可用的临场视角（不写代码也能用）

无需改任何代码，**让用户现在就能看到 23 家失败的根因 + 临时恢复**：

```python
# 看实时失败：
from app.database import session_scope
from app.models import IntelBridgeLog
with session_scope() as db:
    for r in db.query(IntelBridgeLog).filter(
        IntelBridgeLog.action == "scrape",
        IntelBridgeLog.detail.like("%失败%"),
    ).order_by(IntelBridgeLog.id.desc()).limit(10):
        print(r.ts, r.detail[:160])

# 临时回退（可选）：
from app import state
state.set_ai_settings({"model": "cn:glm-5.3-flash"})
```

## 6. 不在本设计内（避免蔓延）

- 抓取本身的多源新闻容错（已实现 stale-while-revalidate）
- LLM 调用 503/timeout 重试（已有 60s 内补试一次；建议扩到 3 次 / 指数退避，但本次不做）
- 失败家自动降级到 local engine（语义复杂，本次不做）

## 7. 落地预期收益

- **可观测性**：从「绿色但失败」变成「红 + 失败原因 + 一键重试」
- **数据不丢**：raw_news 缓存 30 分钟，网关短暂抽风期间抓到的新闻不会随 LLM 失败蒸发
- **恢复速度**：网关恢复后 1 次点击重试 → 23 家立即补齐入库
- **失败可治**：retry_count 累加 + failed_final 状态防止失败死循环