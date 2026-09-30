"""TwelveData 数据源（FILE_SIZE_DEBT Batch F-3 从 data_provider.py 拆出）。

⚠️⚠️ 搬家不许改语义：datetime 是**无时区墙钟**，必须 tz_localize('America/New_York')
后由 fetch_history 做**唯一一次**归一化；`outputsize=5000` 分支**不认 end**
→ 会读到**未来数据**，该分支原样保留。
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .common import OHLCV, _normalize
from .synthetic import _market_of

# 本项目周期 → TwelveData interval 参数（命名不同：1d→1day、1wk→1week、30m→30min）
_TD_INTERVAL = {
    "1d": "1day", "1wk": "1week", "1h": "1h",
    "30m": "30min", "15m": "15min", "5m": "5min", "1m": "1min",
}



def _from_twelvedata(symbol: str, start: str, end: str | None, interval: str) -> pd.DataFrame:
    """TwelveData 行情（走多 Key 轮询池，见 `app/twelvedata.py`）。

    免费档实测 **8 credits/分钟、800/天**，单账号喂不饱全量标的 —— 故本函数
    **不直接持有密钥**，一律通过 `twelvedata.api_get` 取池中当前可用的 Key。
    池内全部 Key 都超限/冷却时 `acquire()` 返回 None → 这里返回空 →
    降级链继续往下走。**限流器即安全阀**，不会把额度打爆、也不会抛 429 雪崩。

    ⚠️ TwelveData 的 `values` 是**倒序**（最新在前），必须 reverse，
    否则 K 线时间轴会整体反过来（回测会读到未来数据）。

    ⚠️ **时区是这里最容易错的地方**：TwelveData 的 `datetime` 是**无时区的交易所墙钟**
    （日线就是 "2026-09-25"）。若直接交给 `_normalize`（默认把 naive 当 UTC 再转 NY），
    日线会整体退到**前一天 20:00** —— 日期都错了，回测会系统性偏移一天。
    所以这里先显式 `tz_localize("America/New_York")` 变成 aware。

    返回值**故意不做 `_normalize`**：降级链的 `v_td` 与 provider 路径的 `fetch_history`
    各会归一化，且两条路**互斥**（同一次请求只会走其中一条），所以恰好一次。
    ⚠️ `_normalize` 对 naive 输入**不是幂等**的（每多跑一次就再退 4 小时），
    因此「归一化几次」必须是确定的 —— 不要在这里、或在调用方重复加。
    """
    if _market_of(symbol) != "US":
        return pd.DataFrame(columns=OHLCV)
    td_interval = _TD_INTERVAL.get(interval)
    if not td_interval:
        return pd.DataFrame(columns=OHLCV)
    from .. import twelvedata as _td

    if not _td.pool().has_key():
        return pd.DataFrame(columns=OHLCV)

    # 日线/周线用 outputsize 拿长历史；日内给 start_date/end_date（免费档日内回溯有限）
    params: dict[str, Any] = {"symbol": symbol, "interval": td_interval}
    if interval in ("1d", "1wk"):
        params["outputsize"] = 5000
    else:
        params["start_date"] = start
        if end:
            params["end_date"] = end
        params["outputsize"] = 5000

    res = _td.api_get("/time_series", params)
    if not res.get("ok"):
        return pd.DataFrame(columns=OHLCV)
    data = res.get("data") or {}
    values = data.get("values") if isinstance(data, dict) else None
    if not values:
        return pd.DataFrame(columns=OHLCV)
    df = pd.DataFrame(values)
    if "datetime" not in df.columns:
        return pd.DataFrame(columns=OHLCV)
    df = df.rename(columns={"datetime": "date"})
    for c in OHLCV:
        if c not in df.columns:
            df[c] = 0.0 if c == "volume" else np.nan
    df = df[["date", *OHLCV]]
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).set_index("date")
    df = df.iloc[::-1]                      # 倒序 → 正序（见 docstring 的警告）
    try:
        df.index = df.index.tz_localize("America/New_York")   # naive 墙钟 → aware（关键）
    except (TypeError, AttributeError):
        pass                                # 已经是 aware 就原样保留
    df = df[~df.index.duplicated(keep="last")].sort_index()

    # 尊重请求区间：日线/周线用 `outputsize=5000` 会返回**远超 start** 的长历史，
    # 且 TwelveData 在该分支下**不认 end** —— 若不裁剪，指定 end 的回测会读到
    # end 之后的 K 线，等于未来函数（铁律）。裁剪逻辑放在 twelvedata.clip_range（纯函数，可自检）。
    df = _td.clip_range(df, start, end, interval)
    return df[OHLCV].apply(pd.to_numeric, errors="coerce")



def v_td(symbol: str, start: str, end: str | None, interval: str) -> pd.DataFrame:
    # `_from_twelvedata` 返回 aware（纽约）帧、**故意不做**归一化（见其 docstring）——
    # 降级链的契约是「已归一化」，所以在这里补上这**唯一一次**。
    return _normalize(_from_twelvedata(symbol, start, end, interval))



class TwelveDataProvider:
    """适配器：把 TwelveData 多 Key 轮询池接进数据源注册表。

    注册后才能出现在「设置 → 数据与缓存 → 源健康状态」里，并可被选为优先数据源。
    `history()` 返回 **aware（纽约）** 帧，由 `fetch_history` 里的 `_normalize`
    做那**唯一一次**归一化（若这里先归一化成 naive，会被再当 UTC 转一次 →
    日线整体退一天）。
    """

    name = "twelvedata"

    def history(self, symbol: str, start: str | None, end: str | None, interval: str):
        try:
            df = _from_twelvedata(symbol, start or "2019-01-01", end, interval)
            return df if df is not None and len(df) > 20 else None
        except Exception:  # noqa: BLE001
            return None

    def status(self) -> dict:
        from .. import twelvedata as _td

        st = _td.pool().status()
        if st["enabled"] == 0:
            return {
                "name": "twelvedata",
                "available": False,
                "reason": "未配置密钥（在「数据与缓存」里添加 TwelveData Key）",
            }
        return {
            "name": "twelvedata",
            "available": st["available_now"] > 0,
            "reason": (
                f"{st['enabled']} 个密钥，当前可用 {st['available_now']} 个；"
                f"合计额度 {st['effective_per_min']}/min、{st['effective_per_day']}/day"
            ),
            **{k: st[k] for k in ("count", "enabled", "available_now",
                                  "effective_per_min", "effective_per_day")},
        }



def register_twelvedata_provider() -> None:
    # 延迟导入：注册表全局（_history_providers/_preferred）留在 data_provider.py
    # （多处读者），此处调用时机在 data_provider 加载完成之后，无循环问题。
    from ..data_provider import register_history_provider

    register_history_provider("twelvedata", TwelveDataProvider())

