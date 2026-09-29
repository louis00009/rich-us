"""本地历史行情库（IBKR 灌库产物）

设计动机
--------
`data_provider` 的免费源链（yfinance → stooq → twelvedata → finnhub）每次都要**上网**，
受限于限流、超时与第三方稳定性。而历史 K 线是**基本不变**的数据 ——
拉一次落地本地，之后读取就是磁盘 IO，快几个数量级，且不受外部服务影响。

本模块是「灌库 → 读库」的**读侧**：

    tools/ibkr_ingest.py  写入（灌库器，可断点续传）
        ↓  runtime/ibkr_bars/{SYMBOL}.parquet  +  runtime/ibkr_bars.jsonl
    hist_store.py         读取（本模块，零网络）
        ↓
    data_provider.fetch_history()  链的最优先位置

⚠️ 铁律：本模块**只读不写**。写入一律走灌库器，避免两处写逻辑不同步
（项目历史上 `rankings` 就因两处硬编码不同步导致 422）。

⚠️ 铁律：读到的数据**必须原样返回**，不得静默裁剪或填补。
数据不足时返回 None，由 data_provider 降级到在线源 —— 绝不用空/部分数据冒充完整。
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pandas as pd

_RUNTIME = Path(__file__).resolve().parent.parent / "runtime"
BARS_DIR = _RUNTIME / "ibkr_bars"
INDEX_FILE = _RUNTIME / "ibkr_bars.jsonl"

_lock = threading.RLock()
_index: dict[str, dict] | None = None      # symbol → {rows, start, fetched_at}
_index_mtime: float = 0.0


def _safe_name(symbol: str) -> str:
    """与灌库器的命名保持一致（BRK-B → BRK_B）。"""
    return symbol.strip().upper().replace("/", "_").replace("-", "_")


def _load_index(force: bool = False) -> dict[str, dict]:
    """读索引（带 mtime 缓存，避免每次请求都解析整个 JSONL）。

    索引只认 `rows > 0` 的记录 —— 失败记录不参与「已灌库」判断，
    这样新增灌库后索引会自动包含新标的。
    """
    global _index, _index_mtime
    with _lock:
        try:
            mtime = INDEX_FILE.stat().st_mtime if INDEX_FILE.exists() else 0.0
        except OSError:
            mtime = 0.0
        if _index is not None and not force and mtime == _index_mtime:
            return _index

        idx: dict[str, dict] = {}
        if INDEX_FILE.exists():
            try:
                for line in INDEX_FILE.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue          # 半行/损坏行跳过，不拖垮整个索引
                    if int(rec.get("rows", 0) or 0) > 0:
                        # 后写覆盖前写（同一标的重灌时以最新为准）
                        idx[str(rec.get("symbol", "")).upper()] = rec
            except OSError:
                idx = {}
        _index = idx
        _index_mtime = mtime
        return idx


def available() -> bool:
    """本地库是否有任何数据。"""
    return len(_load_index()) > 0


def coverage() -> dict:
    """给前端/诊断用的库状态。"""
    idx = _load_index()
    return {
        "available": bool(idx),
        "symbols": len(idx),
        "dir": str(BARS_DIR),
        "index_file": str(INDEX_FILE),
    }


def list_symbols() -> list[str]:
    return sorted(_load_index().keys())


def _read_frame(symbol: str) -> pd.DataFrame | None:
    """读单个标的。parquet 优先，回落 csv（与灌库器写入顺序对称）。"""
    safe = _safe_name(symbol)
    p = BARS_DIR / f"{safe}.parquet"
    if p.exists():
        try:
            return pd.read_parquet(p)
        except Exception:  # noqa: BLE001 —— 文件损坏/依赖缺失 → 尝试 csv
            pass
    c = BARS_DIR / f"{safe}.csv"
    if c.exists():
        try:
            return pd.read_csv(c, index_col=0, parse_dates=True)
        except Exception:  # noqa: BLE001
            return None
    return None


def has(symbol: str) -> bool:
    """该标的是否已灌库（只查索引，不读文件，零 IO 成本）。"""
    return symbol.strip().upper() in _load_index()


def history(
    symbol: str,
    start: str | None = None,
    end: str | None = None,
    interval: str = "1d",
) -> pd.DataFrame | None:
    """从本地库取历史 K 线。

    返回 None 的**任一情况**（由 data_provider 决定是否降级到在线源）：
      - 该标的未灌库
      - 非日线周期（当前只灌了日线）
      - 请求区间超出本地覆盖范围（**关键：不许用部分数据冒充完整**）
      - 文件损坏

    ⚠️ 区间校验是「诚实性」要求：若用户要 5 年、本地只有 2 年，
    返回截断的 2 年会让上层**误以为**这就是全部历史 → 回测结论错误。
    因此宁可返回 None 让它去在线源取。
    """
    if interval not in ("1d", "1D", "daily"):
        return None                        # 本库只存日线
    sym = symbol.strip().upper()
    if not has(sym):
        return None

    df = _read_frame(sym)
    if df is None or df.empty:
        return None

    # 统一索引为 DatetimeIndex（灌库器写入时 index 是 date）
    if not isinstance(df.index, pd.DatetimeIndex):
        try:
            df.index = pd.to_datetime(df.index, errors="coerce")
            df = df[df.index.notna()]
        except Exception:  # noqa: BLE001
            return None
    if df.empty:
        return None

    # 本地覆盖范围校验：请求区间必须落在覆盖内，否则宁缺毋滥
    if start:
        try:
            s = pd.Timestamp(start)
            tz = getattr(df.index, "tz", None)
            if tz is not None:
                s = s.tz_localize(tz) if s.tzinfo is None else s.tz_convert(tz)
            # 允许 5 个自然日的余量（周末/假日 + 起始日恰逢非交易日）
            if s < df.index.min() - pd.Timedelta(days=5):
                return None
        except Exception:  # noqa: BLE001
            pass

    # 时区对齐后切片（对齐逻辑与 backtest/history 一致，避免 naive/aware 比较抛错）
    try:
        tz = getattr(df.index, "tz", None)

        def _align(ts):
            t = pd.Timestamp(ts)
            if tz is not None:
                return t.tz_localize(tz) if t.tzinfo is None else t.tz_convert(tz)
            return t.tz_localize(None) if t.tzinfo is not None else t

        if start:
            df = df[df.index >= _align(start)]
        if end:
            df = df[df.index <= _align(end)]
    except Exception:  # noqa: BLE001
        pass

    return df if not df.empty else None


def invalidate_index_cache() -> None:
    """灌库后调用，强制下次重新解析索引。"""
    global _index_mtime
    with _lock:
        _index_mtime = -1.0


__all__ = [
    "available", "coverage", "list_symbols", "has", "history",
    "invalidate_index_cache", "BARS_DIR", "INDEX_FILE",
]
