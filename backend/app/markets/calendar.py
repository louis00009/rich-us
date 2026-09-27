"""交易日历 —— 市场感知的「今天开不开市、现在处于哪个时段」。

`registry.Market.session_of()` 只回答时间问题（9:30-16:00 算不算盘中），
本模块把**日期**也纳入：周末、节假日、半日市、以及跨日的「下一次开盘」。

时区语义（重要）
----------------
传入 naive `datetime` 时一律解释为**该市场的本地时间**（旧的 `is_market_open()`
就是这个行为，保持兼容）。要表达绝对时刻请传 aware datetime，本模块会自行转换。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from . import holidays as hol
from .registry import Market, get_market

_MAX_SCAN_DAYS = 400   # 防止异常输入导致死循环


# ======================================================================
# 状态对象
# ======================================================================
@dataclass(frozen=True)
class MarketStatus:
    market: str
    now_local: dt.datetime
    is_trading_day: bool
    session: str                 # regular | extended | auction | closed
    reason: str                  # 人类可读说明
    holiday: str | None = None
    is_half_day: bool = False
    early_close: str | None = None
    next_open: dt.datetime | None = None
    next_close: dt.datetime | None = None
    calendar_verified: bool = True
    warnings: tuple[str, ...] = ()

    @property
    def is_open(self) -> bool:
        """是否处于**可成交**的时段（常规盘或盘前盘后，不含竞价）。"""
        return self.session in ("regular", "extended")

    def as_dict(self) -> dict:
        return {
            "market": self.market,
            "now_local": self.now_local.isoformat(),
            "is_trading_day": self.is_trading_day,
            "is_open": self.is_open,
            "session": self.session,
            "session_label": get_market(self.market).label_of_session(self.session),
            "reason": self.reason,
            "holiday": self.holiday,
            "is_half_day": self.is_half_day,
            "early_close": self.early_close,
            "next_open": self.next_open.isoformat() if self.next_open else None,
            "next_close": self.next_close.isoformat() if self.next_close else None,
            "calendar_verified": self.calendar_verified,
            "warnings": list(self.warnings),
        }


# ======================================================================
# 基础判定
# ======================================================================
def _d(when: dt.datetime) -> str:
    return when.strftime("%Y-%m-%d")


def holiday_name(market: Market, when: dt.datetime) -> str | None:
    return hol.holidays_for(market.code).get(_d(when))


def early_close_name(market: Market, when: dt.datetime) -> str | None:
    return hol.early_closes_for(market.code).get(_d(when))


def is_trading_day(market: Market | str, when: dt.datetime | dt.date | None = None) -> bool:
    """是否交易日（考虑周末 + 节假日）。半日市算交易日。"""
    m = get_market(market) if isinstance(market, str) else market
    if when is None:
        local = m.localize()
    elif isinstance(when, dt.datetime):
        local = m.localize(when)
    else:
        local = m.localize(dt.datetime.combine(when, dt.time(12, 0)))
    if local.weekday() >= 5:
        return False
    return holiday_name(m, local) is None


def sessions_for(market: Market, when: dt.datetime) -> tuple:
    """返回该日的常规时段；半日市会把收盘时间前移。"""
    ec = early_close_name(market, when)
    if not ec or market.half_day_close is None:
        return market.regular
    from .registry import Session

    out = []
    for s in market.regular:
        end = min(s.end, market.half_day_close)
        if end > s.start:
            out.append(Session(s.start, end, f"{s.label}（半日市）"))
    return tuple(out)


def _session_at(market: Market, local: dt.datetime, regular: tuple) -> str:
    t = local.time()
    for s in regular:
        if s.contains(t):
            return "regular"
    for s in market.auction:
        if s.contains(t):
            return "auction"
    for s in market.extended:
        if s.contains(t):
            return "extended"
    return "closed"


def market_status(market: Market | str, when: dt.datetime | None = None) -> MarketStatus:
    """完整状态：是否交易日、处于哪个时段、下次开盘/收盘、日历可信度。"""
    m = get_market(market) if isinstance(market, str) else market
    local = m.localize(when)
    warns: list[str] = []
    verified = local.year in hol.verified_years(m.code)
    if not verified:
        warns.append(
            f"{m.name} {local.year} 年节假日表未与交易所官方日历核对，"
            f"节假日判断可能不准确 —— 请更新 app/markets/holidays.py"
        )

    hname = holiday_name(m, local)
    ec = early_close_name(m, local)
    trading = local.weekday() < 5 and hname is None

    if not trading:
        if hname:
            reason = f"{m.name}今日休市（{hname}）"
        else:
            reason = f"{m.name}周末休市"
        return MarketStatus(
            market=m.code, now_local=local, is_trading_day=False, session="closed",
            reason=reason, holiday=hname, is_half_day=False, early_close=ec,
            next_open=next_open(m, local), next_close=None,
            calendar_verified=verified, warnings=tuple(warns),
        )

    regular = sessions_for(m, local)
    sess = _session_at(m, local, regular)
    half = ec is not None
    if sess == "closed":
        # 区分「还没开盘」「午休」「已收盘」
        t = local.time()
        first = regular[0].start if regular else None
        last = regular[-1].end if regular else None
        if first and t < first:
            reason = f"{m.name}开盘前（{first:%H:%M} 开盘）"
        elif last and t >= last:
            reason = f"{m.name}已收盘（{last:%H:%M} 收盘）"
        else:
            reason = f"{m.name}休市间歇（{m.describe_sessions()}）"
    else:
        reason = f"{m.name}{m.label_of_session(sess)}中（{m.describe_sessions()}）"
        if half:
            reason += f" ｜ 今日半日市（{ec}），提前至 {m.half_day_close:%H:%M} 收盘"

    return MarketStatus(
        market=m.code, now_local=local, is_trading_day=True, session=sess,
        reason=reason, holiday=None, is_half_day=half, early_close=ec,
        next_open=(next_open(m, local) if sess == "closed" else None),
        next_close=next_close(m, local, regular),
        calendar_verified=verified, warnings=tuple(warns),
    )


# ======================================================================
# 时间游走
# ======================================================================
def next_trading_day(market: Market | str, when: dt.datetime | None = None) -> dt.date:
    m = get_market(market) if isinstance(market, str) else market
    cur = m.localize(when).date()
    for _ in range(_MAX_SCAN_DAYS):
        cur += dt.timedelta(days=1)
        if is_trading_day(m, cur):
            return cur
    raise RuntimeError(f"{m.code} 未来 {_MAX_SCAN_DAYS} 天找不到交易日")


def prev_trading_day(market: Market | str, when: dt.datetime | None = None) -> dt.date:
    m = get_market(market) if isinstance(market, str) else market
    cur = m.localize(when).date()
    for _ in range(_MAX_SCAN_DAYS):
        cur -= dt.timedelta(days=1)
        if is_trading_day(m, cur):
            return cur
    raise RuntimeError(f"{m.code} 过去 {_MAX_SCAN_DAYS} 天找不到交易日")


def next_open(market: Market | str, when: dt.datetime | None = None) -> dt.datetime | None:
    """下一次常规开盘时刻（含当日，若当前还没开盘）。"""
    m = get_market(market) if isinstance(market, str) else market
    local = m.localize(when)
    if is_trading_day(m, local):
        regular = sessions_for(m, local)
        for s in regular:
            if local.time() < s.start:
                return dt.datetime.combine(local.date(), s.start, tzinfo=local.tzinfo)
    d = next_trading_day(m, local)
    regular = sessions_for(m, m.localize(dt.datetime.combine(d, dt.time(12, 0))))
    if not regular:
        return None
    return dt.datetime.combine(d, regular[0].start, tzinfo=local.tzinfo)


def next_close(
    market: Market | str,
    when: dt.datetime | None = None,
    regular: tuple | None = None,
) -> dt.datetime | None:
    m = get_market(market) if isinstance(market, str) else market
    local = m.localize(when)
    if is_trading_day(m, local):
        reg = regular if regular is not None else sessions_for(m, local)
        if reg and local.time() < reg[-1].end:
            return dt.datetime.combine(local.date(), reg[-1].end, tzinfo=local.tzinfo)
    d = next_trading_day(m, local)
    reg = sessions_for(m, m.localize(dt.datetime.combine(d, dt.time(12, 0))))
    if not reg:
        return None
    return dt.datetime.combine(d, reg[-1].end, tzinfo=local.tzinfo)


def trading_days(market: Market | str, start: dt.date, end: dt.date) -> list[dt.date]:
    """[start, end] 区间内的交易日列表。用于回测对齐与数据校验。"""
    m = get_market(market) if isinstance(market, str) else market
    out: list[dt.date] = []
    cur = start
    while cur <= end:
        if is_trading_day(m, cur):
            out.append(cur)
        cur += dt.timedelta(days=1)
    return out


# ======================================================================
# 兼容层：旧代码调用的 is_market_open()
# ======================================================================
def is_market_open(now: dt.datetime | None = None, market: str = "US") -> bool:
    """保留旧签名。默认美股 + 仅常规时段 —— 与原 guardrails.is_market_open 行为一致。"""
    st = market_status(market, now)
    return st.session == "regular"


# ======================================================================
# 覆盖度自检（供 /api/system/market 与自检脚本使用）
# ======================================================================
def coverage(reference: dt.date | None = None) -> list[dict]:
    ref = reference or dt.date.today()
    out = []
    for code in ("US", "HK"):
        m = get_market(code)
        yrs = sorted(hol.verified_years(code))
        out.append({
            "market": code,
            "name": m.name,
            "holiday_count": len(hol.holidays_for(code)),
            "verified_years": yrs,
            "holidays_through": max((int(d[:4]) for d in hol.holidays_for(code)), default=0),
            "current_year_verified": ref.year in yrs,
            "needs_update": ref.year not in yrs,
        })
    return out


__all__ = [
    "MarketStatus", "market_status", "is_trading_day", "is_market_open",
    "sessions_for", "next_open", "next_close", "next_trading_day",
    "prev_trading_day", "trading_days", "holiday_name", "early_close_name",
    "coverage",
]
