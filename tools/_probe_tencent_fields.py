"""腾讯美股行情字段口径探针（离线可跑，只读网络，不写任何生产数据）。

背景：`app/company.py::_tencent_batch` 只解析了 parts[1]（中文名）与 parts[44]（市值）。
榜单页要加财务指标，必须先确认这批字段到底代表什么 —— 腾讯没有公开字段文档，
所以本脚本用**算术自证 + 交叉一致**的方式验证：

  1. parts[39] == price / parts[47]        → 39=市盈率(TTM)、47=每股收益(TTM)
  2. parts[51] / parts[39] * 100 == parts[57] → 51=市净率、57=ROE%（恒等式 ROE = PB/PE）
  3. parts[44] == parts[63] * price / 1e8  → 44=流通市值（亿），63=流通股本
     parts[45] == parts[62] * price / 1e8  → 45=总市值（亿），62=总股本
  4. parts[52] 与已知股息率对比            → 52=股息率%

跑法：
  cd IBKR && backend/.venv/Scripts/python.exe tools/_probe_tencent_fields.py [样本数]
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "backend" / "app" / "markets" / "sp500.json"

UA = {"User-Agent": "Mozilla/5.0 QuantDesk"}
BATCH = 50


def fetch(codes: list[str]) -> str:
    url = "https://qt.gtimg.cn/q=" + ",".join(codes)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310
        return r.read().decode("gbk", errors="ignore")


def parse(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for m in re.finditer(r'v_([A-Za-z0-9]+)="([^"]*)"', text):
        var, body = m.group(1), m.group(2)
        if var.startswith("us"):
            out[var[2:].upper()] = body.split("~")
    return out


def f(parts: list[str], i: int) -> float | None:
    try:
        if i < len(parts) and parts[i] not in ("", "-"):
            return float(parts[i])
    except (ValueError, IndexError):
        pass
    return None


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 120
    cons = json.loads(SNAPSHOT.read_text(encoding="utf-8"))["constituents"]
    syms = [c["symbol"] for c in cons][:n]
    rows: dict[str, list[str]] = {}
    for i in range(0, len(syms), BATCH):
        chunk = syms[i : i + BATCH]
        rows.update(parse(fetch(["us" + s.replace(".", "-") for s in chunk])))
    print(f"请求 {len(syms)} 只，返回 {len(rows)} 只\n")

    checks = {
        "39 == price/47  (PE, EPS)": lambda p: _rel(f(p, 39), _div(f(p, 3), f(p, 47))),
        "51/39*100 == 57 (PB, ROE)": lambda p: _rel(f(p, 57), _div(f(p, 51), f(p, 39), 100)),
        "44 == 63*price  (流通市值)": lambda p: _rel(f(p, 44), _div(_mul(f(p, 63), f(p, 3)), 1e8)),
        "45 == 62*price  (总市值)": lambda p: _rel(f(p, 45), _div(_mul(f(p, 62), f(p, 3)), 1e8)),
    }
    for name, fn in checks.items():
        ok = bad = skip = 0
        worst: list[tuple[float, str]] = []
        for sym, p in rows.items():
            try:
                d = fn(p)
            except Exception:  # noqa: BLE001
                d = None
            if d is None:
                skip += 1
            elif d < 0.02:
                ok += 1
            else:
                bad += 1
                worst.append((d, sym))
        worst.sort(reverse=True)
        tot = ok + bad
        pct = f"{ok / tot * 100:.1f}%" if tot else "n/a"
        print(f"{name:32s} 命中 {ok:4d}/{tot:<4d} = {pct:>6s}  跳过 {skip:3d}  最大偏差 "
              + (", ".join(f"{s}:{d * 100:.1f}%" for d, s in worst[:4]) or "—"))

    # 51 是否为市净率？用 总市值(亿)/51 反推净资产（亿美元），与公开净资产量级对照。
    print("\n--- 51 反推净资产（亿美元）---")
    known = {"JPM": 3500, "PFE": 880, "KO": 300, "AAPL": 800, "MSFT": 4000, "TSLA": 800, "NVDA": 1800}
    for sym, ref in known.items():
        p = rows.get(sym)
        if not p:
            continue
        pb, cap = f(p, 51), f(p, 45)
        eq = None if not pb or cap is None else cap / pb
        print(f"{sym:6s} PB={pb:<7} 反推净资产={eq:>8.0f} 亿  (公开量级 ~{ref} 亿)")

    implied = [f(p, 51) / f(p, 39) * 100 for p in rows.values() if f(p, 51) and f(p, 39)]
    implied = [x for x in implied if x is not None]
    if implied:
        implied.sort()
        med = implied[len(implied) // 2]
        print(f"\n51/39*100 隐含 ROE：中位数 {med:.1f}%  区间 {implied[0]:.1f}% ~ {implied[-1]:.1f}%  "
              f"落在 0~100% 的比例 {sum(1 for x in implied if 0 < x < 100) / len(implied) * 100:.0f}%")

    print("\n--- 抽样 ---")
    for sym in ("AAPL", "MSFT", "KO", "JPM", "TSLA", "PFE", "NVDA", "XOM"):
        p = rows.get(sym)
        if not p:
            continue
        print(f"{sym:6s} price={f(p, 3)} PE={f(p, 39)} EPS={f(p, 47)} 51={f(p, 51)} "
              f"股息率={f(p, 52)} 57={f(p, 57)} 58={f(p, 58)} 总市值={f(p, 45)}亿 换手={f(p, 38)}% 振幅={f(p, 43)}%")


def _mul(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a * b


def _div(a: float | None, b: float | None, scale: float = 1.0) -> float | None:
    if a is None or b in (None, 0):
        return None
    return a / b * scale


def _rel(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    d = max(abs(a), abs(b))
    return None if d == 0 else abs(a - b) / d


if __name__ == "__main__":
    main()
