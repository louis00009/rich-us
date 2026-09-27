---
name: quantdesk-add-module
description: 给本地 QuantDesk for IBKR 量化平台（C:\Users\Louis\Desktop\IBKR）新增一个端到端功能模块的固定流程。当用户说「继续把核心功能补齐」「加一个 XX 模块」「实现 XX 功能」「新增 XX 页面」，或要求补齐某个已识别缺口（引擎能力 / API / 前端页面）时使用。覆盖顺序：先校准 todo → 引擎层 → API 层 → 前端层 → 自检 → 文档与记忆 → 端到端验证。
agent_created: true
---

# QuantDesk 新增全栈模块

工作区固定为 `C:\Users\Louis\Desktop\IBKR`。后端 FastAPI + SQLite，前端 React + Vite + Tailwind，
单端口 8787 由 FastAPI 托管 `frontend/dist`。

## 铁律（顺序不可调换）

1. **先校准 todo，再写代码**。用户明确要求过这一点。`TaskList` 拿到快照 → 把已完成项标 completed
   → 把本轮目标标 in_progress → 用 `TaskCreate` 拆出子任务（引擎 / API / 前端 / 自检各一条）。
2. **引擎层先落地并单独验证**，再接 API。引擎没跑通就写 API，会在两个层面同时排错。
3. **API 路由必须挂到 `app.openapi()["paths"]` 验证**，不能只看 `app.routes`（见下）。
4. **自检要能断言"约束真的生效"**，不能只断言"接口返回 200"。
5. **收尾必须更新 README + `.workbuddy/memory/`**，否则下一轮会重新发现同样的事。

## 各层落点

| 层 | 文件 | 约定 |
|---|---|---|
| 引擎 | `backend/app/engine/<name>.py` | 纯 numpy/pandas，不引入新依赖 |
| 导出 | `backend/app/engine/__init__.py` | 加进 `__all__`，否则 API 层 import 不到 |
| 请求模型 | `backend/app/schemas.py` | Pydantic，`Field(...)` 带范围约束；`field_validator` 规范化 symbols |
| 路由 | `backend/app/api/<name>.py` | `APIRouter(prefix="/<name>", tags=[...])`，用 `CurrentUser` / `DbSession` |
| 挂载 | `backend/app/api/__init__.py` | import + `include_router` |
| 长任务 | 路由内 `await run_in_threadpool(fn)` | 同步计算不能阻塞事件循环 |
| 页面 | `frontend/src/pages/<Name>.tsx` | 复用 `components/ui.tsx` + `components/charts.tsx` |
| 路由 | `frontend/src/App.tsx` | `<Route path="/<name>" element={<Name />} />` |
| 入口 | `frontend/src/components/Layout.tsx` | `NAV` 数组加一项（lucide 图标需 import） |
| 自检 | `tests/run_checks.py` | 新增 `test_<name>()`，注册进 `main()` 的 `which` 分支 |
| 冒烟 | `frontend/render-smoke.mjs` | `ROUTES` 数组加一项 + 至少 1 项交互检查 |

## 关键陷阱（都实际踩过）

### 1. `include_router` 是惰性的 —— 枚举路由必须走 openapi()
该 FastAPI 版本里 `app.routes` / `api_router.routes` 装的是 `_IncludedRouter` 包装对象，
`getattr(r, "path")` 全是 `""`。验证路由是否挂上：

```python
from app.main import app
paths = sorted(p for p in app.openapi()["paths"] if "<name>" in p)
assert "/api/<name>/run" in paths
```

### 2. 自检脚本的断言顺序也会错
典型翻车：先 `DELETE` 掉记录，再断言"同名重复创建被拒" —— 测的其实是"删干净了没"。
凡涉及"拒绝"的断言，必须在触发条件**仍然成立**时执行。

### 3. 主进程会拦截删除
`rm` / `fs.rmSync` 在大批量或特定路径下会被拦截。对策：
- 清理临时文件：单个 `rm -f` 通常可行；超过 50 个文件改用重命名归档。
- 前端 Vite 的 `emptyOutDir` 必须保持 `false`，靠 `scripts/prebuild.mjs` 重命名归档旧 dist。

### 4. 不要用 heredoc 写 Python
`python - <<'PY' ... PY` 会被 shell 解析炸掉（表现为 SIGTERM 无输出）。
用 Write 工具写脚本文件再执行，用完 `rm -f` 删掉。

### 5. 长耗时接口前端要传 `LONG_TIMEOUT`
`frontend/src/lib/api.ts` 默认超时 30s；回测/寻优/优化这类接口必须显式传 `LONG_TIMEOUT`（300s）。

## 自检该断言什么（以组合优化为例的范式）

不要停在「200 OK」。要断言**业务不变量**：

- 结果向量的约束是否被严格遵守（如权重和 == 总仓位、单标的上限、簇上限）
- 数值自洽（如相关矩阵对角=1、对称；两条代码路径给出的同一数据一致）
- **异常输入抛的是业务异常而不是崩溃**（`OptimizeError` 而非 `KeyError`）
- **静默降级必须被标记**（约束无解时自动放宽必须带 `*_relaxed` 标志 + 备注）

用**合成数据**（`np.random.default_rng(42)` + 受控相关结构）而非真实行情：
约束是否生效必须可复现，不能因数据源断网降级到合成而漂移。
真实行情的端到端演示另写一个脚本（如 `tests/optimize_e2e.py`），在 README 注明。

## 收尾清单

```bash
cd backend && .venv/Scripts/python.exe ../tests/run_checks.py        # 全绿
cd frontend && npm run typecheck                                     # 零错误
cd frontend && npm run build
# 启动服务后
cd frontend && npm run smoke                                         # 全绿 + 零运行时错误
```

然后更新：
- `README.md`：目录树、自检项数、新功能章节（新增章节要顺延后续编号）、自检命令
- `.workbuddy/memory/YYYY-MM-DD.md`：追加本轮做了什么（append-only）
- `.workbuddy/memory/MEMORY.md`：本次新增的**不可破坏的设计约定**与命令速查数字
