#!/bin/sh
# ============================================================
# 容器启动入口
# ------------------------------------------------------------
# 做了什么：
#   1) 若为 standalone 模式，先拉起 Ollama 并确保模型就位
#   2) 启动 core FastAPI（8000）
#   3) 启动 MCP Server（8080）
# 任何一步失败都直接退出，避免"容器活着但服务是死的"
# ============================================================
set -e

echo "[entrypoint] 启动 core 服务…"
uvicorn core.main:app --host 127.0.0.1 --port 8000 &
CORE_PID=$!

# 等 core 起来（最多 30 秒）
i=0
while [ $i -lt 30 ]; do
    if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
        echo "[entrypoint] core 就绪"
        break
    fi
    i=$((i + 1))
    sleep 1
done

if [ $i -ge 30 ]; then
    echo "[entrypoint][error] core 启动失败，退出"
    kill $CORE_PID 2>/dev/null || true
    exit 1
fi

# standalone 模式下拉起 Ollama
if command -v ollama >/dev/null 2>&1; then
    echo "[entrypoint] 启动 Ollama（模型 ${OLLAMA_MODEL}）…"
    ollama serve >/tmp/ollama.log 2>&1 &
    # 等 Ollama 端口可用
    j=0
    while [ $j -lt 60 ]; do
        if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
            break
        fi
        j=$((j + 1))
        sleep 1
    done
    # 模型未拉取则拉取（首次启动较慢，后续镜像层已缓存）
    ollama pull "${OLLAMA_MODEL}" || echo "[entrypoint][warn] 模型拉取失败，重构端点将不可用"
fi

echo "[entrypoint] 启动 MCP Server（${MCP_TRANSPORT} :${MCP_PORT}）…"
exec python adapters/fal_mcp/mcp_server.py
