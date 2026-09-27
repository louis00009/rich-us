"""数据库引擎与会话（SQLite + WAL）。"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import DB_PATH


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
    "intel_events": [("stage", "VARCHAR(16) DEFAULT ''")],
    "intel_analyses": [
        ("based_on_events", "TEXT DEFAULT '[]'"),
        ("event_score", "FLOAT"),
        ("outcome_window_days", "INTEGER DEFAULT 7"),
        ("outcome_checked_at", "DATETIME"),
        ("outcome_price", "FLOAT"),
        ("outcome_return", "FLOAT"),
        ("outcome_hit", "BOOLEAN"),
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


def _migrate() -> None:
    from sqlalchemy import text

    with engine.connect() as conn:
        for table, cols in _MIGRATE_COLUMNS.items():
            for name, ddl in cols:
                try:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                    conn.commit()
                except Exception:  # noqa: BLE001 —— 列已存在等情况静默跳过
                    pass
        for table, name, col in _MIGRATE_INDEXES:
            try:
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({col})"))
                conn.commit()
            except Exception:  # noqa: BLE001 —— 索引已存在/表缺失等情况静默跳过
                pass
