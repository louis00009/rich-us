"""符号宇宙 —— 精选标的清单（从 `data_provider.py` 拆出，铁律 9，2026-09-30）。

纯数据表：ETF / 美股 / 指数 / 加密 / 外汇。供「搜索联想」与「行情看板」使用。
全市场标的搜不到时走 `symbol_search.py` 的 Yahoo 兜底。

⚠️ 这不是交易白名单 —— 能否下单由 `brokers/` 与风控决定，与这里无关。
"""
from __future__ import annotations

from dataclasses import dataclass


# ------------------------------------------------------------------
# 符号宇宙（用于搜索联想）
# ------------------------------------------------------------------
@dataclass(frozen=True)
class SymbolInfo:
    symbol: str
    name: str
    kind: str  # ETF | STOCK | INDEX


UNIVERSE: list[SymbolInfo] = [
    SymbolInfo("SPY", "SPDR S&P 500 ETF Trust", "ETF"),
    SymbolInfo("QQQ", "Invesco QQQ Trust (Nasdaq 100)", "ETF"),
    SymbolInfo("IWM", "iShares Russell 2000 ETF", "ETF"),
    SymbolInfo("DIA", "SPDR Dow Jones Industrial Average ETF", "ETF"),
    SymbolInfo("VTI", "Vanguard Total Stock Market ETF", "ETF"),
    SymbolInfo("VOO", "Vanguard S&P 500 ETF", "ETF"),
    SymbolInfo("SMH", "VanEck Semiconductor ETF", "ETF"),
    SymbolInfo("SOXX", "iShares Semiconductor ETF", "ETF"),
    SymbolInfo("XLK", "Technology Select Sector SPDR", "ETF"),
    SymbolInfo("XLF", "Financial Select Sector SPDR", "ETF"),
    SymbolInfo("XLE", "Energy Select Sector SPDR", "ETF"),
    SymbolInfo("XLV", "Health Care Select Sector SPDR", "ETF"),
    SymbolInfo("XLI", "Industrial Select Sector SPDR", "ETF"),
    SymbolInfo("XLP", "Consumer Staples Select Sector SPDR", "ETF"),
    SymbolInfo("XLY", "Consumer Discretionary Select Sector SPDR", "ETF"),
    SymbolInfo("XLU", "Utilities Select Sector SPDR", "ETF"),
    SymbolInfo("XLB", "Materials Select Sector SPDR", "ETF"),
    SymbolInfo("XLRE", "Real Estate Select Sector SPDR", "ETF"),
    SymbolInfo("GLD", "SPDR Gold Shares", "ETF"),
    SymbolInfo("SLV", "iShares Silver Trust", "ETF"),
    SymbolInfo("USO", "United States Oil Fund", "ETF"),
    SymbolInfo("TLT", "iShares 20+ Year Treasury Bond ETF", "ETF"),
    SymbolInfo("IEF", "iShares 7-10 Year Treasury Bond ETF", "ETF"),
    SymbolInfo("HYG", "iShares High Yield Corporate Bond ETF", "ETF"),
    SymbolInfo("LQD", "iShares Investment Grade Corporate Bond ETF", "ETF"),
    SymbolInfo("EEM", "iShares MSCI Emerging Markets ETF", "ETF"),
    SymbolInfo("EFA", "iShares MSCI EAFE ETF", "ETF"),
    SymbolInfo("FXI", "iShares China Large-Cap ETF", "ETF"),
    SymbolInfo("KWEB", "KraneShares CSI China Internet ETF", "ETF"),
    SymbolInfo("ARKK", "ARK Innovation ETF", "ETF"),
    SymbolInfo("TQQQ", "ProShares UltraPro QQQ (3x)", "ETF"),
    SymbolInfo("SOXL", "Direxion Daily Semiconductor Bull 3X", "ETF"),
    SymbolInfo("UVXY", "ProShares Ultra VIX Short-Term Futures", "ETF"),
    SymbolInfo("VIXY", "ProShares VIX Short-Term Futures ETF", "ETF"),
    SymbolInfo("IBIT", "iShares Bitcoin Trust ETF", "ETF"),
    SymbolInfo("AAPL", "Apple Inc.", "STOCK"),
    SymbolInfo("MSFT", "Microsoft Corporation", "STOCK"),
    SymbolInfo("NVDA", "NVIDIA Corporation", "STOCK"),
    SymbolInfo("AMZN", "Amazon.com, Inc.", "STOCK"),
    SymbolInfo("GOOGL", "Alphabet Inc. Class A", "STOCK"),
    SymbolInfo("META", "Meta Platforms, Inc.", "STOCK"),
    SymbolInfo("TSLA", "Tesla, Inc.", "STOCK"),
    SymbolInfo("AVGO", "Broadcom Inc.", "STOCK"),
    SymbolInfo("AMD", "Advanced Micro Devices, Inc.", "STOCK"),
    SymbolInfo("NFLX", "Netflix, Inc.", "STOCK"),
    SymbolInfo("CRM", "Salesforce, Inc.", "STOCK"),
    SymbolInfo("ORCL", "Oracle Corporation", "STOCK"),
    SymbolInfo("ADBE", "Adobe Inc.", "STOCK"),
    SymbolInfo("INTC", "Intel Corporation", "STOCK"),
    SymbolInfo("MU", "Micron Technology, Inc.", "STOCK"),
    SymbolInfo("QCOM", "QUALCOMM Incorporated", "STOCK"),
    SymbolInfo("TSM", "Taiwan Semiconductor Manufacturing (ADR)", "STOCK"),
    SymbolInfo("ASML", "ASML Holding N.V. (ADR)", "STOCK"),
    SymbolInfo("ARM", "Arm Holdings plc (ADR)", "STOCK"),
    SymbolInfo("PLTR", "Palantir Technologies Inc.", "STOCK"),
    SymbolInfo("COIN", "Coinbase Global, Inc.", "STOCK"),
    SymbolInfo("MSTR", "MicroStrategy Incorporated", "STOCK"),
    SymbolInfo("UBER", "Uber Technologies, Inc.", "STOCK"),
    SymbolInfo("ABNB", "Airbnb, Inc.", "STOCK"),
    SymbolInfo("SHOP", "Shopify Inc.", "STOCK"),
    SymbolInfo("SQ", "Block, Inc.", "STOCK"),
    SymbolInfo("PYPL", "PayPal Holdings, Inc.", "STOCK"),
    SymbolInfo("JPM", "JPMorgan Chase & Co.", "STOCK"),
    SymbolInfo("BAC", "Bank of America Corporation", "STOCK"),
    SymbolInfo("GS", "The Goldman Sachs Group, Inc.", "STOCK"),
    SymbolInfo("MS", "Morgan Stanley", "STOCK"),
    SymbolInfo("V", "Visa Inc.", "STOCK"),
    SymbolInfo("MA", "Mastercard Incorporated", "STOCK"),
    SymbolInfo("BRK-B", "Berkshire Hathaway Inc. Class B", "STOCK"),
    SymbolInfo("UNH", "UnitedHealth Group Incorporated", "STOCK"),
    SymbolInfo("LLY", "Eli Lilly and Company", "STOCK"),
    SymbolInfo("JNJ", "Johnson & Johnson", "STOCK"),
    SymbolInfo("PFE", "Pfizer Inc.", "STOCK"),
    SymbolInfo("MRK", "Merck & Co., Inc.", "STOCK"),
    SymbolInfo("ABBV", "AbbVie Inc.", "STOCK"),
    SymbolInfo("TMO", "Thermo Fisher Scientific Inc.", "STOCK"),
    SymbolInfo("ISRG", "Intuitive Surgical, Inc.", "STOCK"),
    SymbolInfo("XOM", "Exxon Mobil Corporation", "STOCK"),
    SymbolInfo("CVX", "Chevron Corporation", "STOCK"),
    SymbolInfo("COP", "ConocoPhillips", "STOCK"),
    SymbolInfo("OXY", "Occidental Petroleum Corporation", "STOCK"),
    SymbolInfo("WMT", "Walmart Inc.", "STOCK"),
    SymbolInfo("COST", "Costco Wholesale Corporation", "STOCK"),
    SymbolInfo("HD", "The Home Depot, Inc.", "STOCK"),
    SymbolInfo("MCD", "McDonald's Corporation", "STOCK"),
    SymbolInfo("NKE", "NIKE, Inc.", "STOCK"),
    SymbolInfo("SBUX", "Starbucks Corporation", "STOCK"),
    SymbolInfo("PG", "The Procter & Gamble Company", "STOCK"),
    SymbolInfo("KO", "The Coca-Cola Company", "STOCK"),
    SymbolInfo("PEP", "PepsiCo, Inc.", "STOCK"),
    SymbolInfo("DIS", "The Walt Disney Company", "STOCK"),
    SymbolInfo("BA", "The Boeing Company", "STOCK"),
    SymbolInfo("CAT", "Caterpillar Inc.", "STOCK"),
    SymbolInfo("GE", "GE Aerospace", "STOCK"),
    SymbolInfo("DE", "Deere & Company", "STOCK"),
    SymbolInfo("F", "Ford Motor Company", "STOCK"),
    SymbolInfo("GM", "General Motors Company", "STOCK"),
    SymbolInfo("RIVN", "Rivian Automotive, Inc.", "STOCK"),
    SymbolInfo("LCID", "Lucid Group, Inc.", "STOCK"),
    SymbolInfo("NIO", "NIO Inc. (ADR)", "STOCK"),
    SymbolInfo("BABA", "Alibaba Group Holding (ADR)", "STOCK"),
    SymbolInfo("PDD", "PDD Holdings Inc. (ADR)", "STOCK"),
    SymbolInfo("JD", "JD.com, Inc. (ADR)", "STOCK"),
    SymbolInfo("TCEHY", "Tencent Holdings (ADR)", "STOCK"),
    SymbolInfo("^GSPC", "S&P 500 Index", "INDEX"),
    SymbolInfo("^NDX", "Nasdaq 100 Index", "INDEX"),
    SymbolInfo("^DJI", "Dow Jones Industrial Average", "INDEX"),
    SymbolInfo("^VIX", "CBOE Volatility Index", "INDEX"),
    SymbolInfo("^TNX", "CBOE 10-Year Treasury Note Yield", "INDEX"),
    # T-134：加密与外汇（只读行情，仅供看板/分析；不在交易白名单）
    SymbolInfo("BTC-USD", "Bitcoin (USD)", "CRYPTO"),
    SymbolInfo("ETH-USD", "Ethereum (USD)", "CRYPTO"),
    SymbolInfo("EURUSD=X", "Euro / US Dollar", "FX"),
]

UNIVERSE_MAP = {s.symbol: s for s in UNIVERSE}
