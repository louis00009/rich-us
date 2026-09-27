#!/usr/bin/env bash
# ====================================================================
#  QuantDesk for IBKR — 一键启动（macOS / Linux / Git Bash）
# ====================================================================
set -e
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
VENV="backend/.venv"

echo "===================================================================="
echo "  QuantDesk for IBKR — 一键启动"
echo "===================================================================="

if [ ! -x "$VENV/bin/python" ]; then
  echo "[1/4] 创建 Python 虚拟环境..."
  "$PY" -m venv "$VENV"
  echo "[2/4] 安装后端依赖（约 1-3 分钟）..."
  "$VENV/bin/python" -m pip install --upgrade pip -q
  "$VENV/bin/pip" install -r backend/requirements.txt
else
  echo "[1/4] 虚拟环境已存在"
  echo "[2/4] 跳过依赖安装"
fi

if [ ! -f "frontend/dist/index.html" ]; then
  if [ ! -d "frontend/node_modules" ]; then
    echo "[3/4] 安装前端依赖..."
    (cd frontend && npm install --no-fund --no-audit)
  else
    echo "[3/4] 前端依赖已存在"
  fi
  echo "      构建前端..."
  (cd frontend && npm run build)
else
  echo "[3/4] 前端已构建，跳过"
fi

echo "[4/4] 启动服务..."
cd backend
exec ../"$VENV"/bin/python run.py
