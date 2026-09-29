"""
AI 任务中枢（AI Task Hub）· 框架层
===================================
平台里「值得让大模型看一眼」的功能点，全部登记成一个一个 **AI 任务**。
本文件只放**框架**（任务模型 / 注册表 / 运行入口 / 公共工具与提示词约束），
具体任务按领域拆到：

  · `ai_tasks_market.py`   行情类：个股快评、新闻要点、盘面简报、候选池点评
  · `ai_tasks_analysis.py` 分析类：回测诊断、寻优解读、风控体检、组合点评、交易复盘
  · `ai_tasks_ops.py`      运营类：策略草稿、订单诊断、情报解读、提案复核
  · `ai_tasks_screen.py`   选股类：多标的批量研判、智能选股
  · `ai_tasks_strategy.py` 策略类：自定义策略代码审查（未来函数检测）

设计目标（与项目既有约定一致）
------------------------------
1. **单一入口**：前端只需 `POST /api/ai/assist {task, payload}`。
   不需要为每个功能点各写一个接口，也不需要在各处重复处理鉴权、超时、错误。
2. **复用同一套 AI 配置**：调用链与「AI 研判 / AI Copilot」完全一致 ——
   都走 `ai_analyst._llm_call`，因此「设置 → AI 分析」里配的网关、
   密钥、全局模型、`QD_AI_EXTRA_MODELS` 别名与多模型选择全部自动生效。
3. **数据不编造**：每个任务的上下文一律由后端从**平台真实数据**构造
   （行情快照 / 回测指标 / 风控配置 / 持仓 / 新闻 / 情报事件），
   大模型只做归纳与判断，不做事实生成。
4. **降级可用**：未配置 LLM 时，每个任务都有确定性的**规则化兜底**
   （`engine="local"`），页面不会空白也不会报错，只是少了自然语言深度。
   这与平台「本地量化引擎兜底」的既有设计一脉相承。
5. **AI 只有建议权**：所有任务的提示词都显式禁止输出「买入/卖出信号」，
   交易动作仍必须走 `ai_proposals` + 人工批准（见 AI_GUIDE.md §2.6）。

新增一个接入点：在对应领域模块里写一个 `_b_xxx`（构造上下文与提示词）与
一个 `_l_xxx`（规则化兜底），再 `_register(...)` 登记即可，无需改 API 层。
"""
from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from .ai_analyst import SYSTEM_PROMPT, _llm_call, ai_configured, analyze_local, market_snapshot

# ==================================================================
# 通用提示词约束
# ==================================================================
_GUARD = (
    "\n\n【硬性约束】\n"
    "1. 只依据上面给出的结构化数据推理，不得编造价格、财报、新闻或事件；"
    "数据里没有的就说「数据未覆盖」。\n"
    "2. 明确区分「数据事实」与「概率判断」，每条判断都要给依据。\n"
    "3. 使用简体中文，结构化输出，不要空泛套话。\n"
    "4. 不要给出「买入信号 / 卖出信号」这类绝对指令，也不要承诺收益 —— "
    "平台的一切交易动作都必须经 AI 提案 + 人工批准，你只提供分析与风险提示。\n"
    "5. 最后用单独一行「风险提示：…」收束。"
)

_MARKET_SYSTEM = SYSTEM_PROMPT

_GENERIC_SYSTEM = (
    "你是一位严谨的量化研究与风控助理，服务于一位专业交易员。"
    "你的价值在于把繁杂的数据整理成可执行的结论，而不是复述数据本身。"
)


# ==================================================================
# 任务模型与注册表
# ==================================================================
@dataclass(frozen=True)
class Task:
    key: str
    title: str
    desc: str
    system: str
    build: Callable[[dict], "tuple[str, dict]"]
    local: Callable[[dict, dict], str]
    max_tokens: int = 1200
    temperature: float = 0.3
    # 需要**结构化结果**的任务（如「智能选股」要返回可被前端应用的筛选条件）
    # 在这里挂一个解析函数：run_task 会把 text 解析成 `out["data"]`。
    # 为 None 表示纯文本任务（大多数），前端只看 text。
    parse: Callable[[str], dict] | None = None


TASKS: dict[str, Task] = {}


