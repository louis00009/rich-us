"""数据库引擎与会话（SQLite + WAL）。"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import DB_PATH

log = logging.getLogger("quantdesk.db")


class Base(DeclarativeBase):
    pass


engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False, "timeout": 30},
    future=True,
    # 连接池扩容：实时抓取模式下（调度 tick + alerts/scan + 前端轮询并发），
    # 默认 5+10 曾被占满导致全站 500（QueuePool timeout）。
    pool_size=20,
    max_overflow=30,
    pool_timeout=60,
    pool_pre_ping=True,
)


@event.listens_for(engine, "connect")
def _sqlite_pragma(dbapi_conn, _rec):  # noqa: ANN001
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """事务上下文：正常提交，异常回滚。"""
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_db() -> Iterator[Session]:
    """FastAPI 依赖。"""
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def init_db() -> None:
    from . import models  # noqa: F401  确保模型注册

    Base.metadata.create_all(engine)
    _migrate()


_MIGRATE_COLUMNS: dict[str, list[tuple[str, str]]] = {
    # 轻量迁移：create_all 不会给已存在的表加列，这里按需 ALTER。
    # （风险配置新增字段必须同步 RISK_COLUMNS 白名单，否则写入被静默丢弃。）
    "risk_config": [
        ("allow_short", "BOOLEAN DEFAULT 0"),
        ("allow_extended_hours", "BOOLEAN DEFAULT 0"),
        ("hk_max_gross_exposure_pct", "FLOAT DEFAULT 100.0"),
        ("max_daily_orders", "INTEGER DEFAULT 0"),
        ("max_orders_per_minute", "INTEGER DEFAULT 0"),
    ],
    "orders": [("currency", "VARCHAR(8) DEFAULT ''")],
    "fills": [("currency", "VARCHAR(8) DEFAULT ''")],
    "company_profiles": [("name_cn", "TEXT DEFAULT ''"), ("market_cap", "REAL DEFAULT 0")],
    "intel_events": [("stage", "VARCHAR(16) DEFAULT ''"), ("occurred_at", "VARCHAR(16) DEFAULT ''")],
    "intel_companies": [("note", "TEXT DEFAULT ''")],
    "intel_settings": [("ai_scrape", "BOOLEAN DEFAULT 1")],
    "intel_analyses": [
        ("based_on_events", "TEXT DEFAULT '[]'"),
        ("event_score", "FLOAT"),
        ("outcome_window_days", "INTEGER DEFAULT 7"),
        ("outcome_checked_at", "DATETIME"),
        ("outcome_price", "FLOAT"),
        ("outcome_return", "FLOAT"),
        ("outcome_hit", "BOOLEAN"),
        ("outcome_benchmark", "FLOAT"),
    ],
    # 复现字段（2026-09-29）：历史回测缺基准/成本/周期/数据源，无法 100% 复现
    "backtest_runs": [
        ("benchmark", "VARCHAR(16) DEFAULT 'SPY'"),
        ("commission_bps", "FLOAT DEFAULT 1.0"),
        ("slippage_bps", "FLOAT DEFAULT 2.0"),
        ("interval", "VARCHAR(8) DEFAULT '1d'"),
        ("data_source", "VARCHAR(16) DEFAULT ''"),
    ],
}


# P2-1：高频过滤列补索引。`create_all` 只建「缺失的表」，**不会给已存在的表补索引** ——
# 所以这里显式 CREATE INDEX IF NOT EXISTS，保证老库也能吃到（新库由 index=True 建，
# 索引名与 SQLAlchemy 默认的 ix_<表>_<列> 一致，不会重复创建）。
_MIGRATE_INDEXES: list[tuple[str, str, str]] = [
    ("orders", "ix_orders_mode", "mode"),
    ("orders", "ix_orders_status", "status"),
    ("engine_runs", "ix_engine_runs_strategy_id", "strategy_id"),
    ("engine_runs", "ix_engine_runs_status", "status"),
    ("engine_runs", "ix_engine_runs_mode", "mode"),
    ("ai_proposals", "ix_ai_proposals_order_id", "order_id"),
]


# 「预期内」的 DDL 失败标记：这些表示「对象已存在」，是迁移的正常路径，静默跳过。
# ⚠️ 只认这几类 —— 其余一律当**真实失败**上报（见 _migrate 的说明）。
_BENIGN_DDL_MARKERS = ("duplicate column name", "already exists", "duplicate index")


def _is_benign_ddl_error(msg: str) -> bool:
    low = msg.lower()
    return any(k in low for k in _BENIGN_DDL_MARKERS)


def _missing_columns(conn) -> list[str]:  # noqa: ANN001
    """以**库的真实结构**为准，列出 `_MIGRATE_COLUMNS` 里还没到位的列。

    为什么不直接信 ALTER 的返回：ALTER 可能报了个看不懂的错、也可能「报错但其实成了」。
    收尾核对 `PRAGMA table_info` 才是判据 —— 这也是排查老库怪错时唯一可靠的手段。
    """
    out: list[str] = []
    for table, cols in _MIGRATE_COLUMNS.items():
        try:
            rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
        except Exception as exc:  # noqa: BLE001
            out.append(f"{table}（无法读取表结构：{type(exc).__name__}）")
            continue
        if not rows:
            out.append(f"{table}（表不存在）")
            continue
        have = {r[1] for r in rows}   # PRAGMA table_info 列序：cid, name, type, ...
        out.extend(f"{table}.{name}" for name, _ in cols if name not in have)
    return out


def _migrate() -> None:
    """轻量迁移：`create_all` 不会给**已存在**的表补列/索引，这里按需 ALTER / CREATE INDEX。

    ⚠️ 历史缺陷（2026-09-29 修）：这里曾是 `except Exception: pass`，把**所有**异常都吞掉。
    本意只是跳过「列已存在」，但真实失败（DDL 写错、库被锁、磁盘错）同样被静默吞掉 ——
    结果是**列缺失却无人知晓**，下游表现为各种莫名其妙的报错，排查时只能靠手工
    `PRAGMA table_info` 核对（这个坑被记录了很久）。

    现在的策略：
      ① 只有 `_BENIGN_DDL_MARKERS` 里那几类「已存在」才静默跳过；
      ② 其余失败**带真实异常文本**记 WARNING，不再无声无息；
      ③ 收尾用 `_missing_columns()` 逐个校验期望列**是否真的到位**，缺任何一个就抛
         RuntimeError —— 启动即失败，宁可起不来，也不带病运行。
    """
    from sqlalchemy import text

    problems: list[str] = []
    with engine.connect() as conn:
        for table, cols in _MIGRATE_COLUMNS.items():
            for name, ddl in cols:
                try:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                    conn.commit()
                except Exception as exc:  # noqa: BLE001
                    if _is_benign_ddl_error(str(exc)):
                        continue          # 列已存在 = 迁移的正常路径
                    problems.append(f"{table}.{name}: {type(exc).__name__}: {str(exc)[:160]}")
        for table, name, col in _MIGRATE_INDEXES:
            try:
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({col})"))
                conn.commit()
            except Exception as exc:  # noqa: BLE001
                if _is_benign_ddl_error(str(exc)):
                    continue
                problems.append(f"索引 {name}: {type(exc).__name__}: {str(exc)[:160]}")

        # ③ 判据以库的真实结构为准（ALTER 报的错可能是误报，也可能「报错但已生效」）
        missing = _missing_columns(conn)

    if problems:
        log.warning("迁移期出现非预期失败（下面按库的真实结构复核）：%s", "；".join(problems))
    if missing:
        raise RuntimeError(
            "数据库迁移后仍缺列：" + "、".join(missing)
            + "。请检查 `_MIGRATE_COLUMNS` 的 DDL 是否正确、库文件是否可写；"
            "带病运行会让下游报错极难定位（历史上正是被静默吞掉的那个坑）。"
        )
    if problems:
        log.warning("上述失败已复核：期望列均已到位，判定为「已存在」类正常跳过。")
