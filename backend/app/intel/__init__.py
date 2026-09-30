"""
AI 情报中心（Intel Center）
===========================
把「互联网信息抓取 → 美股核心公司关键节点 → AI 买入建议」产品化为一条
可持续运行的流水线：

  B. 内置 AI 全自动管道（配置 AI 后无需任何外部 Agent，默认开启）
     调度器每轮对到期公司执行：多源新闻抓取（finnhub/yahoo-rss/ibkr）→ LLM 把新闻
     结构化为「公司关键节点」事件入库 → 结合事件面与量化快照产出买入建议。
     来源真实性由架构保证：occurred_on/source_name/source_url 一律继承新闻条目，
     LLM 只做挑选与打标，不触碰来源字段（杜绝编造链接）。
  C. 本地量化引擎（零配置兜底）
     未配置 LLM 时完全基于行情数据给出建议，保证监控开启后始终有产出。
  D. 外部 AI Agent（WorkBuddy / Claude Code / Codex ...）
     通过 /api/intel/bridge/* 用 X-Intel-Token 领任务（poll / brief）、
     提交事件节点（events）与买入建议（analysis）。与交易账户完全隔离，
     定位为「能联网深度搜索」的增强通道。

一键开启/截止：
  POST /api/intel/monitor/start  → 生成 IntelRun(running) + 启动调度线程
  POST /api/intel/monitor/stop   → 关闭线程 + run 置 finished + Markdown 报告落盘
服务重启后 monitor_enabled=true 自动恢复监控（resume_on_startup）。

拆包说明（FILE_SIZE_DEBT Batch F-1）：intel.py 1900+ 行拆为 9 个域文件，
本文件只做 re-export —— `from app.intel import X` 与 `intel.X` 属性访问保持不变。
"""
from __future__ import annotations

from .common import (  # noqa: F401
    EVENT_CATEGORIES,
    EVENT_STAGES,
    SENTIMENTS,
    RECOMMENDATIONS,
    HORIZONS,
    REC_CN,
    REPORT_DIR,
    IntelAnalysis,
    IntelBridgeLog,
    IntelCompany,
    IntelEvent,
    IntelRun,
    IntelSetting,
    log,
)
from .settings import (  # noqa: F401
    DEFAULT_COMPANIES,
    _gen_token,
    chain_list,
    ensure_default_companies,
    ensure_settings,
    pinned_list,
    save_settings,
)
from .bridge import (  # noqa: F401
    bridge_base_url,
    bridge_guide,
    bridge_log,
    pending_tasks,
    reset_bridge_token,
)
from .events import (  # noqa: F401
    _event_row,
    _norm_event_time,
    _norm_title,
    _seen_add,
    add_events,
    make_dedupe_key,
)
from .scrape import (  # noqa: F401
    _EVENT_HARVEST_PROMPT,
    _touch_scrape,
    ai_harvest_events,
    ai_scrape_companies,
    breaker_status,
    scrape_batch,
)
from .timeline import (  # noqa: F401
    _EVENT_FACE_DAILY_CAP,
    _EVENT_FACE_DAYS,
    _EVENT_FACE_WEIGHT,
    _LOCAL_REC_MAP,
    _STAGE_WEIGHT,
    _event_face,
    _event_face_weights,
    _rec_from_score,
    _vol_position_scale,
    timeline,
)
from .verify import (  # noqa: F401
    _CAL_BUCKETS,
    _HOLD_TOLERANCE,
    _VERIFY_BENCHMARK,
    _VERIFY_TOLERANCE,
    _brier,
    _calibrate,
    _close_on_or_before,
    _hit_for,
    _hold_hit,
    _run_row,
    verify_due_analyses,
    verify_stats,
    window_days_for,
    VERIFY_WINDOW_DAYS,
)
from .report import _render_report, write_report  # noqa: F401
from .analysis import (  # noqa: F401
    _EARNINGS_TTL_FAIL,
    _EARNINGS_TTL_OK,
    _LLM_ANALYSIS_PROMPT,
    _CRITIC_PROMPT,
    _agent_track,
    _analysis_row,
    _earnings_cache,
    _earnings_date,
    _llm_analysis,
    _local_analysis,
    _sanitize_analysis,
    add_analysis,
    analysis_due_symbols,
    auto_analyze_symbol,
    company_brief,
)
from .scheduler import SCHEDULER, IntelScheduler, resume_on_startup  # noqa: F401