def _register(
    key: str,
    title: str,
    desc: str,
    build: Callable[[dict], "tuple[str, dict]"],
    local: Callable[[dict, dict], str],
    *,
    system: str = _GENERIC_SYSTEM,
    max_tokens: int = 1200,
    temperature: float = 0.3,
    parse: Callable[[str], dict] | None = None,
) -> None:
    """登记一个 AI 任务（领域模块在导入时调用）。"""
    TASKS[key] = Task(key, title, desc, system, build, local, max_tokens, temperature, parse)


def task_catalog() -> list[dict[str, str]]:
    """给前端 / 文档用的任务清单。"""
    return [
        {"key": t.key, "title": t.title, "desc": t.desc}
        for t in sorted(TASKS.values(), key=lambda x: x.key)
    ]


# ==================================================================
# 公共工具
# ==================================================================
def _clean(obj: Any) -> Any:
    """递归把 NaN / ±Inf 换成 None —— 否则 json 里会出现非法字面量 NaN。"""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else round(obj, 6)
    return obj


def _j(obj: Any) -> str:
    return json.dumps(_clean(obj), ensure_ascii=False, indent=1)


# 模型常把 JSON 包在 ```json 围栏里，或在前后加一句解释 —— 不能直接 json.loads。
_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def _extract_json(text: str) -> dict:
    """从模型输出里抠出第一个 JSON 对象（供 task.parse 使用）。

    依次尝试：整段 → 每个围栏块 → 第一个 `{` 到最后一个 `}`。
    都失败才抛 ValueError，由 run_task 记成 llm_error 并退回纯文本展示。
    """
    s = (text or "").strip()
    if not s:
        raise ValueError("输出为空")
    for cand in [s, *_JSON_FENCE.findall(s)]:
        try:
            obj = json.loads(cand)
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, TypeError):
            pass
    i, k = s.find("{"), s.rfind("}")
    if i >= 0 and k > i:
        obj = json.loads(s[i:k + 1])
        if isinstance(obj, dict):
            return obj
    raise ValueError("输出里找不到合法的 JSON 对象")


def _pct(v: Any, digits: int = 2) -> str:
    try:
        return f"{float(v) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def _num(v: Any, digits: int = 2) -> str:
    try:
        return f"{float(v):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _snap_facts(symbol: str, horizon: str = "swing") -> dict:
    """把某个标的的量化快照整理成紧凑的事实字典（AI 上下文 + 兜底共用）。"""
    snap = market_snapshot(symbol, with_intraday=horizon == "intraday")
    if snap.get("error"):
        raise ValueError(f"{symbol} 无行情数据：{snap['error']}")
    local = analyze_local(snap, horizon)
    facts: dict[str, Any] = {
        "symbol": snap["symbol"],
        "as_of": snap["last_date"],
        "price": snap["price"],
        "horizon": horizon,
        "returns_pct": snap["returns"],
        "ma": snap["ma"],
        "dist_pct": snap["dist"],
        "levels": snap["levels"],
        "indicators": snap["indicators"],
        "realtime": snap.get("realtime") or {"realtime": False},
        "local_engine": {
            "regime": local.get("regime"),
            "regime_desc": local.get("regime_desc"),
            "bias": local.get("bias"),
            "score": local.get("composite_score"),
            "confidence": local.get("confidence"),
            "dimensions": local.get("dimensions"),
            "suggested_position_pct": local.get("suggested_position_pct"),
            "levels": local.get("levels"),
            "warnings": local.get("warnings"),
            "strategy_matches": local.get("strategy_matches"),
        },
    }
    if snap.get("intraday"):
        facts["intraday"] = snap["intraday"]
    return facts


# ==================================================================
# 运行入口
# ==================================================================
# 推理型模型（如 glm / deepseek-reasoner 一类）会把 token 预算先花在思维链上，
# 预算给少了就会出现「HTTP 200 但 content 为空」。实测（cn:glm-5.3-flash，
# 同一提示词只改 max_tokens，多次运行）：
#
#   max_tokens=2200 → finish=length，reasoning=2199，content 0 字
#   max_tokens=3072 → finish=length，reasoning=3042，content 0 字
#   max_tokens=4096 → finish=length，reasoning=3153，content 1475 字（被截断）
#   max_tokens=6144 → finish=stop，  reasoning=2415，content 1878 字（完整）
#   max_tokens=8192 → 网关自身超时失败（finish=None，content 0）
#
# 关键结论：
#   ① **思维链固定先烧掉 1800~3200 token**（波动很大），正文还要 ~1000-1500，
#      所以下限必须 ≥ 6144，否则要么空返回、要么正文被截断；
#   ② 上限**不能超过 6144** —— 8192 会让网关自己挂掉，所以补试时不再翻倍；
#   ③ max_tokens 只是上限、不按上限计费（6144 那次实际只生成约 3600 token）。
_MIN_TOKEN_BUDGET = 6144
_MAX_TOKEN_BUDGET = 6144

