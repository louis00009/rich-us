"""榜单计算纯函数：搜索匹配、排序、行过滤。

从 rankings.py 按铁律 9（FILE_SIZE_DEBT Batch D-2）拆出 —— 这些函数
只做「行 → 行」的纯计算，不碰缓存与数据源。rankings.py 保留旧的下划线
名字作为别名（测试与外部调用一直在用 `from app.rankings import ...`）。
"""
from __future__ import annotations

import re
from typing import Any

_CJK_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")


def _name_match(name: str, ql: str) -> bool:
    """名称匹配：拉丁文按**词首**，CJK 按**子串**。

    · 拉丁文若用任意子串，"tmo" 会命中 "Atmos Energy"（a-**tmo**-s）——
      用户搜一个明确的代码，结果无关公司混进来。按词首匹配即可消除，
      同时 "fisher" 仍能命中 "Thermo Fisher"、"thermo fisher" 命中整名开头。
    · CJK 没有词边界，「赛默飞」必须在「赛默飞世尔」**中间**也能命中，故用子串。
    """
    n = (name or "").lower()
    if not n:
        return False
    if _CJK_RE.search(ql):                     # 中文查询 → 子串
        return ql in n
    if n.startswith(ql):                       # 拉丁文 → 整名开头
        return True
    return any(w.startswith(ql) for w in re.split(r"[^a-z0-9]+", n) if w)


def _match_rank(sym: str, name: str, name_cn: str, ql: str) -> int | None:
    """搜索匹配质量：0 = 代码精确 / 1 = 代码前缀 / 2 = 名称命中；不匹配返回 None。

    ⚠️ 旧实现是 `ql in sym.lower()` 的**子串**匹配 —— 搜 "TMO" 会命中
    "ATMOS Energy"（a-**tmo**-s），用户搜一个明确的代码，结果无关标的按当前
    排序（如涨跌幅）排在正主前面，看起来就像「搜不出来」。代码必须前缀匹配。
    """
    s = (sym or "").lower()
    if s == ql:
        return 0
    if s.startswith(ql):
        return 1
    if _name_match(name, ql) or _name_match(name_cn, ql):
        return 2
    return None


def _sort_rows(rows: list[dict[str, Any]], sort: str, desc: bool) -> None:
    """排序。**缺失值恒排末尾**（不论升序降序）。

    旧实现是 `x.get("market_cap") or 0.0` —— 把"没有数据"当成 0：升序时这些行
    会顶到最前面，用户看到的"市值最小的股票"其实是没有市值的股票。
    加估值指标后缺失面会大得多（腾讯不覆盖的小票），所以这里必须修。
    """
    if sort == "symbol":
        rows.sort(key=lambda r: str(r.get("symbol") or ""), reverse=desc)
    else:
        def key(r: dict[str, Any]) -> tuple[bool, float]:
            v = r.get(sort)
            # bool 必须先判：Python 里 True == 1，否则布尔列会与数值列混排
            if isinstance(v, bool):
                return (False, -float(v) if desc else float(v))
            if not isinstance(v, (int, float)):
                return (True, 0.0)              # 缺失 → 永远排在最后
            return (False, -float(v) if desc else float(v))

        rows.sort(key=key)

    # 搜索匹配质量作为**主排序键**：代码精确 > 代码前缀 > 名称命中。
    # Python 的 sort 是稳定的 → 同一质量档内保持上面算好的排序。
    # 无搜索时 _match_rank 全为 0，这一步等价于空操作。
    if rows and "_match_rank" in rows[0]:
        rows.sort(key=lambda r: r.get("_match_rank", 9))


def _build_filter(
    pe_min: float | None, pe_max: float | None, pb_max: float | None,
    cap_min: float | None, div_min: float | None, roe_min: float | None,
    from_high_max: float | None, exclude_loss: bool,
    rsi_min: float | None = None, rsi_max: float | None = None,
    above_ma200: bool = False, below_ma200: bool = False,
    vol_max: float | None = None, beta_max: float | None = None,
    score_min: float | None = None, only_bull: bool = False,
    req_1y_min: float | None = None, excess_min: float | None = None,
) -> Any:
    """构造行过滤器。

    语义要点：**设了某指标的区间，缺该指标的标的会被排除**，而不是当成 0。
    否则「PE ≤ 15」会混进一堆根本没有 EPS 数据的标的（那些标的 PE 显示为 —）。
    技术面筛选同理 —— 没有均线数据的标的不会因为「不知道」而被放行。
    """
    def keep(r: dict[str, Any]) -> bool:
        if exclude_loss and r.get("pe_state") == "loss":
            return False
        if pe_min is not None or pe_max is not None:
            pe = r.get("pe_ttm")
            if not isinstance(pe, (int, float)):
                return False
            if pe_min is not None and pe < pe_min:
                return False
            if pe_max is not None and pe > pe_max:
                return False
        if pb_max is not None:
            pb = r.get("pb")
            if not isinstance(pb, (int, float)) or pb > pb_max:
                return False
        if roe_min is not None:
            roe = r.get("roe")
            if not isinstance(roe, (int, float)) or roe < roe_min:
                return False
        if div_min is not None:
            d = r.get("div_yield")
            if not isinstance(d, (int, float)) or d < div_min:
                return False
        if cap_min is not None:
            cap = r.get("market_cap")
            if not isinstance(cap, (int, float)) or cap < cap_min * 1e8:   # 亿美元 → 美元
                return False
        if from_high_max is not None:
            # 距 52 周高 ≤ from_high_max（如 -30 表示"从高点回撤至少 30%"）
            fh = r.get("pct_from_high")
            if not isinstance(fh, (int, float)) or fh > from_high_max:
                return False

        # ---- 技术面 ----
        if rsi_min is not None or rsi_max is not None:
            v = r.get("rsi14")
            if not isinstance(v, (int, float)):
                return False
            if rsi_min is not None and v < rsi_min:
                return False
            if rsi_max is not None and v > rsi_max:
                return False
        if above_ma200:
            v = r.get("ma200_rel")
            if not isinstance(v, (int, float)) or v <= 0:
                return False
        if below_ma200:
            v = r.get("ma200_rel")
            if not isinstance(v, (int, float)) or v >= 0:
                return False
        if only_bull and r.get("ma_bull") is not True:
            return False
        if vol_max is not None:
            v = r.get("vol_ann")
            if not isinstance(v, (int, float)) or v > vol_max:
                return False
        if beta_max is not None:
            v = r.get("beta")
            if not isinstance(v, (int, float)) or v > beta_max:
                return False
        if req_1y_min is not None:
            v = r.get("r1y")
            if not isinstance(v, (int, float)) or v < req_1y_min:
                return False
        if excess_min is not None:
            v = r.get("excess_1y")
            if not isinstance(v, (int, float)) or v < excess_min:
                return False

        # ---- 评分 ----
        if score_min is not None:
            v = r.get("score")
            if not isinstance(v, (int, float)) or v < score_min:
                return False
        return True

    return keep
