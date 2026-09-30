"""intel 调度器（FILE_SIZE_DEBT Batch F-1 从 intel.py 拆出）：

IntelScheduler（轻 tick 20s 刷新报价 + 重 tick 按周期任务/分析/对账/必读；
_live 字典暴露实时进度供管理端轮询）+ SCHEDULER 单例 + resume_on_startup。
"""
from __future__ import annotations

import datetime as dt
import threading
import time
from typing import Any

from sqlalchemy.orm import Session

from ..database import session_scope
from .common import IntelCompany, IntelRun, IntelSetting, log
from .settings import ensure_default_companies, ensure_settings, pinned_list, save_settings
from .bridge import bridge_log, pending_tasks
from .events import add_events
from .scrape import ai_scrape_companies
from .analysis import analysis_due_symbols, auto_analyze_symbol
from .verify import _run_row, verify_due_analyses
from .report import write_report


class IntelScheduler:
    """监控调度线程：轻 tick（20s 刷新报价/计数）+ 重 tick（按周期生成任务与自动分析）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_heavy = 0.0
        # 实时运行状态（纯内存，GET /intel/live 每 2~3s 轮询）：
        # 监控在后台跑什么（抓取/分析哪家、进度几分之几）必须可见，
        # 否则用户开了监控看不到任何动静，会以为「跑了但没数据回来」。
        self._live: dict[str, Any] = {"phase": "idle", "note": "", "progress": 0, "total": 0, "ts": None}

    def _live_set(self, **kw: Any) -> None:
        self._live.update(kw)
        self._live["ts"] = dt.datetime.now(dt.timezone.utc).isoformat()

    @property
    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def current_run(self, db: Session | None = None) -> IntelRun | None:
        own = db is None
        if own:
            from ..database import SessionLocal

            db = SessionLocal()  # type: ignore[assignment]
        try:
            row = (
                db.query(IntelRun).filter(IntelRun.status == "running")  # type: ignore[union-attr]
                .order_by(IntelRun.id.desc()).first()
            )
            if row and own:
                db.expunge(row)  # type: ignore[union-attr]
            return row
        finally:
            if own:
                db.close()  # type: ignore[union-attr]

    def start(self, interval_minutes: int | None = None, auto_analyze: bool | None = None) -> int:
        """一键开启：创建 run + 启动线程。已在运行则返回现有 run_id。"""
        with self._lock:
            st = ensure_settings()
            if interval_minutes is not None:
                st = save_settings(interval_minutes=interval_minutes)
            if auto_analyze is not None:
                st = save_settings(auto_analyze=auto_analyze)
            cur = self.current_run()
            if self.alive:
                if cur:
                    return cur.id
                # 线程活着但 run 丢失（异常场景）：补建 run，绝不重复开线程
                with session_scope() as db:
                    run = IntelRun(interval_minutes=st.interval_minutes,
                                   auto_analyze=st.auto_analyze, note="run 丢失后补建")
                    db.add(run)
                    db.flush()
                    return run.id
            # 清理僵尸 running（服务重启残留）
            if cur:
                self._close_run(cur.id, status="stopped", note="服务重启前遗留批次，已自动关闭")
                cur = None
            with session_scope() as db:
                run = IntelRun(
                    interval_minutes=st.interval_minutes, auto_analyze=st.auto_analyze,
                    note="监控开启",
                )
                db.add(run)
                db.flush()
                run_id = run.id
            with session_scope() as db:
                row = db.get(IntelSetting, 1)
                row.monitor_enabled = True
            self._stop.clear()
            self._last_heavy = 0.0
            self._thread = threading.Thread(target=self._loop, name="intel-scheduler", daemon=True)
            self._thread.start()
            from ..state import log as audit_log

            audit_log("intel_start", "INFO", f"AI 情报监控开启（run #{run_id}，周期 {st.interval_minutes} 分钟）")
            return run_id

    def stop(self) -> dict[str, Any]:
        """一键截止：停线程 + 关 run + 报告落盘。"""
        with self._lock:
            self._stop.set()
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=4)
            self._thread = None
            cur = self.current_run()
            result: dict[str, Any] = {"stopped": bool(cur)}
            if cur:
                self._close_run(cur.id, status="finished", note="手动截止")
                result["run_id"] = cur.id
                result["report_path"] = write_report(cur.id)
            with session_scope() as db:
                row = db.get(IntelSetting, 1)
                row.monitor_enabled = False
            from ..state import log as audit_log

            audit_log("intel_stop", "INFO", "AI 情报监控截止，报告已归档")
            return result

    # ----------------------------------------------------------------
    def _close_run(self, run_id: int, *, status: str, note: str) -> None:
        with session_scope() as db:
            run = db.get(IntelRun, run_id)
            if run and run.status == "running":
                run.status = status
                run.ended_at = dt.datetime.now(dt.timezone.utc)
                run.note = note

    def _loop(self) -> None:
        st = ensure_settings()
        heavy_every = max(300, st.interval_minutes * 60)
        while not self._stop.wait(20):
            try:
                self._tick(heavy_every)
            except Exception:  # noqa: BLE001 —— 任何异常都不能杀死调度线程
                log.exception("Intel 调度 tick 异常")

    def _tick(self, heavy_every: float) -> None:
        run = self.current_run()
        if run is None:
            return
        run_id, interval = run.id, run.interval_minutes
        # 轻活：刷新观察标的报价（供简报与报告使用）+ 价格异动联动
        try:
            from ..data_provider import get_quotes

            with session_scope() as db:
                syms = [c.symbol for c in db.query(IntelCompany).filter(IntelCompany.enabled.is_(True)).all()]
            if syms:
                self._check_surge(get_quotes(syms) or [], run_id)
        except Exception:  # noqa: BLE001
            pass
        now = time.time()
        if now - self._last_heavy < heavy_every:
            with session_scope() as db:
                r = db.get(IntelRun, run_id)
                if r and r.status == "running":
                    r.tick_count = (r.tick_count or 0) + 1
                    r.last_tick_at = dt.datetime.now(dt.timezone.utc)
            return
        self._last_heavy = now
        st = ensure_settings()
        # 重活 1：任务整备（把到期公司标记为待抓取——由 bridge/poll 暴露给 Agent）
        with session_scope() as db:
            tasks = pending_tasks(db, st.interval_minutes)
            r = db.get(IntelRun, run_id)
            if r and r.status == "running":
                r.tick_count = (r.tick_count or 0) + 1
                r.last_tick_at = dt.datetime.now(dt.timezone.utc)
        # 重活 1.5：内置 AI 抓取（多源新闻 → 关键节点事件），AI 已配置且开关打开时自动运行
        if st.ai_scrape:
            try:
                from ..ai_analyst import ai_configured

                if ai_configured():
                    def _scrape_progress(done: int, total: int, note: str) -> None:  # noqa: ANN001
                        self._live_set(phase="scrape", progress=done, total=total, note=note)

                    # 重点标的优先（用户指定 = 重点盯，不是只对手动抓取生效）：
                    # 每轮先抓 pinned（≤4 家），再补 3 家到期轮转 —— 2026-09-30 ORCL 教训。
                    pinned = pinned_list(st)[:4]
                    if pinned:
                        with session_scope() as db:
                            due = [t["symbol"] for t in pending_tasks(db, st.interval_minutes)]
                        batch = pinned + [x for x in due if x not in pinned][:3]
                        results = ai_scrape_companies(symbols=batch, with_analysis=False,
                                                      run_id=run_id, progress_cb=_scrape_progress)
                    else:
                        results = ai_scrape_companies(limit=3, with_analysis=False, run_id=run_id,
                                                      progress_cb=_scrape_progress)
                    for r in results:
                        if r.get("inserted"):
                            log.info("Intel AI 抓取 %s：+%s 事件（新闻 %s 条）",
                                     r.get("symbol"), r.get("inserted"), r.get("news_n"))
                        elif r.get("error"):
                            log.warning("Intel AI 抓取 %s 失败：%s", r.get("symbol"), r.get("error"))
                    self._live_set(phase="scrape_done", note="本轮抓取完成")
                else:
                    self._live_set(phase="skipped", note="AI 未配置，本轮跳过自动抓取（到「设置 → AI 分析」配置后生效）")
            except Exception:  # noqa: BLE001 —— 抓取失败不阻塞后续分析
                log.exception("Intel AI 抓取轮失败")
        # 重活 2：自动分析（LLM 优先 / 本地兜底），每轮最多 3 家，避免阻塞
        if st.auto_analyze:
            from ..database import SessionLocal

            db2 = SessionLocal()
            try:
                due = analysis_due_symbols(db2, st.interval_minutes, limit=3)
            finally:
                db2.close()
            for i, sym in enumerate(due):
                if self._stop.is_set():
                    break
                self._live_set(phase="analyze", progress=i, total=len(due), note=f"正在分析 {sym}（事件面 + 量化快照）…")
                try:
                    row = auto_analyze_symbol(sym, run_id)
                    if row:
                        log.info("Intel 自动分析 %s → %s（%s）", sym, row.recommendation, row.engine)
                except Exception:  # noqa: BLE001
                    log.exception("Intel 自动分析失败 %s", sym)
        # 重活 3：建议验证对账（满 7 天的建议 vs 实际涨跌），每轮最多 8 条
        try:
            n = verify_due_analyses(limit=8)
            if n:
                log.info("Intel 到期建议验证 %s 条", n)
        except Exception:  # noqa: BLE001
            log.exception("Intel 建议验证失败")
        # 重活 4：每日必读清单（**纯规则、不调 LLM**）—— 这是「AI 主动分析并记录」
        # 的确定性部分：每轮把当日事件按重要度重排并落库留痕，用户打开页面即刻可读。
        # 放在最后：即便它失败（例如行情源不可用导致时机区间缺失）也不影响抓取与建议。
        try:
            from .. import intel_digest

            digest = intel_digest.build_digest()
            intel_digest.save_digest(digest, generated_by="scheduler")
            log.info("Intel 每日必读已更新：必读 %s 条 / 候选 %s 条",
                     (digest.get("totals") or {}).get("top"), (digest.get("totals") or {}).get("events"))
        except Exception:  # noqa: BLE001
            log.exception("Intel 每日必读生成失败")
        self._live_set(phase="idle", progress=0, total=0,
                       note=f"本轮完成 · 下轮约 {interval} 分钟后（数据一到每日必读会即时刷新，无需等下轮）")

    # ----------------------------------------------------------------
    def _check_surge(self, quotes: list[dict], run_id: int | None) -> None:
        """价格异动联动（2026-09-30 ORCL 教训）。

        旧形态的致命盲区：情报系统只看新闻、完全不看价格 —— 标的盘中暴涨/暴跌时
        没有任何机制察觉，更不会去问「为什么」。现在轻 tick（20s）比对现价与昨收：
          · |涨跌幅| >= surge_pct（默认 3%）→ 自动记一条「股价异动」事件入库
            （影响度按幅度分档，7%+ 记 5★）→ 必读实时刷新 → 立即触发该标的 AI 归因分析
            （结合近期事件回答「为什么动」）→ 台账留痕。
        去重：title 含日期，同一标的同日同方向只记一次（add_events dedupe 天然挡住）。
        事件触发 refresh_async("events") / 分析触发 ("analysis") —— 数据一到必读即更新。
        """
        if not quotes:
            return
        st = ensure_settings()
        try:
            th = float(st.surge_pct or 3.0)
        except (TypeError, ValueError):
            th = 3.0
        for q in quotes:
            try:
                sym = str(q.get("symbol") or "").strip().upper()
                px = float(q.get("price") or 0)
                pc = float(q.get("prev_close") or 0)
            except Exception:  # noqa: BLE001
                continue
            if not sym or px <= 0 or pc <= 0:
                continue
            chg = (px / pc - 1) * 100
            if abs(chg) < th:
                continue
            today = dt.date.today().isoformat()
            direction = "大涨" if chg > 0 else "大跌"
            res = add_events([{
                "symbol": sym,
                "title": f"股价异动：{today} 盘中{direction}",
                "summary": (f"价格监控发现 {sym} 盘中涨跌 {chg:+.2f}%（现价 {px:g}，昨收 {pc:g}，"
                            f"阈值 ±{th:g}%）。本条由价格监控自动记录，AI 分析将结合近期事件给出归因。"),
                "category": "other",
                "sentiment": "positive" if chg > 0 else "negative",
                "impact": 5 if abs(chg) >= 7 else (4 if abs(chg) >= 5 else 3),
                "stage": "",
                "occurred_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"),
                "source_name": "quantdesk-price-watch",
            }], agent="builtin-ai", run_id=run_id)
            if not res.get("inserted"):
                continue  # 今日已记过（重复）—— 不重复分析
            bridge_log("builtin-ai", "surge",
                       f"{sym} {chg:+.2f}% · 已记异动事件并触发 AI 归因分析（阈值 ±{th:g}%）")
            log.info("Intel 价格异动 %s %s%+.2f%% —— 已入库并触发归因分析", sym, direction, chg)
            from .. import intel_digest

            intel_digest.refresh_async("surge")
            if st.auto_analyze:
                try:
                    row = auto_analyze_symbol(sym, run_id)
                    if row:
                        log.info("Intel 异动归因 %s → %s（%s）", sym, row.recommendation, row.engine)
                except Exception:  # noqa: BLE001
                    log.exception("Intel 异动归因分析失败 %s", sym)

    def status(self) -> dict[str, Any]:
        st = ensure_settings()
        cur = self.current_run()
        from ..ai_analyst import ai_configured

        return {
            "scheduler_alive": self.alive,
            "monitor_enabled": bool(st.monitor_enabled),
            "interval_minutes": st.interval_minutes,
            "auto_analyze": bool(st.auto_analyze),
            "ai_scrape": bool(st.ai_scrape),
            "llm_configured": ai_configured(),
            "current_run": _run_row(cur) if cur else None,
            "live": dict(self._live),
        }



SCHEDULER = IntelScheduler()


def resume_on_startup() -> None:
    """服务启动：按持久化开关恢复监控；僵尸 running 批次自动收尾。"""
    try:
        ensure_default_companies()
        st = ensure_settings()
        cur = SCHEDULER.current_run()
        if cur and not SCHEDULER.alive:
            SCHEDULER._close_run(cur.id, status="stopped", note="服务重启，批次自动收尾")
        if st.monitor_enabled:
            run_id = SCHEDULER.start()
            log.info("Intel 监控已自恢复（run #%s）", run_id)
    except Exception:  # noqa: BLE001
        log.exception("Intel 监控自恢复失败")

