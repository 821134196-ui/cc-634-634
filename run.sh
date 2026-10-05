#!/usr/bin/env bash
# 一条命令启动：签证材料原件托管与领回系统
# 用法：./run.sh [--reset] [--port 8000]
set -euo pipefail
cd "$(dirname "$0")"

PORT=8000
RESET=0
for arg in "$@"; do
  case "$arg" in
    --reset) RESET=1 ;;
    --port=*) PORT="${arg#--port=}" ;;
    *) echo "未知参数: $arg" >&2; exit 1 ;;
  esac
done

PYTHON_BIN="${PYTHON:-python3}"

# 1) 虚拟环境（Debian 精简镜像常缺 ensurepip，用 get-pip.py 兜底引导）
if [ ! -x .venv/bin/python ]; then
  echo ">> 创建虚拟环境 .venv"
  "$PYTHON_BIN" -m venv .venv 2>/dev/null || "$PYTHON_BIN" -m venv --without-pip .venv
fi
if ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
  echo ">> 引导安装 pip"
  curl -sSL https://bootstrap.pypa.io/get-pip.py -o /tmp/vcd-get-pip.py
  .venv/bin/python /tmp/vcd-get-pip.py -q
fi
echo ">> 安装 Python 依赖"
.venv/bin/python -m pip install -q -r requirements.txt

# 2) 前端静态目录（Vue 已内置于 frontend/vendor，无需联网、无需 Node 构建）
echo ">> 同步前端静态资源"
rm -rf frontend_dist
mkdir -p frontend_dist
cp -r frontend/. frontend_dist/

# 3) 初始化数据库与演示数据
if [ "$RESET" = "1" ]; then
  echo ">> 重置数据"
  .venv/bin/python -m backend.seed --reset
else
  .venv/bin/python -m backend.seed
fi

# 4) 启动（FastAPI 同时托管 API 与前端）
echo ">> 启动服务：http://127.0.0.1:${PORT}"
exec .venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port "$PORT"
