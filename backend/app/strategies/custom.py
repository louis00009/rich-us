"""
自定义策略支持
================
两条路径，安全等级不同：

1) 规则 DSL (RuleStrategy) —— 推荐
   完全数据驱动：用户在前端用「指标 + 比较符 + 数值」拼条件，
   后端按白名单指标计算，不执行任何用户代码。零代码注入风险。

2) 代码策略 (CodeStrategy) —— 高级
   用户提交 Python 函数体，服务端先做 AST 白名单校验：
     · 仅允许 import pandas / numpy / math / datetime / statistics
     · 禁止 __import__ / eval / exec / open / getattr / 双下划线属性 等
     · 禁用 while True、递归深度受限、代码长度受限
   校验通过后在「受限 builtins」命名空间中执行。
   即便有上述防护，代码策略仍属高风险功能，默认仅在本地单用户环境启用。
"""
from __future__ import annotations

import ast
import builtins
import textwrap
from typing import Any

import numpy as np
import pandas as pd

from .base import ParamSpec, SignalContext, Strategy
from .registry import register

# ==================================================================
# 规则 DSL
# ==================================================================
OPS = [">", "<", ">=", "<=", "cross_above", "cross_below", "==", "!="]

ALLOWED_RULE_INDICATORS = [
    "close", "open", "high", "low", "volume",
    "sma", "ema", "hma", "kama", "rsi", "macd", "macd_hist", "macd_signal",
    "stoch_k", "stoch_d", "cci", "williams_r", "mfi",
    "atr", "natr", "bb_upper", "bb_lower", "bb_pctb", "bb_width",
    "adx", "plus_di", "minus_di", "zscore", "roc", "vol_ratio", "obv",
    "cmf", "realized_vol", "efficiency_ratio",
    "donchian_upper", "donchian_lower", "vwap",
    "dist_sma50", "dist_sma200", "atr_zscore",
]


class RuleError(ValueError):
    pass