# 单次 LLM 调用最长等待。推理模型实测 40~90s，90s 的默认值会卡在边界上
# （出现 ReadTimeout 后静默降级为本地兜底，用户以为「AI 坏了」）。这里给到 180s。
_LLM_TIMEOUT = 180.0


def run_task(key: str, payload: dict | None = None, model: str = "",
             force_local: bool = False) -> dict[str, Any]:
    """执行一个 AI 任务。

    返回 `{task, title, engine, text, facts, data?, llm_error?}`。
    `engine="llm"` 表示由大模型生成，`"local"` 表示规则化兜底。
    `data` 仅结构化任务（登记时给了 `parse`）才有。
    任务不存在或数据不足时抛 ValueError，由 API 层转成 400。
    """
    task = TASKS.get(key)
    if task is None:
        raise ValueError(f"未知 AI 任务：{key}")
    payload = payload or {}
    prompt, facts = task.build(payload)
    out: dict[str, Any] = {
        "task": task.key,
        "title": task.title,
        "engine": "local",
        "text": "",
        "facts": _clean(facts),
    }
    if not force_local and (ai_configured() or model):
        msgs = [{"role": "system", "content": task.system},
                {"role": "user", "content": prompt}]
        budget = max(task.max_tokens, _MIN_TOKEN_BUDGET)
        try:
            t0 = time.monotonic()
            text = (_llm_call(msgs, temperature=task.temperature,
                              max_tokens=budget, model_name=model,
                              timeout=_LLM_TIMEOUT) or "").strip()
            # 空返回时补试一次。闸门取 60s：前端单次等待上限 240s，
            # 首调用若已耗时 60s+，再补一次就可能把总耗时推到超时，宁可直接降级。
            # 注意预算**不翻倍**（6144 已是网关上限，8192 会让网关失败）。
            if not text and time.monotonic() - t0 < 60:
                text = (_llm_call(msgs, temperature=task.temperature,
                                  max_tokens=min(budget * 2, _MAX_TOKEN_BUDGET),
                                  model_name=model, timeout=_LLM_TIMEOUT) or "").strip()
            if text:
                out["text"] = text
                out["engine"] = "llm"
            else:
                # 不能把 engine 标成 llm 却展示本地兜底文案 —— 那是误导。
                # 注意：这条文案由前端 AIAssist 以**纯文本**渲染（不是 Markdown），
                # 所以这里不能用 `**强调**` 语法，否则界面上会显示成字面星号。
                out["llm_error"] = (
                    f"模型返回了空内容（本次 token 预算 {budget}）。"
                    "最常见原因是推理模型把预算花在思维链上（本项目实测固定消耗 1800~3200 token）；"
                    "若频繁出现，建议在「设置 → AI 分析」改选一个非推理模型。"
                )
        except Exception as exc:  # noqa: BLE001 —— 失败必须静默降级到本地兜底
            out["llm_error"] = f"{type(exc).__name__}: {exc}"
    if not out["text"]:
        try:
            out["text"] = task.local(facts, payload)
        except Exception as exc:  # noqa: BLE001
            out["text"] = f"本地兜底也失败了：{type(exc).__name__}: {exc}"
    # 结构化任务：把 text 解析成 data（LLM 与本地兜底都走这一步 ——
    # 本地兜底也输出 JSON 文本，因此未配置 LLM 时智能选股同样可用）。
    if task.parse and out["text"]:
        try:
            out["data"] = task.parse(out["text"])
        except Exception as exc:  # noqa: BLE001 —— 解析失败不算任务失败，只是没有结构化结果
            note = f"结构化解析失败：{exc}"
            out["llm_error"] = f"{out['llm_error']} / {note}" if out.get("llm_error") else note
    return out


# 领域模块在导入时通过 _register 登记任务 —— 必须放在文件末尾，
# 保证上面的 _register / 工具函数已定义。
from . import (  # noqa: E402,F401
    ai_tasks_analysis,
    ai_tasks_intel,
    ai_tasks_market,
    ai_tasks_ops,
    ai_tasks_screen,
    ai_tasks_strategy,
)
