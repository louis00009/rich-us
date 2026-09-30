"""数据层共享状态与工具（从 `data_provider.py` 拆出，铁律 9，2026-09-30）。

`_last_errors` 被「标的搜索 / 取数链 / 券商源」多方写入；
`_bounded_set` 是模块级缓存的通用有界写入（搜索缓存与报价缓存共用）。
放在这里可让 `symbol_search.py` 与 `data_provider.py` 共用而不产生循环导入。

⚠️ `_last_errors` 是**同一个 dict 对象**被多处 import 后写入 —— 只能 `d[k] = v`，
   不要整体重新赋值，否则各处看到的将不是同一份。
"""
from __future__ import annotations

from typing import Any


_CACHE_CAP = 2048


def _bounded_set(d: dict, key: Any, value: Any, cap: int = _CACHE_CAP) -> None:
    """向模块级缓存写入并限制容量（超出时按插入顺序淘汰最旧的键）。

    P3：这些缓存是模块级 dict，键来自用户输入的 symbol / 搜索词 ——
    不设上限时长时间运行会被慢慢撑大，且没有任何淘汰机制。
    """
    d.pop(key, None)          # 先删再插，刷新插入顺序（用于 FIFO 淘汰）
    d[key] = value
    if len(d) > cap:
        for k in list(d.keys())[: len(d) - cap]:
            d.pop(k, None)
_last_errors: dict[str, str] = {}
def recent_source_errors() -> dict[str, str]:
    """各数据源最近一次失败原因（诊断用，随时可清空重来）。"""
    return dict(_last_errors)