def validate_rule(rule: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(rule, dict):
        raise RuleError("规则必须是对象")
    entry = rule.get("entry")
    if not isinstance(entry, dict) or not (entry.get("all") or entry.get("any")):
        raise RuleError("缺少 entry 条件（需提供 all 或 any 数组）")
    for group_key in ("entry", "exit"):
        grp = rule.get(group_key)
        if grp is None:
            continue
        if not isinstance(grp, dict):
            raise RuleError(f"{group_key} 必须是对象")
        conds = grp.get("all") or grp.get("any") or []
        if not isinstance(conds, list):
            raise RuleError(f"{group_key} 条件必须是数组")
        for c in conds:
            _validate_cond(c, group_key)
    d = rule.get("direction", "long")
    if d not in ("long", "short", "both"):
        raise RuleError("direction 只能是 long / short / both")
    return {
        "direction": d,
        "entry": rule["entry"],
        "exit": rule.get("exit") or {},
        "entry_size": float(np.clip(float(rule.get("entry_size", 1.0)), 0.01, 1.0)),
        "stop_loss_pct": float(rule.get("stop_loss_pct", 0) or 0),
        "take_profit_pct": float(rule.get("take_profit_pct", 0) or 0),
        "max_hold_bars": int(rule.get("max_hold_bars", 0) or 0),
        "notes": str(rule.get("notes", ""))[:500],
    }


def _validate_cond(c: Any, where: str) -> None:
    if not isinstance(c, dict):
        raise RuleError(f"{where} 中的条件必须是对象")
    op = c.get("op")
    if op not in OPS:
        raise RuleError(f"不支持的比较符: {op}")
    for side in ("left", "right"):
        s = c.get(side)
        if not isinstance(s, dict):
            raise RuleError(f"条件缺少 {side} 操作数")
        if "const" in s:
            try:
                float(s["const"])
            except (TypeError, ValueError) as exc:
                raise RuleError(f"{side}.const 必须是数字") from exc
        elif "indicator" in s:
            key = str(s["indicator"]).lower()
            if key not in ALLOWED_RULE_INDICATORS:
                raise RuleError(f"不支持的指标: {key}")
        else:
            raise RuleError(f"{side} 需包含 indicator 或 const")


def _operand_df(spec: dict[str, Any], ctx: SignalContext, cache: dict) -> pd.DataFrame:
    if "const" in spec:
        val = float(spec["const"])
        return pd.DataFrame(val, index=ctx.closes.index, columns=ctx.closes.columns)
    key = str(spec["indicator"]).lower()
    period = int(spec.get("period", 14) or 14)
    ck = (key, period)
    if ck not in cache:
        from .indicators import compute_indicator

        cols = {}
        for sym, df in ctx.data.items():
            try:
                cols[sym] = compute_indicator(df, key, period)
            except Exception:  # noqa: BLE001
                cols[sym] = pd.Series(np.nan, index=df.index)
        cache[ck] = pd.DataFrame(cols).reindex(index=ctx.closes.index, columns=ctx.closes.columns)
    base = cache[ck]
    mult = spec.get("mult")
    shift = int(spec.get("shift", 0) or 0)
    out = base * float(mult) if mult is not None else base
    if shift:
        out = out.shift(shift)
    return out


def _eval_cond(c: dict[str, Any], ctx: SignalContext, cache: dict) -> pd.DataFrame:
    left = _operand_df(c["left"], ctx, cache)
    right = _operand_df(c["right"], ctx, cache)
    op = c["op"]
    if op == ">":
        r = left > right
    elif op == "<":
        r = left < right
    elif op == ">=":
        r = left >= right
    elif op == "<=":
        r = left <= right
    elif op == "==":
        r = (left - right).abs() < 1e-9
    elif op == "!=":
        r = (left - right).abs() >= 1e-9
    elif op == "cross_above":
        r = (left > right) & (left.shift(1) <= right.shift(1))
    else:  # cross_below
        r = (left < right) & (left.shift(1) >= right.shift(1))
    return r.fillna(False)


def _eval_group(group: dict[str, Any] | None, ctx: SignalContext, cache: dict, default: bool) -> pd.DataFrame:
    if not group:
        return pd.DataFrame(default, index=ctx.closes.index, columns=ctx.closes.columns)
    conds = group.get("all") or group.get("any") or []
    if not conds:
        return pd.DataFrame(default, index=ctx.closes.index, columns=ctx.closes.columns)
    results = [_eval_cond(c, ctx, cache) for c in conds]
    acc = results[0].copy()
    if group.get("all"):
        for r in results[1:]:
            acc &= r
    else:
        for r in results[1:]:
            acc |= r
    return acc.fillna(False)


class RuleStrategy(Strategy):
    """由 JSON 规则动态生成的策略。"""

    key = "custom_rule"
    name = "自定义规则策略"
    category = "自定义"
    description = "基于指标条件的自定义进出场规则，由前端可视化编辑器生成。"
    tags = ["自定义", "规则", "可视化"]
    min_bars = 120

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return []

    def __init__(self, rule: dict[str, Any] | None = None, **params: Any) -> None:
        self.rule = validate_rule(rule or {})
        super().__init__(**params)

    def generate(self, ctx: SignalContext) -> pd.DataFrame:
        cache: dict = {}
        r = self.rule
        ent = _eval_group(r["entry"], ctx, cache, False)
        ex = _eval_group(r.get("exit"), ctx, cache, False)
        size = float(r["entry_size"])
        direction = r["direction"]
        allow_long = direction in ("long", "both")
        allow_short = direction in ("short", "both")
        max_hold = int(r.get("max_hold_bars", 0) or 0)

        n_cols = ent.shape[1]
        ent_np = ent.to_numpy(dtype=bool)
        ex_np = ex.to_numpy(dtype=bool)
        ent_l = ent_np if allow_long else np.zeros_like(ent_np)
        ent_s = ent_np if allow_short else np.zeros_like(ent_np)

        state = pd.DataFrame(0.0, index=ctx.closes.index, columns=ctx.closes.columns)
        cur = np.zeros(n_cols)
        held = np.zeros(n_cols, dtype=int)
        for i in range(len(ent)):
            cur = np.where(ent_l[i], size, cur)
            cur = np.where(ent_s[i], -size, cur)
            held = np.where(cur != 0, held + 1, 0)
            hit = ex_np[i] | ((max_hold > 0) & (held > max_hold))
            cur = np.where(hit, 0.0, cur)
            held = np.where(hit, 0, held)
            state.iloc[i] = cur
        return state


# ==================================================================
# 代码策略 —— AST 白名单沙箱
# ==================================================================
_ALLOWED_IMPORTS = {"pandas": "pd", "numpy": "np", "math": "math", "datetime": "datetime", "statistics": "statistics"}
_FORBIDDEN_NAMES = {
    "__import__", "eval", "exec", "compile", "open", "input", "breakpoint",
    "globals", "locals", "vars", "getattr", "setattr", "delattr", "dir",
    "memoryview", "type", "object", "classmethod", "staticmethod", "property",
    "exit", "quit", "help", "super", "reload", "system", "popen", "spawn",
    "os", "sys", "subprocess", "shutil", "socket", "ctypes", "importlib",
    "pickle", "marshal", "shelve", "tempfile", "pathlib", "threading", "multiprocessing",
}
_MAX_CODE_LEN = 8000
_MAX_AST_NODES = 1200

# 即使 pandas / numpy 在白名单内，其文件 I/O 能力也必须封堵，
# 否则 `pd.read_pickle('/path')` 可绕过「禁止 open」的限制读取任意文件。
_FORBIDDEN_ATTRS = {
    # pandas 读写
    "read_csv", "read_table", "read_fwf", "read_clipboard", "read_excel", "read_feather",
    "read_hdf", "read_html", "read_json", "read_orc", "read_parquet", "read_pickle",
    "read_sas", "read_spss", "read_sql", "read_sql_query", "read_sql_table", "read_stata",
    "read_xml", "to_csv", "to_excel", "to_feather", "to_hdf", "to_html", "to_json",
    "to_latex", "to_markdown", "to_orc", "to_parquet", "to_pickle", "to_sql", "to_stata",
    "to_xml", "to_clipboard", "HDFStore", "ExcelWriter", "ExcelFile", "io",
    # numpy 读写
    "load", "save", "savez", "savez_compressed", "savetxt", "loadtxt", "fromfile",
    "tofile", "memmap", "genfromtxt", "ctypeslib", "fromregex", "ndfromtxt",
}

# 以字符串常量形式出现时才拦截（避免误伤 "load"、"io" 这类普通列名）
_STRING_BLOCKLIST = {
    n
    for n in _FORBIDDEN_ATTRS
    if n.startswith(("read_", "to_")) or n in {"HDFStore", "ExcelWriter", "ExcelFile", "ctypeslib", "memmap"}
}


class CodeSecurityError(ValueError):
    pass


def validate_code(code: str) -> ast.Module:
    if not code or not code.strip():
        raise CodeSecurityError("代码为空")
    if len(code) > _MAX_CODE_LEN:
        raise CodeSecurityError(f"代码过长（上限 {_MAX_CODE_LEN} 字符）")
    try:
        tree = ast.parse(textwrap.dedent(code), mode="exec")
    except SyntaxError as exc:
        raise CodeSecurityError(f"语法错误: {exc.msg} (第 {exc.lineno} 行)") from exc

    n_nodes = sum(1 for _ in ast.walk(tree))
    if n_nodes > _MAX_AST_NODES:
        raise CodeSecurityError("代码结构过于复杂")

    has_generate = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in _ALLOWED_IMPORTS:
                    raise CodeSecurityError(f"禁止导入模块: {a.name}")
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] not in _ALLOWED_IMPORTS:
                raise CodeSecurityError(f"禁止导入模块: {node.module}")
            for a in node.names:
                if a.name in _FORBIDDEN_ATTRS:
                    raise CodeSecurityError(f"禁止导入符号: {a.name}")
        elif isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
            raise CodeSecurityError(f"禁止使用名称: {node.id}")
        elif isinstance(node, ast.Attribute):
            if node.attr.startswith("_"):
                raise CodeSecurityError(f"禁止访问私有/魔术属性: {node.attr}")
            if node.attr in _FORBIDDEN_ATTRS:
                raise CodeSecurityError(f"禁止调用文件读写/序列化接口: {node.attr}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # 仅对「高辨识度」的文件 I/O 名称做字符串拦截，避免误伤普通列名
            if node.value in _STRING_BLOCKLIST:
                raise CodeSecurityError(f"禁止以字符串形式引用受限接口: {node.value}")
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in _FORBIDDEN_NAMES:
                raise CodeSecurityError(f"禁止调用: {fn.id}")
        elif isinstance(node, ast.While):
            test = node.test
            if isinstance(test, ast.Constant) and test.value is True:
                raise CodeSecurityError("禁止 `while True` 死循环")
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            raise CodeSecurityError("禁止使用 global / nonlocal")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "generate":
            has_generate = True
        elif isinstance(node, (ast.Lambda, ast.ClassDef, ast.AsyncFunctionDef)):
            raise CodeSecurityError("禁止定义 lambda / class / async 函数")

    if "def generate" not in code:
        raise CodeSecurityError("必须定义 `def generate(ctx):` 函数")
    if not has_generate:
        raise CodeSecurityError("未找到 generate 函数定义")
    return tree


def _safe_import(name: str, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
    """受限 __import__：即使 AST 校验被绕过，也只可能导入白名单模块。"""
    root = str(name).split(".")[0]
    if root not in _ALLOWED_IMPORTS:
        raise ImportError(f"禁止导入模块: {name}")
    return builtins.__import__(name, globals, locals, fromlist, level)


def _safe_getattr(obj, name, *default):  # noqa: ANN001
    """受限 getattr：无法通过字符串绕过 AST 的私有属性检查。"""
    if str(name).startswith("_"):
        raise AttributeError(f"禁止访问私有/魔术属性: {name}")
    return getattr(obj, name, *default)


_SAFE_BUILTINS = {
    k: getattr(builtins, k)
    for k in (
        "abs", "min", "max", "sum", "len", "range", "enumerate", "zip", "sorted",
        "round", "int", "float", "bool", "str", "list", "tuple", "dict", "set",
        "frozenset", "bytes", "complex", "any", "all", "map", "filter", "reversed",
        "pow", "divmod", "slice", "iter", "next", "repr", "format", "chr", "ord",
        "hex", "bin", "hash", "id", "callable", "hasattr", "isinstance", "issubclass",
        "print",
        # 异常类型（策略内可能需要捕获）
        "Exception", "BaseException", "ValueError", "TypeError", "KeyError",
        "IndexError", "ZeroDivisionError", "ArithmeticError", "RuntimeError",
        "StopIteration", "NotImplementedError", "AttributeError", "ImportError",
    )
}
# 受控覆写：仅允许白名单模块导入 + 拦截私有属性
_SAFE_BUILTINS["__import__"] = _safe_import
_SAFE_BUILTINS["getattr"] = _safe_getattr


class CodeStrategy(Strategy):
    key = "custom_code"
    name = "自定义代码策略"
    category = "自定义"
    description = "用户提交 Python 函数（AST 白名单沙箱 + 受限 builtins）。"
    tags = ["自定义", "Python", "高级"]
    min_bars = 60

    @classmethod
    def param_specs(cls) -> list[ParamSpec]:
        return []

    def __init__(self, code: str = "", **params: Any) -> None:
        validate_code(code)
        self.code = textwrap.dedent(code)
        super().__init__(**params)

    def _namespace(self) -> dict[str, Any]:
        import datetime as _dt
        import math as _math
        import statistics as _stats

        ns: dict[str, Any] = {
            "__builtins__": _SAFE_BUILTINS,
            "__name__": "quantdesk_strategy",
            # 常用别名预置，用户无需 import 也能直接用
            "pd": pd,
            "pandas": pd,
            "np": np,
            "numpy": np,
            "math": _math,
            "datetime": _dt,
            "statistics": _stats,
        }
        exec(compile(self.code, "<strategy>", "exec"), ns, ns)  # noqa: S102 已完成 AST 白名单校验
        return ns

    def generate(self, ctx: SignalContext) -> pd.DataFrame:
        ns = self._namespace()
        fn = ns.get("generate")
        if not callable(fn):
            raise CodeSecurityError("generate 未定义或不可调用")
        result = fn(ctx)
        if not isinstance(result, pd.DataFrame):
            raise ValueError("generate 必须返回 DataFrame(index=时间, columns=标的, values=权重)")
        return result
