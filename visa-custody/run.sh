#!/usr/bin/env bash
# 一条命令启动：签证材料原件托管与领回系统
# 用法：
#   ./run.sh            首次会自动准备依赖并写入演示数据，然后启动服务
#   ./run.sh --reset    清空并重建演示数据后启动
#   PORT=8080 ./run.sh  指定端口
set -euo pipefail

cd "$(dirname "$0")"

PY=python3
PORT="${PORT:-8000}"
PYDEPS="$(pwd)/.pydeps"
export PYTHONPATH="$PYDEPS${PYTHONPATH:+:$PYTHONPATH}"
export PIP_DISABLE_PIP_VERSION_CHECK=1

echo "==> [1/4] 检查 Python"
$PY --version

# 1) 若目标依赖目录缺少 fastapi，则准备依赖
if ! PYTHONPATH="$PYDEPS" $PY -c "import fastapi, sqlalchemy, uvicorn, multipart" >/dev/null 2>&1; then
  echo "==> [2/4] 准备 Python 依赖到 ./.pydeps（项目自包含，不污染系统环境）"

  # 该环境可能没有 pip / venv（精简容器）。必要时把 pip 引导到用户目录。
  if ! $PY -m pip --version >/dev/null 2>&1; then
    echo "    未检测到 pip，使用 get-pip.py 引导到用户目录 ..."
    BOOT="$(mktemp -d)/get-pip.py"
    curl -fsSL https://bootstrap.pypa.io/get-pip.py -o "$BOOT"
    $PY "$BOOT" --user --break-system-packages
  fi

  $PY -m pip install --upgrade --target="$PYDEPS" -r requirements.txt
else
  echo "==> [2/4] 依赖已就绪 (.pydeps)"
fi

# 2) 初始化数据库 + 演示数据
NEED_SEED=0
if [ "${1:-}" = "--reset" ]; then
  NEED_SEED=1
elif [ ! -f "$(pwd)/data/custody.db" ]; then
  NEED_SEED=1
fi

if [ "$NEED_SEED" = "1" ]; then
  echo "==> [3/4] 初始化数据库并写入演示数据"
  $PY -m app.seed_data $([ "${1:-}" = "--reset" ] && echo --reset || true)
else
  echo "==> [3/4] 数据库已存在，跳过种子数据"
fi

# 3) 启动
echo "==> [4/4] 启动服务： http://127.0.0.1:${PORT}"
echo "    浏览器打开上述地址即可（演示账号见登录页 / README）。Ctrl+C 停止。"
exec $PY -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
